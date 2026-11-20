"""
Date-format helpers shared by the date strategies.

The date shift itself runs in ``execution/_strategies/_date_shift.py``: a keyed offset derived
from the admitted mask secret. The V1 class that lived here, with an MD5 fallback offset that
could be reversed by search, was deleted (roadmap row 24zb). What stays is format detection
(``_detect_format``) and the common-format list (``_COMMON_FORMATS``), imported by
``bucket_perturb`` and ``text_mask`` (date_shift no longer detects: its format is required), and the
one shift-window resolver
(``shift_window``, ``shift_window_problem``) that every date_shift route reads its bounds from.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import pandas as pd

from decoy_engine import reasons
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


def _detect_format(series: pd.Series) -> str | None:
    """Pick the date format that parses every value in the sample.

    F9 fix: bumped the sample from 20 -> 200 rows. 20 was demonstrably too
    small for mixed-format columns coming out of legacy ETL pipelines: if
    the first 20 happen to share one format but the rest are different,
    the wrong format is locked in and downstream rows silently pass
    through unshifted.

    When more than one format parses the entire sample, we emit a warning
    rather than tie-breaking silently. A wrong winner mis-parses some
    rows, which the handler reports as row errors, not a crash.
    """
    sample = series.dropna().astype(str).head(min(200, len(series)))
    candidates: list[str] = []
    for fmt in _COMMON_FORMATS:
        ok = True
        for v in sample:
            try:
                datetime.strptime(v.strip(), fmt)
            except ValueError:
                ok = False
                break
        if ok:
            candidates.append(fmt)
    if not candidates:
        return None
    if len(candidates) > 1:
        import warnings as _warnings

        _warnings.warn(
            "date_shift._detect_format: column matches multiple formats "
            f"{candidates!r}; using the first ({candidates[0]!r}). Configure "
            "date_format explicitly to remove ambiguity.",
            stacklevel=2,
        )
    return candidates[0]
