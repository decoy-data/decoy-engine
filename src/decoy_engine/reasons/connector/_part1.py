"""Catalog of the ``connector`` namespace, part 1."""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import UNRELEASED as UNRELEASED
from decoy_engine.reasons._types import Outcome, RetryClass

__all__ = [
    "AMBIGUOUS_NAME",
    "CATALOG_READ_FAILED",
    "COLUMN_NAME_UNSUPPORTED",
    "COLUMN_NOT_FOUND",
    "DEADLINE_EXCEEDED",
    "DUCKDB_UNAVAILABLE",
    "DUPLICATE_RELATION",
    "EXPORT_FAILED",
    "EXTENSION_UNAVAILABLE",
    "EXTENSION_UNTRUSTED_LOCATION",
    "NO_SELECTIONS",
    "RELATION_NOT_FOUND",
    "RELATION_SHAPE_CHANGED",
    "SOURCE_UNREACHABLE",
    "UNSUPPORTED_COLUMN_TYPE",
    "VALUE_GUARD_FAILED",
    "VALUE_NOT_REPRESENTABLE",
]

_d = _catalog.connector("PostgresSnapshotError")

# Usage codes: the user can repair the config or the database, so the CLI exits 1, not 3.
# POSTGRES_SOURCE_USAGE_CODES is computed from this outcome.
_USAGE = Outcome.CONFIGURATION
_FIX = RetryClass.CONFIGURATION_REPAIR

AMBIGUOUS_NAME = _d("ambiguous_name", "Ambiguous name.", outcome=_USAGE, retry=_FIX)
CATALOG_READ_FAILED = _d("catalog_read_failed", "Catalog read failed.")
COLUMN_NAME_UNSUPPORTED = _d(
    "column_name_unsupported",
    "Column name unsupported.",
    outcome=_USAGE,
    retry=_FIX,
    since="1.30.0",
)
COLUMN_NOT_FOUND = _d("column_not_found", "Column not found.", outcome=_USAGE, retry=_FIX)
DEADLINE_EXCEEDED = _d("deadline_exceeded", "Deadline exceeded.")
DUCKDB_UNAVAILABLE = _d("duckdb_unavailable", "Duckdb unavailable.")
DUPLICATE_RELATION = _d("duplicate_relation", "Duplicate relation.", outcome=_USAGE, retry=_FIX)
EXPORT_FAILED = _d("export_failed", "Export failed.")
EXTENSION_UNAVAILABLE = _d(
    "extension_unavailable", "Extension unavailable.", outcome=_USAGE, retry=_FIX
)
EXTENSION_UNTRUSTED_LOCATION = _d(
    "extension_untrusted_location",
    "Extension untrusted location.",
    outcome=_USAGE,
    retry=_FIX,
)
NO_SELECTIONS = _d("no_selections", "No selections.")
RELATION_NOT_FOUND = _d("relation_not_found", "Relation not found.", outcome=_USAGE, retry=_FIX)
RELATION_SHAPE_CHANGED = _d(
    "relation_shape_changed",
    "Relation shape changed.",
    outcome=_USAGE,
    retry=_FIX,
    since="1.30.0",
)
SOURCE_UNREACHABLE = _d("source_unreachable", "Source unreachable.")
UNSUPPORTED_COLUMN_TYPE = _d(
    "unsupported_column_type", "Unsupported column type.", outcome=_USAGE, retry=_FIX
)
VALUE_GUARD_FAILED = _d("value_guard_failed", "Value guard failed.")
VALUE_NOT_REPRESENTABLE = _d(
    "value_not_representable", "Value not representable.", outcome=_USAGE, retry=_FIX
)
