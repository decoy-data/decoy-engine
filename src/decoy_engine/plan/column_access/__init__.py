"""Column-access declarations and the writer query, shared by execution and verification.

Both packages import this one registry downward, so the chunked carry, native admission and
the post-scan cannot disagree on which columns a config entry reads or writes.
"""

from __future__ import annotations

from decoy_engine.contracts.strategy_requirements import SIBLING_REFERENCE_KEYS
from decoy_engine.plan.column_access._declarations import (
    OWN_TARGET_CREATES,
    OWN_TARGET_SOURCE,
    PASSTHROUGH_OUTPUT_IS_INPUT,
    SURFACE_DECLARATIONS,
    ColumnAccess,
    column_access,
    composite_provider_offenders,
    created_columns,
    handler_written_columns,
    has_when,
    predicate_names,
    provider_is_composite,
    scalar_creating_reads,
    touched_columns,
)
from decoy_engine.plan.column_access._transform_ops import transform_op_writes
from decoy_engine.plan.column_access._writes import (
    ChildKey,
    KnownEmpty,
    KnownSet,
    TableWrites,
    Unknown,
    config_child_keys,
    may_write,
    written_columns_by_table,
)

__all__ = [
    "OWN_TARGET_CREATES",
    "OWN_TARGET_SOURCE",
    "PASSTHROUGH_OUTPUT_IS_INPUT",
    "SIBLING_REFERENCE_KEYS",
    "SURFACE_DECLARATIONS",
    "ChildKey",
    "ColumnAccess",
    "KnownEmpty",
    "KnownSet",
    "TableWrites",
    "Unknown",
    "column_access",
    "composite_provider_offenders",
    "config_child_keys",
    "created_columns",
    "handler_written_columns",
    "has_when",
    "may_write",
    "predicate_names",
    "provider_is_composite",
    "scalar_creating_reads",
    "touched_columns",
    "transform_op_writes",
    "written_columns_by_table",
]
