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
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from decoy_engine import reasons
from decoy_engine.errors import ValidatorStateError
from decoy_engine.validators._fold import KeyStateBudget, finding_index_cap
from decoy_engine.validators._registry import build_fold
from decoy_engine.validators._types import (
    RowSpan,
    ValidationReport,
    ValidatorFinding,
    ValidatorResult,
    result_status,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from decoy_engine.validators._fold import Fold


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
        self._elapsed = 0.0
        self._report: ValidationReport | None = None

    def observe(self, table: str, output: pa.Table, source: pa.Table | None = None) -> None:
        """Feed one complete resident table, then mark it complete."""
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
        findings: list[ValidatorFinding] = []
        results: list[ValidatorResult] = []
        for index, (name, fold) in enumerate(zip(self._names, self._folds, strict=True)):
            outcome = fold.finish()
            findings.extend(outcome.findings)
            failing = sum(f.failing_row_count for f in outcome.findings)
            results.append(
                ValidatorResult(
                    validator=name,
                    entry_index=index,
                    status=result_status(outcome.findings, outcome.checked, outcome.skipped),
                    checked=outcome.checked,
                    skipped=outcome.skipped,
                    failing_row_count=failing,
                )
            )
        self._elapsed += time.perf_counter() - started
        self._report = ValidationReport(
            passed=not findings,
            validators_run=tuple(dict.fromkeys(self._names)),
            findings=tuple(findings),
            elapsed_ms=self._elapsed * 1000.0,
            results=tuple(results),
        )
        return self._report

    def _check_pairing(self) -> None:
        """A paired check needs as many source rows as published rows, table by table."""
        held: Mapping[str, Any] = self._sources or {}
        for fold in self._folds:
            for table in fold.paired_tables():
                source = held.get(table)
                if table in self._rows and isinstance(source, pa.Table):
                    if source.num_rows != self._rows[table]:
                        raise ValidatorStateError(
                            code=reasons.runtime.VALIDATOR_SOURCE_PAIRING_MISMATCH,
                            message=(
                                f"the source rows for table {table!r} do not match the "
                                "published rows."
                            ),
                        )
