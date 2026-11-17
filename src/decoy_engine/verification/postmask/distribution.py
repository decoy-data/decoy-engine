"""Which distribution facts a masked column keeps (`post_scan.distribution`, row 31).

The check compares a table's masking input with its output on five value-free facts: the row
count, and per column the null rate, the distinct ratio (distinct over non-null), the mean and
the standard deviation. A strategy that changes values by design, or breaks one of these facts for
a reason of its own, must not be checked on it, or a correct run would read as a breach. There is
no second per-strategy table here. The facts derive from the behaviour contract:

- `contracts.distribution_behavior.distribution_behavior_for` gives the cardinality and the moments:
  `preserves_all` keeps both, `preserves_cardinality_only` keeps the distinct ratio, every other
  label keeps neither.
- `contracts.distribution_behavior.NULLS_NOT_PRESERVED` names the strategies whose output nulls do
  not follow their source nulls; every other strategy keeps `null_rate`.
- `categorical` keeps only `row_count` and `null_rate` whatever its label. Weighted and
  `from_profile` categorical are labelled `preserves_all` (the marginal frequencies follow the
  source), but the output values are drawn from a fixed category list, so the distinct ratio, mean
  and standard deviation of the source column do not carry over.
- A column with a `when:` rule is a mixture of masked and source cells, so it keeps only
  `row_count` and, where its strategy keeps nulls, `null_rate`.

Pure: no data, no I/O. Established practice for the tolerance model: Deequ
`RelativeRateOfChangeStrategy` and Great Expectations `expect_column_mean_to_be_between` and
`expect_column_proportion_of_unique_values_to_be_between` (a tolerance on a named summary
statistic, not a significance test). The streamed moments are in `_column_facts.py`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, get_args

from decoy_engine.contracts.distribution_behavior import (
    NULLS_NOT_PRESERVED,
    distribution_behavior_for,
)
from decoy_engine.verification.postmask._column_facts import ValueFacts

_Fact = Literal["row_count", "null_rate", "distinct_ratio", "mean", "std"]
FACTS: tuple[_Fact, ...] = get_args(_Fact)

_ROW: frozenset[_Fact] = frozenset({"row_count"})
_NULLS: frozenset[_Fact] = frozenset({"row_count", "null_rate"})
_CARDINALITY: frozenset[_Fact] = frozenset({"row_count", "null_rate", "distinct_ratio"})
_ALL: frozenset[_Fact] = frozenset(FACTS)
# Strategies whose label claims more than the five facts can show; see the module docstring.
_VALUES_REMAPPED = frozenset({"categorical"})


def preserved_facts(
    strategy: str | None,
    provider_config: tuple[tuple[str, Any], ...] | None = None,
    *,
    conditional: bool = False,
) -> frozenset[_Fact]:
    """The facts a column configured with `strategy` is checked on; always includes `row_count`.

    `provider_config` matters only for `categorical`, whose label depends on it. An unknown
    strategy is checked on the row count alone, so a strategy added without a label cannot
    produce a false breach."""
    label = distribution_behavior_for(strategy, provider_config)
    if label is None or strategy is None:
        return _ROW
    keeps_nulls = strategy not in NULLS_NOT_PRESERVED
    if not keeps_nulls:
        return _ROW
    if conditional or strategy in _VALUES_REMAPPED:
        return _NULLS
    if label == "preserves_all":
        return _ALL
    if label == "preserves_cardinality_only":
        return _CARDINALITY
    return _NULLS


Severity = Literal["info", "warning", "fail", "error"]


@dataclass(frozen=True)
class DistributionFinding:
    """One checked fact. `column` is `None` for `row_count`; `delta_pct` is `None` when the change
    is undefined (see the module docstring)."""

    table: str
    column: str | None
    fact: _Fact
    severity: Severity
    delta_pct: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "column": self.column,
            "fact": self.fact,
            "severity": self.severity,
            "delta_pct": self.delta_pct,
        }


@dataclass(frozen=True)
class ColumnSides:
    """The measured facts of one column on its masking input and its output.

    `facts` is what `preserved_facts` allows. A distinct count is `None` when counting it failed,
    which is an `error` row for `distinct_ratio`."""

    column: str
    facts: frozenset[_Fact]
    source: ValueFacts
    output: ValueFacts
    source_distinct: int | None
    output_distinct: int | None


def _finding(
    table: str, column: str | None, fact: _Fact, severity: Severity, delta: float | None
) -> DistributionFinding:
    rounded = round(delta, 1) if delta is not None and math.isfinite(delta) else None
    return DistributionFinding(table, column, fact, severity, rounded)


def _judged(
    table: str, column: str | None, fact: _Fact, delta: float, tolerance_pct: float
) -> DistributionFinding:
    """A defined change: `warning` above the tolerance, `info` inside it. A change too large to
    represent (infinite) is a breach with no delta; one that is not a number is undefined, so `info`."""
    if math.isnan(delta):
        return _finding(table, column, fact, "info", None)
    # An infinite delta (a finite change too large to represent) compares above any tolerance and
    # is a breach; `_finding` writes it with no ratio.
    return _finding(table, column, fact, "warning" if delta > tolerance_pct else "info", delta)


def _row_count(
    table: str, source_rows: int, quarantined: int, output_rows: int, tolerance_pct: float
) -> DistributionFinding:
    expected = source_rows - quarantined
    if expected <= 0:
        # Nothing expected: both empty is a match; rows from nothing is a breach with no ratio.
        if output_rows == 0:
            return _finding(table, None, "row_count", "info", 0.0)
        return _finding(table, None, "row_count", "warning", None)
    delta = abs(output_rows - expected) / expected * 100.0
    return _judged(table, None, "row_count", delta, tolerance_pct)


def _points(a: float, b: float) -> float:
    return abs(a - b) * 100.0


def _null_rate(table: str, c: ColumnSides, tolerance_pct: float) -> DistributionFinding:
    if c.source.error or c.output.error:
        return _finding(table, c.column, "null_rate", "error", None)
    if c.source.rows == 0 or c.output.rows == 0:
        return _finding(table, c.column, "null_rate", "info", None)
    delta = _points(c.source.nulls / c.source.rows, c.output.nulls / c.output.rows)
    return _judged(table, c.column, "null_rate", delta, tolerance_pct)


def _distinct_ratio(table: str, c: ColumnSides, tolerance_pct: float) -> DistributionFinding:
    if c.source_distinct is None or c.output_distinct is None or c.source.error or c.output.error:
        return _finding(table, c.column, "distinct_ratio", "error", None)
    src_n, out_n = c.source.non_null, c.output.non_null
    if src_n == 0 and out_n == 0:
        return _finding(table, c.column, "distinct_ratio", "info", None)
    if src_n == 0 or out_n == 0:
        return _finding(table, c.column, "distinct_ratio", "warning", None)
    delta = _points(c.source_distinct / src_n, c.output_distinct / out_n)
    return _judged(table, c.column, "distinct_ratio", delta, tolerance_pct)


def _moment_facts(table: str, c: ColumnSides, tolerance_pct: float) -> list[DistributionFinding]:
    wanted = [f for f in ("mean", "std") if f in c.facts]
    if c.source.error or c.output.error:
        return [_finding(table, c.column, f, "error", None) for f in wanted]
    src, out = c.source.moments, c.output.moments
    if c.output.non_finite and src is not None:
        # A finite source whose output is infinite or NaN has moved: a breach, not a gap. A
        # source that is itself non-finite or non-numeric stays `info` below.
        return [_finding(table, c.column, f, "warning", None) for f in wanted]
    src_std = src.std if src is not None else None
    out_std = out.std if out is not None else None
    if src is None or out is None or src_std is None or out_std is None:
        # Non-numeric, non-finite, or fewer than two numeric cells on a side.
        return [_finding(table, c.column, f, "info", None) for f in wanted]
    rows: list[DistributionFinding] = []
    for fact in wanted:
        if fact == "mean":
            if src_std > 0:
                rows.append(
                    _judged(
                        table,
                        c.column,
                        "mean",
                        abs(out.mean - src.mean) / src_std * 100.0,
                        tolerance_pct,
                    )
                )
            elif src.mean != 0:
                rows.append(
                    _judged(
                        table,
                        c.column,
                        "mean",
                        abs(out.mean - src.mean) / abs(src.mean) * 100.0,
                        tolerance_pct,
                    )
                )
            elif out.mean == 0:
                rows.append(_finding(table, c.column, "mean", "info", 0.0))
            else:
                rows.append(_finding(table, c.column, "mean", "warning", None))
        elif src_std > 0:
            rows.append(
                _judged(
                    table, c.column, "std", abs(out_std - src_std) / src_std * 100.0, tolerance_pct
                )
            )
        elif out_std > 0:
            rows.append(_finding(table, c.column, "std", "warning", None))
        else:
            rows.append(_finding(table, c.column, "std", "info", 0.0))
    return rows


def distribution_findings(
    table: str,
    *,
    source_rows: int,
    quarantined: int,
    output_rows: int,
    columns: Sequence[ColumnSides],
    tolerance_pct: float,
) -> tuple[DistributionFinding, ...]:
    """One row per checked fact of one mask table: `row_count` first, then each column's facts in
    the order of `FACTS`. A breach is a `warning`; `fail` severity arrives with the blocking slice.

    `quarantined` is the number of rows quarantine removed from the source: the expected output
    row count is `source_rows - quarantined`."""
    rows = [_row_count(table, source_rows, quarantined, output_rows, tolerance_pct)]
    for c in columns:
        if "null_rate" in c.facts:
            rows.append(_null_rate(table, c, tolerance_pct))
        if "distinct_ratio" in c.facts:
            rows.append(_distinct_ratio(table, c, tolerance_pct))
        rows.extend(_moment_facts(table, c, tolerance_pct))
    return tuple(rows)
