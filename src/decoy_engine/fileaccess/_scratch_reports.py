"""Frozen, value-free reports the scratch arena returns or attaches to an error.

Pattern: the typed reports of the revision-1 scratch branch (`scratch/_reports.py`), trimmed to
the fields F25 V1 freezes. Every field is a closed code, an enum or a count, so `str()` and
`repr()` can carry no path, table, column or cell value; a value that is not a known code is
refused at construction, never stored.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Literal, get_args

Dimension = Literal["bytes", "unknown"]
Route = Literal["engine.scratch", "out_of_core", "declared_staging", "isolated", "snapshot"]


class Disposition(str, enum.Enum):
    """What happened to an arena's bytes. A failed removal is `RETAINED`, never a success."""

    REMOVED = "removed"
    RETAINED = "retained"


def _check(disposition: object, *counts: int | None) -> None:
    """Refuse anything but a Disposition and non-negative int counts (bool is a caller bug)."""
    if not isinstance(disposition, Disposition) or any(
        c is not None and (type(c) is not int or c < 0) for c in counts
    ):
        raise ValueError("a scratch report takes only a Disposition and non-negative counts")


@dataclass(frozen=True, slots=True, kw_only=True)
class QuotaReport:
    """Why a scratch write stopped: out of budget (`bytes`) or an errno-less failure (`unknown`,
    which names no limit, named limit L3: its cap and observation are None)."""

    route: Route = "engine.scratch"
    dimension: Dimension
    effective_bytes_cap: int | None = None
    observed_bytes: int | None = None
    disposition: Disposition = Disposition.RETAINED

    def __post_init__(self) -> None:
        if self.route not in get_args(Route) or self.dimension not in get_args(Dimension):
            raise ValueError("a quota report takes only its closed route and dimension codes")
        _check(self.disposition, self.effective_bytes_cap, self.observed_bytes)


@dataclass(frozen=True, slots=True, kw_only=True)
class CleanupReport:
    """The outcome of one `reclaim()`. Counts are None when a retained arena was not measured."""

    disposition: Disposition
    retained_bytes: int | None = 0
    retained_inodes: int | None = 0

    def __post_init__(self) -> None:
        _check(self.disposition, self.retained_bytes, self.retained_inodes)


class ReclaimOutcome(str, enum.Enum):
    """What one reclaim pass did with one exact-named entry. Closed: nothing maps to `REMOVED`
    except a removal that happened, and every other code leaves the entry as it was."""

    REMOVED = "removed"
    ELIGIBLE = "eligible"
    LIVE = "live"
    YOUNG = "young"
    FOREIGN = "foreign"
    UNPROVEN = "unproven"
    KEPT = "kept"
    LOCK_UNAVAILABLE = "lock_unavailable"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReclaimReport:
    """Counts of one `reclaim_stages` or `sweep_scratch` pass: one per outcome, plus
    `scope_unavailable` when the scope itself could not be opened or listed. No path, name,
    token, errno or message is held, so `str()` and `repr()` are value-free (F26 G5)."""

    removed: int = 0
    eligible: int = 0
    live: int = 0
    young: int = 0
    foreign: int = 0
    unproven: int = 0
    kept: int = 0
    lock_unavailable: int = 0
    failed: int = 0
    scope_unavailable: int = 0

    def __post_init__(self) -> None:
        counts = [getattr(self, o.value) for o in ReclaimOutcome] + [self.scope_unavailable]
        if any(type(c) is not int or c < 0 for c in counts):
            raise ValueError("a reclaim report takes only non-negative int counts")

    def count(self, outcome: ReclaimOutcome) -> int:
        return int(getattr(self, ReclaimOutcome(outcome).value))


__all__ = ["CleanupReport", "Disposition", "QuotaReport", "ReclaimOutcome", "ReclaimReport"]
