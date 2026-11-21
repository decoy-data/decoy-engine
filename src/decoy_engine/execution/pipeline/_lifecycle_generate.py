"""Generate and mixed terms of the lifecycle estimate (F24, row 84, slice E2).

A generate table has no source to read, so it adds no ingest bytes. Its execute bytes are what a
resident run holds for its columns (`decoy_engine.generation` prices them, string payload
included) plus the largest unique-draw working set. Its write bytes are its Arrow output beside
the mask outputs. The mask half of a mixed job comes from `_lifecycle_inputs` as before.

Value-free: a note names a `table.column` and nothing else. This module reaches generation only
through the `decoy_engine.generation` package.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pyarrow as pa

from decoy_engine import generation
from decoy_engine.execution._mem_estimate import ColumnSizeSpec
from decoy_engine.execution._mem_estimate_arrow import Declared, Fixed, Sampled, classify_column
from decoy_engine.execution._mem_estimate_schema import generate_dict_column_width_bytes
from decoy_engine.execution._pipeline_context import classify_table_kinds
from decoy_engine.execution.pipeline import _lifecycle as lc
from decoy_engine.execution.pipeline import _lifecycle_inputs as li


@dataclass(frozen=True)
class Generated:
    """`inputs` is None when the lifecycle cannot be priced; `notes` says why."""

    inputs: lc.GeneratedInputs | None
    notes: tuple[str, ...] = ()


def _declared_widths(generate_tables: list[Mapping[str, Any]]) -> dict[tuple[str, str], float]:
    """The declared text width of each generate column that has one, by `(table, column)`."""
    widths: dict[tuple[str, str], float] = {}
    for t in generate_tables:
        for col in t["generate_columns"]:
            width = generate_dict_column_width_bytes(str(col.get("type")), col)
            if width is not None:
                widths[(t["name"], col["name"])] = width
    return widths


def _column_inputs(name: str, arrow_type: pa.DataType, width: float) -> lc.ColumnInputs:
    """A generated column's size spec from its Arrow type, the way a resident frame holds it."""
    priced = classify_column(arrow_type, has_nulls=False)
    if isinstance(priced, Fixed):
        spec = ColumnSizeSpec(name, priced.label)
    elif isinstance(priced, Declared):
        spec = ColumnSizeSpec(name, "object", string_width_bytes=priced.width_bytes)
    elif isinstance(priced, Sampled):
        spec = ColumnSizeSpec(name, "object", string_width_bytes=width)
    else:
        raise ValueError("generated column has no size model")
    return lc.ColumnInputs(name, arrow_type, False, spec)


def generated_inputs(config: Mapping[str, Any]) -> Generated:
    """The generate tables of `config` as lifecycle inputs, or a note naming why not."""
    kinds = classify_table_kinds(dict(config))
    generate_tables = [
        t for t in config.get("tables") or [] if kinds.get(t.get("name")) == "generate"
    ]
    terms = generation.generated_lifecycle_terms(dict(config), _declared_widths(generate_tables))
    if terms.unpriced:
        return Generated(None, (lc.NOTE_GENERATE_WIDTH.format(column=terms.unpriced[0]),))
    tables: list[lc.TableInputs] = []
    for t in generate_tables:
        columns = tuple(
            _column_inputs(c.column, c.arrow_type, c.width)
            for c in terms.columns
            if c.table == t["name"]
        )
        tables.append(
            lc.TableInputs(
                name=t["name"],
                rows=int(t.get("row_count") or 0),
                columns=columns,
                source_format="generate",
            )
        )
    attached = li.attach_targets(tuple(tables), config)
    if attached.tables is None:
        return Generated(None, attached.notes)
    return Generated(
        lc.GeneratedInputs(
            tables=attached.tables,
            peak_bytes=terms.peak_bytes,
        )
    )
