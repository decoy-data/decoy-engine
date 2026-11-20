"""`np.histogram` that falls back to the most bins numpy accepts for the range."""

from __future__ import annotations

from typing import Any

import numpy as np

# numpy refuses a bin count for a range that is too narrow (1e15 plus noise) or too wide (+-1e308).
_REFUSED = (ValueError, IndexError)


def histogram_for_range(
    values: np.ndarray[Any, np.dtype[np.float64]], bins: int, lo: float, hi: float
) -> tuple[Any, Any]:
    """Counts and edges over `[lo, hi]`; fewer bins than asked when numpy refuses `bins`.

    A snapshot must not crash on such a column. No error text is kept, so no cell can leak.
    """
    with np.errstate(all="ignore"):
        try:
            return np.histogram(values, bins=bins, range=(lo, hi))
        except _REFUSED:
            pass
        good, bad = 1, bins  # `bad` is refused; bisect for the largest accepted count below it
        while bad - good > 1:
            mid = (good + bad) // 2
            try:
                np.histogram(values, bins=mid, range=(lo, hi))
                good = mid
            except _REFUSED:
                bad = mid
        try:
            return np.histogram(values, bins=good, range=(lo, hi))
        except _REFUSED:
            return np.array([values.size]), np.array([lo, hi])
