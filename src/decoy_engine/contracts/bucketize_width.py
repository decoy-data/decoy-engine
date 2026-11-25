"""The one rule for a bucketize column's effective width.

The handler, the plan compile check and the column-shape rule all call ``resolve_bucketize_width``;
none of them reads ``preset`` or ``width`` itself (``tests/sentry/test_bucketize_width_contract.py``
pins the callers). A known preset gives its width and ``width`` is ignored. This module imports
nothing from the engine.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "BUCKETIZE_PRESETS",
    "EXACT_INT_BOUND",
    "MAX_EXACT_DECIMAL_WIDTH",
    "resolve_bucketize_width",
    "unresolvable_width_field",
]

BUCKETIZE_PRESETS: Mapping[str, int] = {
    "by_year": 1,
    "by_2_years": 2,
    "by_5_years": 5,
    "by_decade": 10,
    "by_century": 100,
    "by_thousand": 1_000,
    "by_ten_thousand": 10_000,
}

# With a decimal of at most 15 digits, a width up to 10**15 keeps the bucket bounds and midpoint
# below 2 * 10**15, inside int64 and below 2**53.
MAX_EXACT_DECIMAL_WIDTH = 10**15

# float64 represents every integer up to 2**53 exactly; beyond it consecutive integers collapse.
# One limit for the bucketize handler and kernel, the top_code handler and the top_code compile
# check: a cap or floor at or past it, or a bucketed value at or past it, cannot be handled exactly.
EXACT_INT_BOUND: int = 2**53


def resolve_bucketize_width(provider_config: Mapping[str, Any]) -> int | float | None:
    """The effective bucket width, or None when the config names none.

    A known ``preset`` gives its width. An unknown ``preset`` gives None. With no ``preset``, a
    positive, non-boolean number is the width; anything else gives None.
    """
    preset = provider_config.get("preset")
    if preset is not None:
        return BUCKETIZE_PRESETS.get(preset) if isinstance(preset, str) else None
    raw = provider_config.get("width")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return raw if raw > 0 else None


def unresolvable_width_field(provider_config: Mapping[str, Any]) -> str | None:
    """``"preset"`` or ``"width"``, the field that leaves the width unresolved; None when it resolves."""
    if resolve_bucketize_width(provider_config) is not None:
        return None
    return "preset" if provider_config.get("preset") is not None else "width"
