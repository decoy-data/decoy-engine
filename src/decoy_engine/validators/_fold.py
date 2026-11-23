"""Fold plumbing shared by the validators: the fold shape, bounded state and the whole-table feed.

A validator is a fold: it takes row spans one at a time and gives its findings at the end, so a
whole table (one span) and a streamed table (many spans) give one verdict. The shape follows the
combine functions of Apache Beam (`add_input` then `extract_output`); merging is not needed
because every route delivers a table's rows in order on one thread.

``CappedIndices`` keeps an exact count and the smallest row positions up to a cap, in any arrival
order, so a report does not depend on how rows were chunked or which table came first.
``KeyStateBudget`` is the one place a keyed fold reserves memory before it keeps a key, a
pending child or a parent row, and the one place that refuses with a coded error.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from decoy_engine import reasons
from decoy_engine.errors import ValidatorStateError
from decoy_engine.validators._types import FINDING_INDEX_CAP, RowSpan, SkippedColumn

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    import pyarrow as pa

    from decoy_engine.validators._types import ValidatorFinding


@dataclass(frozen=True)
class FoldResult:
    """What one fold reports at the end: its findings, what it checked and what it skipped."""

    findings: tuple[ValidatorFinding, ...]
    checked: tuple[tuple[str, str | None], ...] = ()
    skipped: tuple[SkippedColumn, ...] = ()


class Fold(Protocol):
    """One validator entry over a run. Spans of one table arrive in row order."""

    def add(self, table: str, span: RowSpan) -> None: ...

    def table_complete(self, table: str) -> None:
        """The table has delivered every row; a keyed fold may now resolve what waited on it."""

    def paired_tables(self) -> frozenset[str]:
        """Tables whose spans must carry a source (empty for a fold that reads none)."""

    def finish(self) -> FoldResult: ...


def finding_index_cap(config: Mapping[str, Any]) -> int | None:
    """The per-finding index cap for this config: lifted under quarantine ``validation_fail``.

    Quarantine removes exactly the listed rows, so a capped list would leave failing rows in the
    output. The cap follows the config, never the route.
    """
    quarantine = config.get("quarantine") or {}
    if quarantine.get("enabled") and "validation_fail" in (quarantine.get("triggers") or []):
        return None
    return FINDING_INDEX_CAP


def run_whole(
    fold: Fold,
    outputs: Mapping[str, pa.Table],
    sources: Mapping[str, pa.Table] | None = None,
) -> FoldResult:
    """Feed every output table as one span and finish: the old whole-table call shape."""
    for table, output in outputs.items():
        fold.add(table, RowSpan(0, output, (sources or {}).get(table)))
        fold.table_complete(table)
    return fold.finish()


class CappedIndices:
    """An exact failure count plus the lowest ``cap`` failing positions (all when ``cap`` is None)."""

    __slots__ = ("_all", "_cap", "_heap", "count")

    def __init__(self, cap: int | None) -> None:
        self._cap = cap
        self._all: list[int] = []
        self._heap: list[int] = []  # negated, so the largest kept position is at the root
        self.count = 0

    def add(self, index: int) -> None:
        """Record one failing position."""
        self.count += 1
        self._offer(index)

    def add_group(self, count: int, indices: Iterable[int]) -> None:
        """Record ``count`` failures of which ``indices`` are the lowest positions kept."""
        self.count += count
        for index in indices:
            self._offer(index)

    def _offer(self, index: int) -> None:
        if self._cap is None:
            self._all.append(index)
        elif len(self._heap) < self._cap:
            heapq.heappush(self._heap, -index)
        elif index < -self._heap[0]:
            heapq.heapreplace(self._heap, -index)

    def indices(self) -> tuple[int, ...]:
        """The kept positions in row order."""
        if self._cap is None:
            return tuple(sorted(self._all))
        return tuple(sorted(-v for v in self._heap))


class KeyStateBudget:
    """Byte ceiling for the key maps, pending children and parent rows of the keyed folds."""

    __slots__ = ("_limit", "_used")

    def __init__(self, limit: int | None) -> None:
        self._limit = limit
        self._used = 0

    def reserve(self, nbytes: int, *, table: str, column: str | None) -> None:
        """Take ``nbytes`` or refuse. The refusal names the table and column, never a value."""
        if self._limit is not None and self._used + nbytes > self._limit:
            where = table if column is None else f"{table}.{column}"
            raise ValidatorStateError(
                code=reasons.runtime.VALIDATOR_KEY_STATE_OVER_BUDGET,
                message=(
                    f"the key state for {where} would exceed the validation budget; set "
                    "execution_mode to full_frame or give the run more memory."
                ),
            )
        self._used += nbytes

    def release(self, nbytes: int) -> None:
        self._used = max(0, self._used - nbytes)

    @property
    def used(self) -> int:
        return self._used
