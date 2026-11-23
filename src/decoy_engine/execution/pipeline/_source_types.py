"""The one output assembler: a masked pandas frame becomes an output table here and nowhere else.

Columns no strategy changed are written from the source Arrow column as stored, so pandas never
changes their type on any route (UF-DOMAIN S1, plan 2026-11-22-uf-domain.md).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

import pandas as pd
import pyarrow as pa

from decoy_engine import reasons
from decoy_engine._arrow_types import TextWidthState, is_text
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.safe_output import attach_output_metadata


def _with_source_types(
    table: pa.Table, schema: pa.Schema | None, names: Collection[str]
) -> pa.Table:
    """Give each named column its source Arrow type back where pandas lost it.

    A date strategy hands pandas ``datetime.date`` cells, which Arrow reads as ``date32`` (so a
    ``date64`` source changes type) and, for an all-null chunk, as ``null`` (so chunk schemas
    differ) and a decimal gets the precision pandas' object round trip changed. Only those losses
    are repaired; any other type difference is left as it is.
    """
    if schema is None:
        return table
    for name in names:
        if name not in table.column_names or name not in schema.names:
            continue
        want = schema.field(name).type
        have = table.schema.field(name).type
        if have != want and (
            pa.types.is_null(have)
            or (pa.types.is_date64(want) and have == pa.date32())
            or (pa.types.is_decimal(want) and pa.types.is_decimal(have))
        ):
            position = table.schema.get_field_index(name)
            table = table.set_column(position, name, table.column(position).cast(want))
    return table


def _stored_index_names(source: pa.Table) -> list[str]:
    """The source columns its pandas metadata stores as the frame index. A name the schema does
    not hold (stale metadata) is not one."""
    listed = (source.schema.pandas_metadata or {}).get("index_columns", [])
    return [
        c
        for c in dict.fromkeys(x for x in listed if isinstance(x, str))
        if c in source.schema.names
    ]


def _expected_index(source: pa.Table, stored: list[str]) -> pd.Index:
    """The index `to_pandas()` gives this source: the values of its stored index columns, else
    the range its own pandas metadata describes (any start and step, so `df.iloc[::2]` and
    `df.iloc[::-1]` sources hold), else `0..n`."""
    if stored:
        values = source.select(stored).replace_schema_metadata(None).to_pandas()
        return pd.MultiIndex.from_frame(values) if len(stored) > 1 else pd.Index(values[stored[0]])
    for entry in (source.schema.pandas_metadata or {}).get("index_columns", []):
        if isinstance(entry, dict) and entry.get("kind") == "range":
            try:
                found = pd.RangeIndex(int(entry["start"]), int(entry["stop"]), int(entry["step"]))
            except (KeyError, TypeError, ValueError):
                break
            if len(found) == source.num_rows:
                return found
            break
    return pd.RangeIndex(source.num_rows)


def _rows_changed(detail: str) -> ExecutionError:
    """Refusal: the frame is no longer the source's rows. Counts only, never a name or value."""
    summary = reasons.get("runtime", reasons.runtime.OUTPUT_ASSEMBLY_ROWS_CHANGED).summary
    return ExecutionError(
        code=reasons.runtime.OUTPUT_ASSEMBLY_ROWS_CHANGED, message=f"{summary} {detail}"
    )


def _columns_mismatch(detail: str) -> ExecutionError:
    """Refusal: the frame's columns are not the source's, in order. Counts only."""
    summary = reasons.get("runtime", reasons.runtime.OUTPUT_ASSEMBLY_COLUMNS_MISMATCH).summary
    return ExecutionError(
        code=reasons.runtime.OUTPUT_ASSEMBLY_COLUMNS_MISMATCH, message=f"{summary} {detail}"
    )


