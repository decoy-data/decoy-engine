"""Column-name hint patterns for the built-in detectors and the per-scan hint extras.

Moved verbatim from ``detection/detectors.py``, which re-exports every name here.
"""

from __future__ import annotations

import re

# ── name-hint patterns (case-insensitive, matched against the column name) ──
#
# Detection sprint (V1): expanded with US English abbreviation forms drawn
# from real-world health, fintech, and payroll headers. Cross-cultural variants
# (Spanish / French / German / etc.) are V1.5; one locale keeps false positives predictable.


def _hint(terms: list[str]) -> re.Pattern[str]:
    """Build a case-insensitive name-hint regex from a list of token strings.

    Each term matches when it appears as a standalone token in the column
    name, where tokens are separated by `_`, `-`, `.`, or string boundaries.
    Order of alternation matters only for performance, not correctness.
    """
    body = "|".join(re.escape(t) for t in terms)
    return re.compile(rf"(?i)^(.*[._-])?({body})([._-].*)?\Z")


# The 26 built-in detectors' column-name hint patterns live in YAML under
# decoy_engine.detection.name_hints.v1/; the loader returns a flat dict
# {detector_id: [term, ...]} and we apply `_hint(terms)` here to build the actual
# re.Pattern objects. Keeping regex construction in this module means there's exactly
# one implementation; the loader is a pure data layer.
#
# Behavior matches the pre-extraction hard-coded dict bit-for-bit; this is verified by
# tests/snapshots/test_name_hints_baseline.py. Any YAML edit that changes coverage breaks
# the snapshot and forces an explicit re-baseline commit.
#
# See decoy_engine.detection.name_hints.v1/README.md for the YAML format
# + contribution conventions.
from decoy_engine.detection.name_hints.loader import load_name_hint_terms

_NAME_HINTS: dict[str, re.Pattern[str]] = {
    det_id: _hint(terms) for det_id, terms in load_name_hint_terms().items()
}


# Per-scan additive name-hint extras. The platform reads its
# detector_overrides table at scan start and stashes
# {detector_id: re.Pattern} here via set_name_hint_extras(); the
# detect_* functions consult this via _hits_name_hint().
#
# Additive semantics: a column name matches if EITHER the shipped
# pattern OR the per-scan extras pattern matches. Customers cannot
# disable shipped patterns through this surface (that's a "full
# override" mode deferred to a later sprint if real demand appears).
#
# ContextVar (not module-global) so concurrent scans on the same
# process don't cross-contaminate -- each scan's profile_columns() call
# sets its own extras for the duration of that call.
from contextlib import contextmanager
from contextvars import ContextVar

_NAME_HINT_EXTRAS: ContextVar[dict[str, re.Pattern[str]] | None] = ContextVar(
    "_NAME_HINT_EXTRAS",
    default=None,
)


@contextmanager
def name_hint_extras(extras: dict[str, list[str]] | None):
    """Context manager: install per-scan name-hint extras.

    Pass a dict mapping detector_id to a list of additional
    column-name term strings. The terms are compiled with the same
    _hint() regex helper used for the shipped library. Behavior is
    additive: shipped patterns still apply unchanged; extras add
    coverage on top.

    Yields and restores the ContextVar so the caller doesn't have
    to manage the token. Pass None to skip installation (no-op).
    """
    if not extras:
        yield
        return
    compiled = {
        det_id: _hint(list(terms))
        for det_id, terms in extras.items()
        if terms  # skip empty lists silently
    }
    token = _NAME_HINT_EXTRAS.set(compiled if compiled else None)
    try:
        yield
    finally:
        _NAME_HINT_EXTRAS.reset(token)


def _hits_name_hint(detector_id: str, col_name: str) -> bool:
    """True if col_name matches the shipped pattern OR a per-scan extra.

    Checked in this order:
      1. Shipped pattern from the YAML library (_NAME_HINTS).
      2. Per-scan extras installed by name_hint_extras() context.
    Either match returns True; matching is additive.
    """
    target = col_name or ""
    pat = _NAME_HINTS.get(detector_id)
    if pat and pat.fullmatch(target):
        return True
    extras = _NAME_HINT_EXTRAS.get()
    if extras:
        extra_pat = extras.get(detector_id)
        if extra_pat and extra_pat.fullmatch(target):
            return True
    return False


def hits_name_hint(detector_id: str, col_name: str) -> bool:
    """Public accessor used by the profiler to build a column's detection trail.

    Returns True when the column name structurally hints at the detector's
    target type (e.g. column "ssn_id" hints at the SSN detector). The
    threshold-relaxation logic itself stays internal to `_evaluate`.
    """
    return _hits_name_hint(detector_id, col_name)
