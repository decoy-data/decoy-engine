"""Catalog of the ``warning`` namespace: scan warnings from path observation in JSON columns."""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import UNRELEASED

__all__ = [
    "NESTED_CELLS_UNREADABLE",
    "NESTED_PATHS_TRUNCATED",
    "NESTED_PATH_KEY_SUSPECT",
]

_d = _catalog.warning("QualityWarning")

NESTED_CELLS_UNREADABLE = _d(
    "nested_cells_unreadable",
    "Some cells of a JSON column are malformed, too large or too deep, so its paths are partial.",
    since=UNRELEASED,
)
NESTED_PATHS_TRUNCATED = _d(
    "nested_paths_truncated",
    "A JSON column has more paths than the scan keeps, so some paths are not listed.",
    since=UNRELEASED,
)
NESTED_PATH_KEY_SUSPECT = _d(
    "nested_path_key_suspect",
    "Some object keys in a JSON column look like data, so the scan wrote them as a wildcard.",
    since=UNRELEASED,
)
