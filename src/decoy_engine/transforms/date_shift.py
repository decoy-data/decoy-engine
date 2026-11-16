"""
Date-format helpers shared by the date strategies.

The date shift itself runs in ``execution/_strategies/_date_shift.py``: a keyed offset derived
from the admitted mask secret. The V1 class that lived here, with an MD5 fallback offset that
could be reversed by search, was deleted (roadmap row 24zb). What stays is format detection
(``_detect_format``) and the common-format list (``_COMMON_FORMATS``), imported by the date_shift
handler, ``bucket_perturb`` and ``text_mask``.
"""

from datetime import datetime

import pandas as pd

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
