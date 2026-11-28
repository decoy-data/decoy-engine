"""The shape of a column: what a strategy that reads the value can rely on.

One closed vocabulary (``ColumnShape``) and the only two functions that map a type to a shape.
``classify_column`` maps what the data is (source format, then Arrow type). ``declared_shape``
maps an F06 declaration. Both are called from places named in
``tests/sentry/test_column_shape_classifier.py``: the profile walk, the plan's shape
assembler and the scan. A stored token is never mapped to ``other``: an unknown token is refused where it is
loaded. This module imports ``pyarrow`` and ``_arrow_types`` only.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pyarrow as pa

from decoy_engine._arrow_types import is_text

__all__ = [
    "EXACT_FLOAT_DECIMAL_DIGITS",
    "NO_SOURCES",
    "TEXT_SOURCE_FORMATS",
    "TYPED_DATE_SHAPES",
    "ColumnShape",
    "ColumnShapes",
    "SourceFacts",
    "build_source_facts",
    "classify_column",
    "declared_shape",
    "is_bounded_decimal",
    "is_nested_type",
    "native_date_shapes",
    "source_facts_of",
    "source_format_for",
    "table_source_facts",
]

# IEEE 754 binary64 carries 15 significant decimal digits exactly (DBL_DIG).
EXACT_FLOAT_DECIMAL_DIGITS = 15

# Source formats whose reader gives text whatever it inferred: a CSV cell is untyped on every
# reader, so a column from one of these formats is text until a declaration says otherwise.
TEXT_SOURCE_FORMATS = frozenset({"csv", "fixed_width"})


# The source kind of a table the caller supplied in memory: it has no file format, so its
# columns are shaped by the table's own schema.
RESIDENT_SOURCE_FORMAT = "table"


def source_format_for(
    descriptors: Mapping[str, Any] | None, table: str, *, resident: Collection[str] = ()
) -> str | None:
    """The source format that shapes ``table``: ``table`` for a caller-supplied resident table,
    else the config descriptor's ``format``. The one place this is decided, so every route
    (plan check, profile walk, chunked entries) classifies a table the same way."""
    if table in resident:
        return RESIDENT_SOURCE_FORMAT
    descriptor = (descriptors or {}).get(table)
    fmt = descriptor.get("format") if isinstance(descriptor, Mapping) else None
    return fmt if isinstance(fmt, str) else None


@dataclass(frozen=True)
class SourceFacts:
    """Experimental: what the caller holds for each table it supplied: its Arrow schema (when known) and
    whether it is resident. A resident table is shaped by its own schema, never by the file
    format of a config descriptor. Every compile route builds this with `build_source_facts`
    and `compile_plan` requires it, so no route can forget either half."""

    schemas: Mapping[str, pa.Schema] = field(default_factory=dict)
    resident: frozenset[str] = frozenset()


NO_SOURCES = SourceFacts()


def build_source_facts(
    *,
    caller: Mapping[str, pa.Schema | None],
    loader: Mapping[str, pa.Schema] | None = None,
) -> SourceFacts:
    """The one builder of `SourceFacts`: tables the caller supplied in memory (``None`` when
    its schema is unknown, e.g. a chunk iterable with no chunks) and tables a source loader
    supplies with typed schemas. Both are resident."""
    known = {n: s for n, s in caller.items() if s is not None}
    return SourceFacts(
        schemas={**known, **(loader or {})}, resident=frozenset(caller) | frozenset(loader or ())
    )


def table_source_facts(table: str, schema: pa.Schema | None, siblings: SourceFacts) -> SourceFacts:
    """The job's ``siblings`` with the one table a route is masking set to its own schema: a
    per-table route still shapes the other tables by their schemas, not by their descriptors."""
    own = build_source_facts(caller={table: schema})
    return SourceFacts(
        schemas={**siblings.schemas, **own.schemas}, resident=siblings.resident | own.resident
    )


def source_facts_of(
    tables: Mapping[str, Any] | None, loader: Mapping[str, pa.Schema] | None = None
) -> SourceFacts:
    """`build_source_facts` for a map of caller tables (``pa.Table`` or a lazy source): each
    table's ``schema`` is its schema."""
    return build_source_facts(
        caller={n: t.schema for n, t in (tables or {}).items()}, loader=loader
    )


