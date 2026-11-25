"""
Date-format helpers shared by the date strategies.

The date shift itself runs in ``execution/_strategies/_date_shift.py``: a keyed offset derived
from the admitted mask secret. The V1 class that lived here, with an MD5 fallback offset that
could be reversed by search, was deleted (roadmap row 24zb). What stays is the common-format list
(``_COMMON_FORMATS``), imported by ``text_mask`` for date spans in free text (no column strategy
detects a format: it is required), and the one shift-window resolver
(``shift_window``, ``shift_window_problem``) that every date_shift route reads its bounds from.

``shift_typed_days`` is the one arithmetic that adds days to a typed date: the native route
calls it on the resident Arrow array and the oracle on an array built from its usable cells, so
the two routes agree by construction (DATE-SHIFT-TYPED).
"""

from collections.abc import Mapping
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from decoy_engine import reasons

# The bounds live with the other temporal bounds, below `profile/` in the import tiers, so the
# profile read and this kernel share them; the names stay importable from here.
from decoy_engine._arrow_types import DATE32_MAX_DAY as DATE32_MAX_DAY
from decoy_engine._arrow_types import DATE32_MIN_DAY as DATE32_MIN_DAY
from decoy_engine._arrow_types import date32_in_range as date32_in_range
from decoy_engine.plan._errors import PlanCompileError

# The handler's defaults when a config names no bound.
DEFAULT_MIN_DAYS = -365
DEFAULT_MAX_DAYS = 365

# `pd.Timedelta.max.days`. A bound outside +/- this can never produce a valid shift in pandas, and
# it keeps `offset + min_days` far from int64 overflow on the native side.
MAX_ABS_SHIFT_DAYS = 106_751

# The config keys that set a window. The native admission narrows the types of the first two
# without spelling them, so the reader sentry sees one file that names them.
WINDOW_BOUND_KEYS = ("min_days", "max_days")

# problem word -> (config key it concerns, fixed message). Messages carry no config value.
WINDOW_PROBLEMS: dict[str, tuple[str, str]] = {
    "jitter_days_with_bounds": (
        "jitter_days",
        "jitter_days cannot be combined with min_days or max_days. Use jitter_days alone for "
        "a window of [-N, N], or min_days and max_days for any other window.",
    ),
    "jitter_days_invalid": ("jitter_days", "jitter_days must be a non-negative integer."),
    "jitter_days_out_of_range": (
        "jitter_days",
        f"jitter_days must be at most {MAX_ABS_SHIFT_DAYS} days.",
    ),
    "min_days_invalid": ("min_days", "min_days must be a whole number of days."),
    "max_days_invalid": ("max_days", "max_days must be a whole number of days."),
    "min_days_out_of_range": (
        "min_days",
        f"min_days must be between -{MAX_ABS_SHIFT_DAYS} and {MAX_ABS_SHIFT_DAYS} days.",
    ),
    "max_days_out_of_range": (
        "max_days",
        f"max_days must be between -{MAX_ABS_SHIFT_DAYS} and {MAX_ABS_SHIFT_DAYS} days.",
    ),
}


class DateShiftWindowError(PlanCompileError, ValueError):
    """`shift_window` refused a window. A `ValueError` too, as the bare `int()` failure it
    replaces was, so callers that catch that keep working."""


def order_window(low: int, high: int) -> tuple[int, int]:
    """The bounds low-first: a reversed window means the same window."""
    return (high, low) if low > high else (low, high)


def _resolve(cfg: Mapping[str, Any]) -> tuple[int, int] | str:
    """The window as `(low, high)`, or the problem word. Both public functions read this."""
    # An explicit null jitter_days reads as unset: today's handler ignores the key.
    if cfg.get("jitter_days") is not None:
        if "min_days" in cfg or "max_days" in cfg:
            return "jitter_days_with_bounds"
        jitter = cfg["jitter_days"]
        if isinstance(jitter, bool) or not isinstance(jitter, int) or jitter < 0:
            return "jitter_days_invalid"
        if jitter > MAX_ABS_SHIFT_DAYS:
            return "jitter_days_out_of_range"
        return (-jitter, jitter)
    bounds: list[int] = []
    for key, default in (("min_days", DEFAULT_MIN_DAYS), ("max_days", DEFAULT_MAX_DAYS)):
        try:
            # The handler's own coercion: strings, floats and numpy integers keep their window.
            bound = int(cfg.get(key, default))
        except (TypeError, ValueError, OverflowError):
            return f"{key}_invalid"
        if abs(bound) > MAX_ABS_SHIFT_DAYS:
            return f"{key}_out_of_range"
        bounds.append(bound)
    return order_window(bounds[0], bounds[1])


def shift_window_problem(cfg: Mapping[str, Any]) -> str | None:
    """A fixed problem word (a key of `WINDOW_PROBLEMS`) when the window is unusable, else None."""
    resolved = _resolve(cfg)
    return resolved if isinstance(resolved, str) else None


def shift_window(cfg: Mapping[str, Any]) -> tuple[int, int]:
    """The inclusive `(low, high)` day window of a date_shift config.

    `jitter_days: N` is `(-N, N)`. Otherwise `min_days` and `max_days` (defaults -365 and 365),
    swapped when reversed. A bad config raises the registered plan error instead of falling
    through to another key.
    """
    resolved = _resolve(cfg)
    if isinstance(resolved, str):
        key, message = WINDOW_PROBLEMS[resolved]
        raise DateShiftWindowError(
            code=reasons.plan.DATE_SHIFT_WINDOW_INVALID,
            path=f"provider_config.{key}",
            message=message,
        )
    return resolved


_COMMON_FORMATS = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%m-%d-%Y",
    "%d-%m-%Y",
    "%Y%m%d",
    "%m/%d/%y",
    "%d/%m/%y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
]


def date32_days(array: pa.Array) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    """`(days, valid)` of a `date32` array: the int64 day numbers (0 in a null slot) and the
    non-null mask. Reading the physical integer never converts a value to Python."""
    if array.type != pa.date32():
        raise TypeError(f"expected a date32 array, got {array.type}")
    days = pc.fill_null(array.cast(pa.int32()), 0).to_numpy(zero_copy_only=False)
    valid = array.is_valid().to_numpy(zero_copy_only=False)
    return days.astype(np.int64), valid


def shift_typed_days(
    array: pa.Array, offsets: np.ndarray[Any, Any]
) -> tuple[pa.Array, np.ndarray[Any, Any]]:
    """Add `offsets[i]` calendar days to every usable row of a `date32` array.

    Returns `(shifted, failed)`. `shifted` keeps the source type; a null stays null. `failed`
    marks the non-null rows whose source or shifted day is outside years 1 to 9999: those keep
    their source value and the caller records a `format_error`. A failed row's offset is ignored,
    so a caller that derives no offset for it may pass 0.
    """
    days, valid = date32_days(array)
    if len(offsets) != len(days):
        raise ValueError(f"{len(offsets)} offsets for {len(days)} rows")
    shifted = days + np.asarray(offsets, dtype=np.int64)
    ok = valid & date32_in_range(days) & date32_in_range(shifted)
    failed = valid & ~ok
    out_days = np.where(ok, shifted, days).astype(np.int32)
    out = pa.array(out_days, type=pa.int32(), mask=~valid).cast(pa.date32())
    return out, failed
