"""Check-digit validators: luhn, npi, iban, vin (SP-05 / P5.INFRA.4).

Each validator is a callable with signature::

    def validate_<name>(
        outputs: dict[str, pa.Table],
        entry: dict[str, Any],
        config: dict[str, Any],
    ) -> tuple[ValidatorFinding, ...]

``outputs`` is the immutable read-only output from the pipeline. ``entry`` is
the per-validator config block (``{"name": "luhn", "columns": {"t": ["cc"]}}``).
``config`` is the full pipeline config dict (for FK validators that read the
``relationships:`` block).

All four check-digit validators delegate entirely to
``decoy_engine.checksums.validate(scheme, value)`` (SP-04 / P5.INFRA.1).
No check-digit logic is re-implemented here.

Null values in any column are skipped: a null is not a Luhn/NPI/IBAN/VIN
violation. This matches the engine's treatment of nullable FKs.

Each validator here is a fold (`ColumnFold`): it takes row spans one at a time and keeps, per
configured column, an exact failure count and the first `FINDING_INDEX_CAP` failing positions.
The ``validate_<name>`` functions stay as the registry entry points: they open the fold, feed
whole tables as one span each and finish.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pyarrow as pa

import decoy_engine.checksums as _checksums
from decoy_engine.validators._fold import (
    CappedIndices,
    FoldResult,
    finding_index_cap,
    run_whole,
)
from decoy_engine.validators._types import RowSpan, ValidatorFinding

# ---------------------------------------------------------------------------
# The per-column fold shared by the check-digit validators and `_generic.py`
# ---------------------------------------------------------------------------


class ColumnFold:
    """A row-local check over the columns named in ``entry["columns"]``.

    A subclass gives the validator name, ``failing_positions`` (the local row positions of a
    value list that fail) and ``describe`` (the finding text built from the total count). Nulls
    are the subclass's call. The fold keeps one tally per configured (table, occurrence), so a
    column listed twice gives two findings, as the whole-table call did.
    """

    name: str

    def __init__(self, entry: dict[str, Any], *, cap: int | None) -> None:
        self._columns: dict[str, list[str]] = entry.get("columns") or {}
        self._cap = cap
        self._tallies: dict[tuple[str, int], CappedIndices] = {}
        self._present: set[tuple[str, int]] = set()

    def failing_positions(self, values: list[Any]) -> Iterable[int]:
        raise NotImplementedError

    def describe(self, count: int, table: str, column: str) -> str:
        raise NotImplementedError

    def add(self, table: str, span: RowSpan) -> None:
        columns = self._columns.get(table)
        if not columns:
            return
        names = span.output.schema.names
        for occurrence, column in enumerate(columns):
            if column not in names:
                continue
            key = (table, occurrence)
            self._present.add(key)
            tally = self._tallies.setdefault(key, CappedIndices(self._cap))
            for position in self.failing_positions(span.output.column(column).to_pylist()):
                tally.add(span.offset + position)

    def table_complete(self, table: str) -> None:
        return None

    def paired_tables(self) -> frozenset[str]:
        return frozenset()

    def finish(self) -> FoldResult:
        findings: list[ValidatorFinding] = []
        checked: list[tuple[str, str | None]] = []
        for table, columns in self._columns.items():
            for occurrence, column in enumerate(columns):
                key = (table, occurrence)
                if key not in self._present:
                    continue
                checked.append((table, column))
                tally = self._tallies.get(key)
                if tally is None or tally.count == 0:
                    continue
                findings.append(
                    ValidatorFinding(
                        validator=self.name,
                        table=table,
                        column=column,
                        failing_row_indices=tally.indices(),
                        detail=self.describe(tally.count, table, column),
                        failing_row_count=tally.count,
                    )
                )
        return FoldResult(tuple(findings), tuple(checked), ())


class _CheckDigitFold(ColumnFold):
    """Check-digit validation: delegates every value to ``checksums.validate(scheme, value)``.

    Null values are skipped (they are not treated as check-digit failures).
    """

    def __init__(self, scheme: str, entry: dict[str, Any], *, cap: int | None) -> None:
        super().__init__(entry, cap=cap)
        self.name = scheme

    def failing_positions(self, values: list[Any]) -> Iterable[int]:
        for i, val in enumerate(values):
            if val is None:
                continue  # nulls are not a check-digit violation
            try:
                valid = _checksums.validate(self.name, str(val))
            except ValueError:
                valid = False
            if not valid:
                yield i

    def describe(self, count: int, table: str, column: str) -> str:
        return f"{count} row(s) in {table}.{column} failed {self.name} check-digit validation"


def check_digit_fold(scheme: str, entry: dict[str, Any], config: dict[str, Any]) -> _CheckDigitFold:
    """The fold for one check-digit scheme, capped by the config's quarantine setting."""
    return _CheckDigitFold(scheme, entry, cap=finding_index_cap(config))


