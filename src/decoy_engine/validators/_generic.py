"""Generic utility validators: regex_match, column_in_set (Sprint 2 honesty
pack, S3 / p5-j-validators-extended).

Pattern: Great Expectations `expect_column_values_to_match_regex` and
`expect_column_values_to_be_in_set` (great-expectations/great_expectations,
Apache-2.0). Both validators follow the `_catalog.py` per-column shape: read
outputs from `entry["columns"]`, skip nulls, one `ValidatorFinding` per
column with at least one failing row.

Trust boundary (trap T8): `pattern` and `allowed_values` are operator-supplied
pipeline config, the same trust surface as the rest of the YAML. No untrusted-
input regex hardening (e.g. ReDoS sandboxing) is in scope; a malicious config
author already controls the whole pipeline.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

import pyarrow as pa

from decoy_engine.validators._catalog import ColumnFold
from decoy_engine.validators._fold import finding_index_cap, run_whole
from decoy_engine.validators._types import ValidatorFinding


class RegexMatchFold(ColumnFold):
    """regex_match: every non-null value matches ``params.pattern`` whole-cell.

    Match rule is `re.fullmatch` on `str(value)`; an operator wanting substring semantics writes
    `.*pattern.*`. Nulls are skipped (a null is not a pattern violation).

    Raises:
        ValueError: `params.pattern` missing, or fails to compile (at construction, before any
            row is read).
    """

    name = "regex_match"

    def __init__(self, entry: dict[str, Any], *, cap: int | None) -> None:
        super().__init__(entry, cap=cap)
        params: dict[str, Any] = entry.get("params") or {}
        pattern_raw = params.get("pattern")
        if not pattern_raw or not isinstance(pattern_raw, str):
            raise ValueError(
                "regex_match validator requires params.pattern (a non-empty regex string)."
            )
        try:
            self._compiled = re.compile(pattern_raw)
        except re.error as exc:
            raise ValueError("regex_match validator: params.pattern is not a valid regex.") from exc
        self._pattern = pattern_raw

    def failing_positions(self, values: list[Any]) -> Iterable[int]:
        for i, val in enumerate(values):
            if val is not None and self._compiled.fullmatch(str(val)) is None:
                yield i

    def describe(self, count: int, table: str, column: str) -> str:
        return f"{count} row(s) in {table}.{column} do not match pattern {self._pattern!r}"


class ColumnInSetFold(ColumnFold):
    """column_in_set: every value belongs to ``params.allowed_values``.

    Comparison canonicalizes both sides via `str()`, consistent with the check-digit validators.
    Nulls are skipped by default; `params.allow_null: false` flips null cells to findings.

    Raises:
        ValueError: `params.allowed_values` missing or empty (at construction).
    """

    name = "column_in_set"

    def __init__(self, entry: dict[str, Any], *, cap: int | None) -> None:
        super().__init__(entry, cap=cap)
        params: dict[str, Any] = entry.get("params") or {}
        allowed_raw = params.get("allowed_values")
        if not allowed_raw or not isinstance(allowed_raw, list):
            raise ValueError(
                "column_in_set validator requires params.allowed_values "
                "(a non-empty list of allowed values)."
            )
        self._allowed: set[str] = {str(v) for v in allowed_raw}
        self._allow_null = bool(params.get("allow_null", True))

    def failing_positions(self, values: list[Any]) -> Iterable[int]:
        for i, val in enumerate(values):
            if val is None:
                if not self._allow_null:
                    yield i
            elif str(val) not in self._allowed:
                yield i

    def describe(self, count: int, table: str, column: str) -> str:
        return (
            f"{count} row(s) in {table}.{column} are not in the allowed set "
            f"({len(self._allowed)} value(s))"
        )


def validate_regex_match(
    outputs: dict[str, pa.Table],
    entry: dict[str, Any],
    config: dict[str, Any],
    *,
    sources: dict[str, pa.Table] | None = None,
) -> tuple[ValidatorFinding, ...]:
    """regex_match over whole tables: one span per table (see `RegexMatchFold`).

    Args:
        outputs: Read-only pipeline outputs.
        entry: Config block; requires `params.pattern` (str).
        config: Full pipeline config dict (read for the quarantine setting only).
        sources: Unused by this validator (registry contract, D2).

    Returns:
        Tuple of ValidatorFinding for each column with non-matching rows.

    Raises:
        ValueError: `params.pattern` missing, or fails to compile.
    """
    fold = RegexMatchFold(entry, cap=finding_index_cap(config))
    return run_whole(fold, outputs).findings


def validate_column_in_set(
    outputs: dict[str, pa.Table],
    entry: dict[str, Any],
    config: dict[str, Any],
    *,
    sources: dict[str, pa.Table] | None = None,
) -> tuple[ValidatorFinding, ...]:
    """column_in_set over whole tables: one span per table (see `ColumnInSetFold`).

    Args:
        outputs: Read-only pipeline outputs.
        entry: Config block; requires `params.allowed_values` (non-empty list).
        config: Full pipeline config dict (read for the quarantine setting only).
        sources: Unused by this validator (registry contract, D2).

    Returns:
        Tuple of ValidatorFinding for each column with out-of-set rows.

    Raises:
        ValueError: `params.allowed_values` missing or empty.
    """
    fold = ColumnInSetFold(entry, cap=finding_index_cap(config))
    return run_whole(fold, outputs).findings
