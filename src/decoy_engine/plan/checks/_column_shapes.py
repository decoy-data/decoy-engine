"""The shape of every column a shape-reading strategy touches, assembled from every fact we hold.

``build_column_shapes`` is the one function the plan check, ``compile_plan`` and
``run_config_only_checks`` call to get shapes. For each column it takes the first fact that
applies: an F06 declaration, a ``nested`` child, a text source format, the profile's observed
shape, the source schema, else ``unknown``. A text format comes before the profile so a profile
taken before a format edit cannot override the config.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping
from typing import TYPE_CHECKING, Any

from decoy_engine._nested_json import nested_children
from decoy_engine.contracts.column_shape import (
    TEXT_SOURCE_FORMATS,
    ColumnShape,
    ColumnShapes,
    classify_column,
    declared_shape,
    source_format_for,
)
from decoy_engine.contracts.strategy_requirements import SHAPE_REQUIREMENTS_BY_STRATEGY

if TYPE_CHECKING:
    import pyarrow as pa

    from decoy_engine.profile._types import Profile

__all__ = ["build_column_shapes", "shape_reading_columns"]


def _reads_shape(col: Mapping[str, Any]) -> bool:
    """Whether this column's strategy, or its nested child's, has a shape rule."""
    strategy = col.get("strategy")
    if strategy in SHAPE_REQUIREMENTS_BY_STRATEGY:
        return True
    provider_config = col.get("provider_config")
    if strategy == "nested" and isinstance(provider_config, Mapping):
        return any(
            c.strategy in SHAPE_REQUIREMENTS_BY_STRATEGY for c in nested_children(provider_config)
        )
    return False


def shape_reading_columns(config: Mapping[str, Any]) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Each ``(table name, column entry)`` under a strategy that has a shape rule, in config order."""
    tables = config.get("tables")
    for table in tables if isinstance(tables, list) else []:
        if not isinstance(table, dict) or not isinstance(table.get("name"), str):
            continue
        for col in table.get("columns") or []:
            if isinstance(col, dict) and isinstance(col.get("name"), str) and _reads_shape(col):
                yield table["name"], col


def _profiled(profile: Profile | None, table: str, column: str) -> ColumnShape:
    if profile is None:
        return ColumnShape.UNKNOWN
    for t in profile.tables:
        if t.name == table:
            for c in t.columns:
                if c.name == column:
                    return c.shape
    return ColumnShape.UNKNOWN


def _from_schema(
    source_schemas: Mapping[str, pa.Schema] | None,
    table: str,
    column: str,
    source_format: str | None,
) -> ColumnShape:
    schema = (source_schemas or {}).get(table)
    if schema is None or column not in schema.names:
        return ColumnShape.UNKNOWN
    return classify_column(source_format=source_format, arrow_type=schema.field(column).type)


def build_column_shapes(
    config: Mapping[str, Any],
    *,
    profile: Profile | None = None,
    source_schemas: Mapping[str, pa.Schema] | None = None,
    resident_tables: Collection[str] = (),
) -> ColumnShapes:
    """``(table, column) -> shape`` for every column under a shape-reading strategy.

    ``resident_tables`` names the tables the caller supplied in memory: those are shaped by their
    own schema, never by a config descriptor's file format."""
    out: dict[tuple[str, str], ColumnShape] = {}
    for table, col in shape_reading_columns(config):
        name = col["name"]
        fmt = source_format_for(config.get("sources"), table, resident=resident_tables)
        if col.get("logical_type") is not None:
            shape = declared_shape(
                logical_type=col["logical_type"], parse_format=col.get("parse_format")
            )
        elif col.get("strategy") == "nested" or fmt in TEXT_SOURCE_FORMATS:
            shape = ColumnShape.TEXT
        else:
            shape = _profiled(profile, table, name)
            if shape is ColumnShape.UNKNOWN:
                shape = _from_schema(source_schemas, table, name, fmt)
        out[(table, name)] = shape
    return dict(sorted(out.items()))
