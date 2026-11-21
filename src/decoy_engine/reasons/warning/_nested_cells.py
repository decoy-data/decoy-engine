"""Catalog of the ``warning`` namespace: nested-cell faults from the bounded cell reader."""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import UNRELEASED

__all__ = [
    "NESTED_CELL_DUPLICATE_KEY",
    "NESTED_CELL_NUMBER_OUT_OF_RANGE",
    "NESTED_CELL_OVERSIZED",
    "NESTED_CELL_TOO_DEEP",
    "NESTED_CHILD_NON_FINITE",
]

_d = _catalog.warning("QualityWarning")

NESTED_CELL_DUPLICATE_KEY = _d(
    "nested_cell_duplicate_key",
    "A nested cell repeats an object key, so it cannot be masked.",
    since="1.30.0",
)
NESTED_CELL_NUMBER_OUT_OF_RANGE = _d(
    "nested_cell_number_out_of_range",
    "A nested rule selects a number too long to read as an integer.",
    since="1.30.0",
)
NESTED_CELL_OVERSIZED = _d(
    "nested_cell_oversized",
    "A nested cell is larger than the byte limit, so it cannot be masked.",
    since="1.30.0",
)
NESTED_CELL_TOO_DEEP = _d(
    "nested_cell_too_deep",
    "A nested cell is deeper than the nesting limit, so it cannot be masked.",
    since="1.30.0",
)
NESTED_CHILD_NON_FINITE = _d(
    "nested_child_non_finite",
    "A nested child strategy returned a value that is not a finite number.",
    since="1.30.0",
)