def is_nested_type(arrow_type: pa.DataType) -> bool:
    """A list, struct, map or union type: its cells are unhashable to pandas."""
    t = pa.types
    return bool(
        t.is_list(arrow_type)
        or t.is_large_list(arrow_type)
        or t.is_fixed_size_list(arrow_type)
        or t.is_struct(arrow_type)
        or t.is_map(arrow_type)
        or t.is_union(arrow_type)
    )


class ColumnShape(str, Enum):
    TEXT = "text"
    DATE = "date"
    TIMESTAMP_TZ = "timestamp_tz"
    TIMESTAMP_NAIVE = "timestamp_naive"
    INTEGER = "integer"
    FLOAT = "float"
    DECIMAL = "decimal"
    DECIMAL_WIDE = "decimal_wide"
    BOOLEAN = "boolean"
    OTHER = "other"
    UNKNOWN = "unknown"


ColumnShapes = Mapping[tuple[str, str], ColumnShape]

# The shapes a date strategy reads as dates with no parse format. Every site that asks "is this
# column a native date" reads this set, and a sentry test fails if one keeps its own copy.
TYPED_DATE_SHAPES = frozenset({ColumnShape.DATE, ColumnShape.TIMESTAMP_TZ})


def native_date_shapes(
    shapes: Mapping[tuple[str, str], ColumnShape], declared: Collection[tuple[str, str]]
) -> dict[tuple[str, str], ColumnShape]:
    """The (table, column) entries of ``shapes`` that are native dates or zoned timestamps.

    The one producer of that view: ``StrategyContext.native_date_columns`` and the chunked source
    gate both call it. A declared date column keeps its text output, so ``declared`` leaves it out.
    """
    return {k: v for k, v in shapes.items() if v in TYPED_DATE_SHAPES and k not in declared}


def is_bounded_decimal(precision: Any, scale: Any) -> bool:
    """Whether ``0 <= scale <= precision <= 15``: a decimal float64 can bucket exactly."""
    return (
        type(precision) is int
        and type(scale) is int
        and 0 <= scale <= precision <= EXACT_FLOAT_DECIMAL_DIGITS
    )


def _decimal_shape(precision: Any, scale: Any) -> ColumnShape:
    return ColumnShape.DECIMAL if is_bounded_decimal(precision, scale) else ColumnShape.DECIMAL_WIDE


def classify_column(*, source_format: str | None, arrow_type: pa.DataType | None) -> ColumnShape:
    """The shape of the data in one column: the source format first, then its Arrow type.

    ``arrow_type=None`` means no schema is known here and gives ``unknown``.
    """
    if source_format in TEXT_SOURCE_FORMATS:
        return ColumnShape.TEXT
    if arrow_type is None:
        return ColumnShape.UNKNOWN
    t = arrow_type
    # A dictionary-encoded string holds text; the encoding is not a different shape.
    if pa.types.is_dictionary(t) and is_text(t.value_type):
        return ColumnShape.TEXT
    if is_text(t):
        return ColumnShape.TEXT
    if pa.types.is_date(t):
        return ColumnShape.DATE
    if pa.types.is_timestamp(t):
        return ColumnShape.TIMESTAMP_TZ if t.tz is not None else ColumnShape.TIMESTAMP_NAIVE
    if pa.types.is_integer(t):
        return ColumnShape.INTEGER
    if pa.types.is_floating(t):
        return ColumnShape.FLOAT
    if pa.types.is_decimal(t):
        return _decimal_shape(t.precision, t.scale)
    if pa.types.is_boolean(t):
        return ColumnShape.BOOLEAN
    return ColumnShape.OTHER


def declared_shape(*, logical_type: str, parse_format: Mapping[str, Any] | None) -> ColumnShape:
    """The shape an F06 declaration gives the column once the boundary has cast it."""
    if logical_type == "date":
        return ColumnShape.DATE
    if logical_type == "integer":
        return ColumnShape.INTEGER
    if logical_type in ("decimal", "currency"):
        fmt = parse_format if isinstance(parse_format, Mapping) else {}
        return _decimal_shape(fmt.get("precision"), fmt.get("scale"))
    if logical_type == "string":
        return ColumnShape.TEXT
    return ColumnShape.OTHER