def table_from_pandas_keeping_source_types(
    frame: pd.DataFrame,
    source: pa.Table | None,
    untouched: Collection[str],
    keep_types: Collection[str] = (),
    arrow_columns: Mapping[str, pa.Array | pa.ChunkedArray] | None = None,
) -> pa.Table:
    """The one place a masked pandas frame becomes an output table.

    The output has the source's row count and column order. Each `untouched` column (the columns
    no strategy changed, `_chunked_carry.untouched_columns`) is the source column as stored, so
    pandas never gets to change its type (decimal precision, nullable ints, `large_string`,
    nested types). Each `arrow_columns` entry is that array as given. Every other column comes
    from the frame through `from_pandas`, as a masked column always did; `keep_types` names the
    date columns whose source type is restored after that conversion.

    The frame must still be the source's rows: same count and an index still in source order (no row
    dropped or reordered since the source was read), and its remaining columns in source order. A
    mismatch raises `ExecutionError` before any output exists; the message carries counts only.
    With `source=None` there is nothing to keep, and the whole frame converts."""
    if source is None:
        return pa.Table.from_pandas(frame, preserve_index=False)
    given = dict(arrow_columns or {})
    n_rows = source.num_rows
    # A source that stores its pandas index as a column reads back with that column as the frame
    # index, so the frame no longer holds it. The output drops it, unless a rule left it untouched
    # (a configured passthrough column is never dropped).
    stored_index = _stored_index_names(source)
    if frame.shape[0] != n_rows:
        raise _rows_changed(
            f"The frame has {frame.shape[0]} rows and the source has {n_rows}.",
        )
    if not frame.index.equals(_expected_index(source, stored_index)):
        raise _rows_changed(
            f"The frame index no longer matches the source row order ({n_rows} rows).",
        )
    dropped = {c for c in stored_index if c not in untouched and c not in given}
    names = [c for c in source.schema.names if c not in dropped]
    source_names = set(names)
    carried = {c for c in names if c in untouched or c in given}
    # Source columns keep the source's order. A column the frame holds and the source does not
    # (a created target) sits where the frame put it.
    in_frame = [c for c in names if c in frame.columns]
    if [c for c in frame.columns if c in source_names] != in_frame or any(
        c not in frame.columns and c not in carried for c in names
    ):
        raise _columns_mismatch(
            f"The frame has {frame.shape[1]} columns and the source has {len(names)}.",
        )
    order = list(frame.columns)
    previous: str | None = None
    for name in names:
        if name in frame.columns:
            previous = name
            continue
        order.insert(0 if previous is None else order.index(previous) + 1, name)
        previous = name
    from_frame = [c for c in frame.columns if c not in carried]
    built = pa.Table.from_pandas(frame[from_frame], preserve_index=False)
    built = _with_source_types(built, source.schema, keep_types)
    fields: list[pa.Field] = []
    columns: list[pa.Array | pa.ChunkedArray] = []
    for name in order:
        if name in given:
            columns.append(given[name])
            fields.append(pa.field(name, given[name].type))
        elif name in carried:
            column = source.column(name)
            field = source.schema.field(name)
            if is_text(field.type):
                # O3: carried text leaves as `string` while it fits 32-bit offsets.
                column = TextWidthState().observe_column(column)
                field = field.with_type(column.type)
            columns.append(column)
            fields.append(field)
        else:
            columns.append(built.column(name))
            fields.append(built.schema.field(name))
    # Row count comes from the source: from_pandas of a zero-column frame has zero rows.
    # A carried column's pandas dtype hint (`Int64`, `string`) is the one its frame column has;
    # a zero-row conversion reads it without copying any cell.
    held = [c for c in names if c in carried and c in frame.columns]
    hints = pa.Table.from_pandas(frame[held].iloc[:0], preserve_index=False).schema.metadata
    schema = attach_output_metadata(
        pa.schema(fields),
        built.schema.metadata,
        carried=carried,
        carried_meta=hints,
    )
    return pa.Table.from_arrays(columns, schema=schema)


__all__ = ["table_from_pandas_keeping_source_types"]
