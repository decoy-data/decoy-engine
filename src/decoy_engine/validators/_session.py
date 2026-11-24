"""The validation session: one run's validators, fed span by span.

A session opens every configured ``validators:`` entry as a fold, takes the published rows of
each table as spans, and builds the one ``ValidationReport`` at ``finish``. It owns the
bookkeeping the folds share: the row offset of each table, the source rows that pair with a
published span, the completion of a table, the key-state ceiling and the time spent.

Three named entry points feed it, over one core, so a caller never passes a mode flag:

* ``observe`` takes one complete resident table.
* ``observe_published`` takes the next batch of a table that is being written.
* ``observe_pair`` takes a batch together with its source batch, for a route that already holds
  the raw rows (the out-of-core join).

Established methodology: Apache Beam combine functions (an accumulator fed one element group at
a time, one output at the end) and Great Expectations results (an exact `unexpected_count`
beside a capped sample of indices).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from decoy_engine import reasons
from decoy_engine.errors import ValidatorStateError
from decoy_engine.validators._fold import KeyStateBudget, assemble_report, finding_index_cap
from decoy_engine.validators._registry import build_fold
from decoy_engine.validators._types import (
    RowSpan,
    ValidationReport,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from decoy_engine.validators._fold import Fold


_ACTIVE: ContextVar[ValidationSession | None] = ContextVar("decoy_validation_session", default=None)


def active_validation_session() -> ValidationSession | None:
    """The session bound to this run, or None outside ``bind_validation_session``."""
    return _ACTIVE.get()


@contextmanager
def bind_validation_session(
    config: dict[str, Any], *, key_state_budget: Callable[[], int | None]
) -> Iterator[ValidationSession | None]:
    """Bind one session for the run, or bind nothing when the config has no validators.

    ``key_state_budget`` resolves the keyed folds' ceiling; it runs only when a session opens.
    Opening validates every entry before any source is read, so a bad pattern or an unknown
    validator name fails at the start of the run.
    """
    if not config.get("validators"):
        yield None
        return
    session = ValidationSession(config, key_state_budget_bytes=key_state_budget())
    token = _ACTIVE.set(session)
    try:
        yield session
    finally:
        _ACTIVE.reset(token)


def run_resident_validation(
    outputs: Mapping[str, pa.Table], config: dict[str, Any], sources: Mapping[str, Any]
) -> ValidationReport | None:
    """Validate resident outputs and return the report, or None when no validators are configured.

    With a session bound to the run the outputs go through it, so the run's one report covers
    them; without one this is the whole-table ``validate`` call.
    """
    if not config.get("validators"):
        return None
    session = active_validation_session()
    if session is None:
        from decoy_engine.validators import _registry

        return _registry.validate(dict(outputs), config, sources=dict(sources))
    session.observe_unobserved(outputs, sources)
    return session.finish()


class ValidationSession:
    """One run's validators. Open it, feed it spans, finish it once.

    Args:
        config: The pipeline config dict; the ``validators:`` list and the quarantine setting
            are read from it.
        sources: Read-only pre-mask source tables by name. A table that arrives through
            ``observe_published`` is paired with the rows of its source at the same positions
            (a zero-copy slice).
        key_state_budget_bytes: Ceiling for the state the keyed folds retain, or None for no
            ceiling (a resident run already holds the tables).

    Raises:
        ValueError: A validator entry is malformed, unknown or has bad parameters.
    """

    def __init__(
        self,
        config: dict[str, Any],
        *,
        sources: dict[str, pa.Table] | None = None,
        key_state_budget_bytes: int | None = None,
    ) -> None:
        self._sources = sources
        cap = finding_index_cap(config)
        budget = KeyStateBudget(key_state_budget_bytes)
        entries: list[Any] = config.get("validators") or []
        self._names: list[str] = []
        self._folds: list[Fold] = []
        for entry in entries:
            name, fold = build_fold(entry, config, cap=cap, budget=budget, sources=sources)
            self._names.append(name)
            self._folds.append(fold)
        self._rows: dict[str, int] = {}
        self._complete: set[str] = set()
        self._explicit_source_rows: dict[str, int] = {}
        self._elapsed = 0.0
        self._report: ValidationReport | None = None

    def observe(self, table: str, output: pa.Table, source: pa.Table | None = None) -> None:
        """Feed one complete resident table, then mark it complete.

        The first complete observer of a table owns its folds. A later observer of the same
        table adds nothing, so a table reached by two completion steps is never counted twice.
        """
        if table in self._complete:
            return
        if source is not None:
            self._explicit_source_rows[table] = source.num_rows
        self._feed(
            table, output, self._source_rows(table, source, self._rows.get(table, 0), output)
        )
        self._complete_table(table)

    def observe_published(self, table: str, batch: pa.RecordBatch | pa.Table) -> None:
        """Feed the next batch of a table being written, in row order."""
        offset = self._rows.get(table, 0)
        self._feed(table, batch, self._source_rows(table, None, offset, batch))

    def observe_pair(
        self, table: str, source: pa.RecordBatch | pa.Table, output: pa.RecordBatch | pa.Table
    ) -> None:
        """Feed a published batch with the raw batch it came from."""
        self._feed(table, output, source)

    def observe_unobserved(
        self, outputs: Mapping[str, pa.Table], sources: Mapping[str, pa.Table]
    ) -> bool:
        """Feed every resident table no observer has completed. True when it fed any."""
        fed = False
        for table, output in outputs.items():
            if table not in self._complete:
                source = sources.get(table)
                self.observe(table, output, source if isinstance(source, pa.Table) else None)
                fed = True
        return fed

    def unobserved_tables(self, tables: Iterable[str]) -> list[str]:
        """The names in ``tables`` no observer has completed."""
        return [table for table in tables if table not in self._complete]

    def paired_tables(self) -> frozenset[str]:
        """The tables a check reads a source for, so a caller loads only those sources."""
        return frozenset().union(*(fold.paired_tables() for fold in self._folds))

    def table_complete(self, table: str) -> None:
        """The table has delivered every row; keyed folds may resolve what waited on it."""
        self._complete_table(table)

    def _source_rows(
        self,
        table: str,
        explicit: pa.Table | None,
        offset: int,
        output: pa.RecordBatch | pa.Table,
    ) -> pa.RecordBatch | pa.Table | None:
        if explicit is not None:
            return explicit
        held = (self._sources or {}).get(table)
        if not isinstance(held, pa.Table):
            return None
        return held.slice(offset, output.num_rows)

    def _feed(
        self,
        table: str,
        output: pa.RecordBatch | pa.Table,
        source: pa.RecordBatch | pa.Table | None,
    ) -> None:
        if self._report is not None:
            raise ValueError("the validation session is finished; open a new one")
        started = time.perf_counter()
        span = RowSpan(self._rows.get(table, 0), output, source)
        for fold in self._folds:
            fold.add(table, span)
        self._rows[table] = span.offset + output.num_rows
        self._elapsed += time.perf_counter() - started

    def _complete_table(self, table: str) -> None:
        if table in self._complete:
            return
        self._complete.add(table)
        started = time.perf_counter()
        for fold in self._folds:
            fold.table_complete(table)
        self._elapsed += time.perf_counter() - started

    def finish(self) -> ValidationReport:
        """Complete every table, check source pairing and build the report. Idempotent."""
        if self._report is not None:
            return self._report
        started = time.perf_counter()
        for table in self._rows:
            self._complete_table(table)
        self._check_pairing()
        outcomes = [fold.finish() for fold in self._folds]
        self._elapsed += time.perf_counter() - started
        self._report = assemble_report(self._names, outcomes, self._elapsed * 1000.0)
        return self._report

    def _check_pairing(self) -> None:
        """A paired check needs as many source rows as published rows, table by table."""
        held: dict[str, int] = {
            name: tbl.num_rows
            for name, tbl in (self._sources or {}).items()
            if isinstance(tbl, pa.Table)
        }
        held.update(self._explicit_source_rows)
        for fold in self._folds:
            for table in fold.paired_tables():
                source_rows = held.get(table)
                if table in self._rows and source_rows is not None:
                    if source_rows != self._rows[table]:
                        raise ValidatorStateError(
                            code=reasons.runtime.VALIDATOR_SOURCE_PAIRING_MISMATCH,
                            message=(
                                f"the source rows for table {table!r} do not match the "
                                "published rows."
                            ),
                        )
