"""Bounded sample reads that fill the lifecycle estimate's `PhaseInputs` (F24, row 84).

This is the only lifecycle module that opens a file. Each source is read once for at most
`SAMPLE_ROWS` rows, the way the CLI reads that format. Column widths and null flags come from
the sample (Parquet nulls from the footer) through the same classifier the router uses. The
sample frames are dropped as soon as the per-column inputs are built.

Value-free: a failure becomes a note holding a table name and an exception type name, never
the exception text, a path or a cell value.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, replace
from typing import Any

import pyarrow as pa

from decoy_engine.execution._mem_estimate import ColumnSizeSpec
from decoy_engine.execution._mem_estimate_arrow import (
    _is_string_family,
    column_arrow_types,
    source_nullable_columns,
)
from decoy_engine.execution._mem_estimate_schema import table_size_spec_from_profile
from decoy_engine.execution._strategies import SCALAR_HANDLERS
from decoy_engine.execution.pipeline import _lifecycle as lc
from decoy_engine.profile._csv_reader import read_csv_source, resolve_csv_dialect
from decoy_engine.profile._lazy_build import build_lazy_source, descriptor_path
from decoy_engine.profile._readers import LazySource, build_profile_source

SAMPLE_ROWS = 10_000


@dataclass(frozen=True)
class Outcome:
    """`tables` is None when the lifecycle cannot be priced; `notes` says why."""

    tables: tuple[lc.TableInputs, ...] | None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Read:
    """What one format's reader hands back: the sample, the source that types its columns
    (the sample itself, or the Parquet footer) and the footer's largest row group."""

    sample: pa.Table
    typing: pa.Table | LazySource
    row_group_bytes: int = 0


def _read_csv(table: str, descriptor: dict[str, Any]) -> _Read:
    dialect = resolve_csv_dialect(descriptor, table=table)
    frame = read_csv_source(
        descriptor_path(descriptor, f"sources.{table}.path"),
        dialect,
        table=table,
        dtype=str,
        nrows=SAMPLE_ROWS,
        field_key=f"sources.{table}.path",
    )
    sample = pa.Table.from_pandas(frame, preserve_index=False)
    return _Read(sample, sample)


def _read_parquet(table: str, descriptor: dict[str, Any]) -> _Read:
    lazy = build_lazy_source(table, descriptor)
    if lazy is None:
        raise ValueError("no lazy parquet source")
    opened = lazy.open_batches(SAMPLE_ROWS)
    with closing(opened):
        first = next(iter(opened.batches), None)
        sample = opened.schema.empty_table() if first is None else pa.Table.from_batches([first])
        group_bytes = opened.facts.max_row_group_bytes
    return _Read(sample, lazy, group_bytes)


def _read_fixed_width(table: str, descriptor: dict[str, Any]) -> _Read:
    source = build_profile_source(descriptor, field_key=f"sources.{table}.path", table=table)
    sample = pa.Table.from_pandas(source.sample_frame(SAMPLE_ROWS), preserve_index=False)
    return _Read(sample, sample)


# Keys equal `FILE_FORMATS` (a guard test pins it); `lc.INGEST_TRANSIENT` and
# `lc.WRITE_TRANSIENT` carry the other half of the per-format rule.
SAMPLE_READERS: dict[str, Callable[[str, dict[str, Any]], _Read]] = {
    "csv": _read_csv,
    "parquet": _read_parquet,
    "fixed_width": _read_fixed_width,
}


def _is_empty_in_sample(column: pa.ChunkedArray) -> bool:
    """A string column with no non-null value in a non-empty sample has no width to measure."""
    if len(column) == 0:
        return False
    if pa.types.is_null(column.type):
        return True
    return _is_string_family(column.type) and column.null_count == len(column)


def _table_inputs(profile_table: Any, descriptor: dict[str, Any], fmt: str) -> lc.TableInputs:
    read = SAMPLE_READERS[fmt](profile_table.name, descriptor)
    types = column_arrow_types(read.typing, profile_table)
    arrays = {n: read.sample.column(n) for n in read.sample.column_names}
    size = table_size_spec_from_profile(
        profile_table,
        sample=arrays,
        arrow_types=types,
        masked_columns=source_nullable_columns(read.typing),
    )
    columns: list[lc.ColumnInputs] = []
    for spec in size.columns:
        if spec.name not in types:
            raise ValueError("column missing from the sample")
        arrow_type, has_nulls = types[spec.name]
        sampled = arrays.get(spec.name)
        if sampled is not None and _is_empty_in_sample(sampled):
            spec = ColumnSizeSpec(spec.name, "object", unpriceable=True)
        columns.append(lc.ColumnInputs(spec.name, arrow_type, has_nulls, spec))
    return lc.TableInputs(
        name=profile_table.name,
        rows=profile_table.row_count,
        columns=tuple(columns),
        source_format=fmt,
        row_group_bytes=read.row_group_bytes,
        rows_exact=profile_table.row_count_exact,
    )