def validate_luhn(
    outputs: dict[str, pa.Table],
    entry: dict[str, Any],
    config: dict[str, Any],
    *,
    sources: dict[str, pa.Table] | None = None,
) -> tuple[ValidatorFinding, ...]:
    """luhn: validates Luhn-checksum integrity per column.

    Delegates to ``checksums.validate('luhn', value)`` (SP-04 / P5.INFRA.1),
    which uses python-stdnum 2.2 ``stdnum.luhn`` (Luhn 1954, US Patent
    2,950,048). No check-digit logic is implemented here.

    Args:
        outputs: Read-only pipeline outputs.
        entry: Config block for this validator instance.
        config: Full pipeline config dict (read for the quarantine setting only).
        sources: Unused by this validator (registry contract, D2).

    Returns:
        Tuple of ValidatorFinding for each column with LUHN failures.
    """
    return run_whole(check_digit_fold("luhn", entry, config), outputs).findings


def validate_npi(
    outputs: dict[str, pa.Table],
    entry: dict[str, Any],
    config: dict[str, Any],
    *,
    sources: dict[str, pa.Table] | None = None,
) -> tuple[ValidatorFinding, ...]:
    """npi: validates US National Provider Identifier check digit per column.

    Delegates to ``checksums.validate('npi', value)`` (SP-04 / P5.INFRA.1),
    which implements the CMS NPPES NPI Check Digit Procedure (2008). No
    check-digit logic is implemented here.

    Args:
        outputs: Read-only pipeline outputs.
        entry: Config block for this validator instance.
        config: Full pipeline config dict (read for the quarantine setting only).
        sources: Unused by this validator (registry contract, D2).

    Returns:
        Tuple of ValidatorFinding for each column with NPI failures.
    """
    return run_whole(check_digit_fold("npi", entry, config), outputs).findings


def validate_iban(
    outputs: dict[str, pa.Table],
    entry: dict[str, Any],
    config: dict[str, Any],
    *,
    sources: dict[str, pa.Table] | None = None,
) -> tuple[ValidatorFinding, ...]:
    """iban: validates IBAN mod-97 check digits per column.

    Delegates to ``checksums.validate('iban', value)`` (SP-04 / P5.INFRA.1),
    which uses python-stdnum 2.2 ``stdnum.iban`` (ISO 13616 / ISO 7064
    mod-97). No check-digit logic is implemented here.

    Args:
        outputs: Read-only pipeline outputs.
        entry: Config block for this validator instance.
        config: Full pipeline config dict (read for the quarantine setting only).
        sources: Unused by this validator (registry contract, D2).

    Returns:
        Tuple of ValidatorFinding for each column with IBAN failures.
    """
    return run_whole(check_digit_fold("iban", entry, config), outputs).findings


def validate_vin(
    outputs: dict[str, pa.Table],
    entry: dict[str, Any],
    config: dict[str, Any],
    *,
    sources: dict[str, pa.Table] | None = None,
) -> tuple[ValidatorFinding, ...]:
    """vin: validates VIN ISO 3779 check character per column.

    Delegates to ``checksums.validate('vin', value)`` (SP-04 / P5.INFRA.1),
    which implements NHTSA 49 CFR Part 565 Appendix B. No check-digit logic
    is implemented here.

    Args:
        outputs: Read-only pipeline outputs.
        entry: Config block for this validator instance.
        config: Full pipeline config dict (read for the quarantine setting only).
        sources: Unused by this validator (registry contract, D2).

    Returns:
        Tuple of ValidatorFinding for each column with VIN failures.
    """
    return run_whole(check_digit_fold("vin", entry, config), outputs).findings