def read_samples(config: Mapping[str, Any], mask_tables: Sequence[Any]) -> Outcome:
    """The per-table inputs for every mask table, read in config `sources` order (the order
    the CLI reads them). Never raises: any failure leaves `tables` None with a note."""
    by_name = {t.name: t for t in mask_tables}
    sources = config.get("sources") or {}
    ordered = [n for n in sources if n in by_name] + [n for n in by_name if n not in sources]
    tables: list[lc.TableInputs] = []
    for name in ordered:
        descriptor = sources.get(name)
        if not isinstance(descriptor, dict) or descriptor.get("type") != "file":
            return Outcome(None, (lc.NOTE_SOURCE_NOT_LOCAL.format(table=name),))
        fmt = descriptor.get("format")
        if not isinstance(fmt, str) or fmt not in SAMPLE_READERS or fmt not in lc.INGEST_TRANSIENT:
            return Outcome(None, (lc.NOTE_SOURCE_FORMAT.format(table=name),))
        try:
            tables.append(_table_inputs(by_name[name], descriptor, fmt))
        except Exception as exc:
            note = lc.NOTE_SAMPLE_UNREADABLE.format(table=name, error=type(exc).__name__)
            return Outcome(None, (note,))
    return Outcome(tuple(tables))


def _int_columns(layout: Any) -> frozenset[str]:
    if not isinstance(layout, dict) or not isinstance(layout.get("columns"), list):
        raise ValueError("layout has no column list")
    return frozenset(
        c["name"]
        for c in layout["columns"]
        if isinstance(c, dict) and c.get("type") == "int" and isinstance(c.get("name"), str)
    )


def attach_targets(tables: tuple[lc.TableInputs, ...], config: Mapping[str, Any]) -> Outcome:
    """Each table with its target format, and for fixed_width the layout's int columns and
    whether it declares transforms. A target the rules do not cover leaves `tables` None."""
    targets = config.get("targets") or {}
    transforms = {t.get("name"): bool(t.get("transforms")) for t in (config.get("tables") or [])}
    out: list[lc.TableInputs] = []
    for t in tables:
        target = targets.get(t.name)
        fmt = target.get("format") if isinstance(target, dict) else None
        if (
            not isinstance(target, dict)
            or target.get("type") != "file"
            or not isinstance(fmt, str)
            or fmt not in lc.WRITE_TRANSIENT
        ):
            return Outcome(None, (lc.NOTE_TARGET_FORMAT.format(table=t.name),))
        ints: frozenset[str] = frozenset()
        if fmt == "fixed_width":
            try:
                ints = _int_columns(target.get("layout"))
            except ValueError:
                return Outcome(None, (lc.NOTE_LAYOUT.format(table=t.name),))
        out.append(
            replace(
                t,
                target=lc.TargetInputs(fmt, ints),
                has_transforms=transforms.get(t.name, False),
            )
        )
    return Outcome(tuple(out))


def table_specs(tables: Sequence[lc.TableInputs]) -> tuple[Any, ...]:
    """The `TableSizeSpec` of each table, priced from its sample."""
    return tuple(lc.table_spec(t) for t in tables)


def _declared_output(
    column: lc.ColumnInputs, strategy: str | None, provider_config: Any
) -> tuple[ColumnSizeSpec, pa.DataType] | None:
    """The column as its strategy writes it, from the handler's own declaration, or None when
    the handler declares nothing for this column."""
    handler = SCALAR_HANDLERS.get(strategy) if strategy is not None else None
    if strategy is None:
        return column.spec, column.arrow_type
    if getattr(handler, "output_is_input", False):
        return column.spec, column.arrow_type
    width_of = getattr(handler, "output_string_width", None)
    width = width_of(provider_config) if callable(width_of) else None
    if width is None:
        return None
    spec = ColumnSizeSpec(column.name, "object", string_width_bytes=float(width))
    return spec, pa.string()


def attach_outputs(tables: tuple[lc.TableInputs, ...], plan: Any) -> Outcome:
    """Each column with its output form, read from the plan's column seeds and the strategy
    handlers' declarations. An FK child column takes its parent key column's output. A handler
    that declares nothing keeps a string input as it is and leaves a non-string input unpriced."""
    seeds = {
        (table, name): seed
        for table, table_seed in plan.seed_envelope.per_table
        for name, seed in table_seed.per_column
    }
    parent_of = {
        (child.table, column): (rel.parent.table, parent_column)
        for rel in plan.relationships
        for child in rel.children
        for column, parent_column in zip(child.columns, rel.parent.columns, strict=True)
    }
    by_key = {(t.name, c.name): c for t in tables for c in t.columns}
    resolved: dict[tuple[str, str], tuple[ColumnSizeSpec, pa.DataType] | None] = {}

    def output_of(key: tuple[str, str]) -> tuple[ColumnSizeSpec, pa.DataType] | None:
        if key not in resolved:
            resolved[key] = None  # a cycle in the edges resolves to "undeclared"
            parent = parent_of.get(key)
            if parent is not None and parent in by_key:
                resolved[key] = output_of(parent)
            else:
                seed = seeds.get(key)
                strategy = None if seed is None else seed.strategy
                config = () if seed is None else seed.provider_config
                resolved[key] = _declared_output(by_key[key], strategy, config)
            if resolved[key] is None and by_key[key].spec.string_width_bytes is not None:
                resolved[key] = (by_key[key].spec, by_key[key].arrow_type)
        return resolved[key]

    out: list[lc.TableInputs] = []
    for t in tables:
        columns: list[lc.ColumnInputs] = []
        for c in t.columns:
            declared = output_of((t.name, c.name))
            if declared is None:
                note = lc.NOTE_OUTPUT_WIDTH.format(column=f"{t.name}.{c.name}")
                return Outcome(None, (note,))
            columns.append(replace(c, output_spec=declared[0], output_arrow_type=declared[1]))
        out.append(replace(t, columns=tuple(columns)))
    return Outcome(tuple(out))
