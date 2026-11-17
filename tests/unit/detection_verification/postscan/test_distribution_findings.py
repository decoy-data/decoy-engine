"""DI-T4 (facts level): `distribution_findings` turns two sides' facts into value-free rows.

Every checked fact is one row (`info` inside tolerance, `warning` outside it); each undefined or
non-finite case of the plan's 3.2 table gets its stated severity and `delta_pct`, never NaN or
infinity. Each rule has a breach cell and a no-breach cell, so a rule that never fires cannot pass.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import numpy as np
import pytest

from decoy_engine.verification.postmask._column_facts import Moments, ValueFacts
from decoy_engine.verification.postmask.distribution import (
    FACTS,
    ColumnSides,
    DistributionFinding,
    Fact,
    distribution_findings,
)

ALL: frozenset[Fact] = frozenset(FACTS)


def _values(data: Sequence[float | None]) -> ValueFacts:
    present = np.array([v for v in data if v is not None], dtype="float64")
    return ValueFacts(len(data), len(data) - len(present), Moments.of(present))


def _col(
    src: Sequence[float | None],
    out: Sequence[float | None],
    *,
    facts: frozenset[Fact] = ALL,
    src_distinct: int | None = None,
    out_distinct: int | None = None,
) -> ColumnSides:
    s, o = _values(src), _values(out)
    return ColumnSides(
        "c",
        facts,
        s,
        o,
        len({v for v in src if v is not None}) if src_distinct is None else src_distinct,
        len({v for v in out if v is not None}) if out_distinct is None else out_distinct,
    )


def _run(
    col: ColumnSides | None,
    *,
    src_rows: int = 10,
    out_rows: int = 10,
    quarantined: int = 0,
    tol: float = 5.0,
) -> dict[tuple[str | None, str], DistributionFinding]:
    rows = distribution_findings(
        "t",
        source_rows=src_rows,
        quarantined=quarantined,
        output_rows=out_rows,
        columns=[col] if col is not None else [],
        tolerance_pct=tol,
    )
    return {(r.column, r.fact): r for r in rows}


SRC = [float(v) for v in range(1, 11)]


def test_equal_frames_have_no_breach_at_one_percent() -> None:
    rows = _run(_col(SRC, SRC), tol=1.0)
    assert {k[1] for k in rows} == set(FACTS)
    assert {r.severity for r in rows.values()} == {"info"}
    assert all(r.delta_pct == 0.0 for r in rows.values())


def test_a_mean_shifted_by_one_point_two_times_breaches_at_five_percent() -> None:
    out = [v * 1.2 for v in SRC]
    rows = _run(_col(SRC, out, facts=frozenset({"row_count", "mean"})))
    mean = rows[("c", "mean")]
    # |6.6 - 5.5| / std(1..10, ddof=1) = 1.1 / 3.0277 = 36.3%
    assert mean.severity == "warning" and mean.delta_pct == 36.3
    # The same shift is inside a 40% tolerance.
    assert _run(_col(SRC, out, facts=frozenset({"mean"})), tol=40.0)[("c", "mean")].severity == (
        "info"
    )


def test_findings_name_table_column_fact_only_and_row_count_has_no_column() -> None:
    rows = _run(_col(SRC, SRC))
    assert (None, "row_count") in rows
    assert rows[(None, "row_count")].table == "t"
    assert {f.name for f in DistributionFinding.__dataclass_fields__.values()} == {
        "table",
        "column",
        "fact",
        "severity",
        "delta_pct",
    }


def test_the_row_count_rule_is_relative_to_source_minus_quarantined() -> None:
    inside = _run(None, src_rows=100, quarantined=3, out_rows=97)[(None, "row_count")]
    assert (inside.severity, inside.delta_pct) == ("info", 0.0)
    # Without the subtraction 97 against 100 is 3%: the cell that fails if it is skipped.
    breach = _run(None, src_rows=100, quarantined=0, out_rows=90)[(None, "row_count")]
    assert (breach.severity, breach.delta_pct) == ("warning", 10.0)
    off = _run(None, src_rows=100, quarantined=3, out_rows=90)[(None, "row_count")]
    assert off.delta_pct == pytest.approx(7.2, abs=0.05)


def test_row_count_edge_cases() -> None:
    both_zero = _run(None, src_rows=0, out_rows=0)[(None, "row_count")]
    assert (both_zero.severity, both_zero.delta_pct) == ("info", 0.0)
    from_nothing = _run(None, src_rows=0, out_rows=5)[(None, "row_count")]
    assert (from_nothing.severity, from_nothing.delta_pct) == ("warning", None)
    fully_quarantined = _run(None, src_rows=4, quarantined=4, out_rows=1)[(None, "row_count")]
    assert (fully_quarantined.severity, fully_quarantined.delta_pct) == ("warning", None)


def test_null_rate_uses_percentage_points() -> None:
    src = [1.0] * 8 + [None, None]  # 20%
    inside = _run(_col(src, [1.0] * 7 + [None] * 3, facts=frozenset({"null_rate"})))
    assert inside[("c", "null_rate")].severity == "warning"  # 10 points
    assert inside[("c", "null_rate")].delta_pct == 10.0
    near = _run(_col(src, [1.0] * 8 + [None] * 2, facts=frozenset({"null_rate"})))
    assert near[("c", "null_rate")].severity == "info"
    # A 40% relative change of a 5-point rate is not a breach: points, not ratio.
    small = _run(
        _col([1.0] * 19 + [None], [1.0] * 18 + [None] * 2, facts=frozenset({"null_rate"})),
        src_rows=20,
        out_rows=20,
    )
    assert small[("c", "null_rate")].delta_pct == 5.0


def test_null_rate_with_a_side_of_zero_rows_is_info_with_no_delta() -> None:
    empty = _col([], [1.0, 2.0], facts=frozenset({"null_rate"}))
    row = _run(empty, src_rows=0, out_rows=2)[("c", "null_rate")]
    assert (row.severity, row.delta_pct) == ("info", None)


def test_distinct_ratio_is_over_non_null_cells_in_points() -> None:
    src = [1.0, 2.0, 3.0, 4.0, None]  # 4 distinct / 4 non-null = 1.0
    out = [1.0, 1.0, 2.0, 3.0, None]  # 3 / 4 = 0.75 -> 25 points
    row = _run(_col(src, out, facts=frozenset({"distinct_ratio"})), src_rows=5, out_rows=5)
    assert row[("c", "distinct_ratio")].delta_pct == 25.0
    assert row[("c", "distinct_ratio")].severity == "warning"
    same = _run(_col(src, src, facts=frozenset({"distinct_ratio"})), src_rows=5, out_rows=5)
    assert same[("c", "distinct_ratio")].severity == "info"


def test_distinct_ratio_with_no_non_null_cells() -> None:
    none = [None, None]
    both = _run(_col(none, none, facts=frozenset({"distinct_ratio"})), src_rows=2, out_rows=2)[
        ("c", "distinct_ratio")
    ]
    assert (both.severity, both.delta_pct) == ("info", None)
    one = _run(_col([1.0, 2.0], none, facts=frozenset({"distinct_ratio"})), src_rows=2, out_rows=2)[
        ("c", "distinct_ratio")
    ]
    assert (one.severity, one.delta_pct) == ("warning", None)


def test_mean_with_a_constant_source_is_relative_to_the_source_mean() -> None:
    src = [10.0] * 5
    row = _run(_col(src, [11.0] * 5, facts=frozenset({"mean"})), src_rows=5, out_rows=5, tol=5.0)[
        ("c", "mean")
    ]
    assert (row.severity, row.delta_pct) == ("warning", 10.0)
    inside = _run(
        _col(src, [10.2] * 5, facts=frozenset({"mean"})), src_rows=5, out_rows=5, tol=5.0
    )[("c", "mean")]
    assert inside.severity == "info"


def test_mean_with_a_constant_zero_source() -> None:
    zeros = [0.0] * 5
    moved = _run(_col(zeros, [1.0] * 5, facts=frozenset({"mean"})), src_rows=5, out_rows=5)
    assert (moved[("c", "mean")].severity, moved[("c", "mean")].delta_pct) == ("warning", None)
    same = _run(_col(zeros, zeros, facts=frozenset({"mean"})), src_rows=5, out_rows=5)
    assert (same[("c", "mean")].severity, same[("c", "mean")].delta_pct) == ("info", 0.0)


def test_std_is_relative_and_a_constant_source_is_a_breach_only_when_the_output_varies() -> None:
    wide = [v * 2 for v in SRC]
    row = _run(_col(SRC, wide, facts=frozenset({"std"})))[("c", "std")]
    assert (row.severity, row.delta_pct) == ("warning", 100.0)
    flat = [3.0] * 5
    grew = _run(
        _col(flat, [1.0, 2.0, 3.0, 4.0, 5.0], facts=frozenset({"std"})), src_rows=5, out_rows=5
    )
    assert (grew[("c", "std")].severity, grew[("c", "std")].delta_pct) == ("warning", None)
    still = _run(_col(flat, [4.0] * 5, facts=frozenset({"std"})), src_rows=5, out_rows=5)
    assert (still[("c", "std")].severity, still[("c", "std")].delta_pct) == ("info", 0.0)


def test_moments_from_fewer_than_two_cells_are_info_with_no_delta() -> None:
    one = _col([5.0, None, None], [5.0, 6.0, 7.0], facts=frozenset({"mean", "std"}))
    rows = _run(one, src_rows=3, out_rows=3)
    for fact in ("mean", "std"):
        assert (rows[("c", fact)].severity, rows[("c", fact)].delta_pct) == ("info", None)


def test_a_non_numeric_or_non_finite_column_is_info_with_no_delta() -> None:
    src = ValueFacts(5, 0, None)
    out = ValueFacts(5, 0, Moments.of(np.arange(5.0)))
    col = ColumnSides("c", frozenset({"mean", "std"}), src, out, 5, 5)
    rows = _run(col, src_rows=5, out_rows=5)
    for fact in ("mean", "std"):
        assert (rows[("c", fact)].severity, rows[("c", fact)].delta_pct) == ("info", None)


def test_a_finite_source_with_a_non_finite_output_is_a_breach() -> None:
    finite = ValueFacts(5, 0, Moments.of(np.arange(5.0)))
    broken = ValueFacts(5, 0, None, non_finite=True)
    col = ColumnSides("c", frozenset({"mean", "std"}), finite, broken, 5, 5)
    rows = _run(col, src_rows=5, out_rows=5)
    for fact in ("mean", "std"):
        assert (rows[("c", fact)].severity, rows[("c", fact)].delta_pct) == ("warning", None)
    # No-breach neighbours: a source that is itself non-finite, or not numeric, stays info.
    for src in (broken, ValueFacts(5, 0, None)):
        rows = _run(
            ColumnSides("c", frozenset({"mean", "std"}), src, broken, 5, 5), src_rows=5, out_rows=5
        )
        for fact in ("mean", "std"):
            assert (rows[("c", fact)].severity, rows[("c", fact)].delta_pct) == ("info", None)
    # And the reverse: a non-finite source with a finite output is info too.
    rows = _run(ColumnSides("c", frozenset({"mean"}), broken, finite, 5, 5), src_rows=5, out_rows=5)
    assert rows[("c", "mean")].severity == "info"


def test_a_non_finite_output_stays_a_breach_for_a_source_with_under_two_cells_or_all_null() -> None:
    broken = ValueFacts(5, 0, None, non_finite=True)
    for src in (_values([5.0, None, None]), _values([None, None, None])):
        col = ColumnSides("c", frozenset({"mean", "std"}), src, broken, 3, 5)
        rows = _run(col, src_rows=3, out_rows=5)
        for fact in ("mean", "std"):
            assert (rows[("c", fact)].severity, rows[("c", fact)].delta_pct) == ("warning", None)


def test_a_finite_change_that_overflows_is_a_breach_not_info() -> None:
    src = ValueFacts(4, 0, Moments(4, 0.0, 1e-300))  # std ~ 5.8e-151
    out = ValueFacts(4, 0, Moments(4, 1e200, 1e-300))
    rows = _run(ColumnSides("c", frozenset({"mean"}), src, out, 4, 4), src_rows=4, out_rows=4)
    assert (rows[("c", "mean")].severity, rows[("c", "mean")].delta_pct) == ("warning", None)
    ok = ValueFacts(4, 0, Moments(4, 0.0, 12.0))
    near = _run(ColumnSides("c", frozenset({"mean"}), ok, ok, 4, 4), src_rows=4, out_rows=4)
    assert near[("c", "mean")].severity == "info"


def test_a_failed_read_is_an_error_row() -> None:
    failed = ValueFacts(5, 0, None, error="ValueError")
    ok = ValueFacts(5, 0, Moments.of(np.arange(5.0)))
    col = ColumnSides(
        "c", frozenset({"null_rate", "mean", "std", "distinct_ratio"}), failed, ok, 5, 5
    )
    rows = _run(col, src_rows=5, out_rows=5)
    for fact in ("null_rate", "mean", "std"):
        assert (rows[("c", fact)].severity, rows[("c", fact)].delta_pct) == ("error", None), fact
    lost = ColumnSides("c", frozenset({"distinct_ratio"}), ok, ok, None, 5)
    row = _run(lost, src_rows=5, out_rows=5)[("c", "distinct_ratio")]
    assert (row.severity, row.delta_pct) == ("error", None)


def test_only_the_facts_a_column_keeps_are_checked() -> None:
    rows = _run(_col(SRC, [v * 3 for v in SRC], facts=frozenset({"row_count", "null_rate"})))
    assert {k[1] for k in rows} == {"row_count", "null_rate"}
    assert {r.severity for r in rows.values()} == {"info"}


def test_every_findings_list_survives_strict_json() -> None:
    cases = [
        _col(SRC, SRC),
        _col([0.0] * 5, [1.0] * 5),
        _col([None, None], [1.0, 2.0]),
        _col([1e200, -1e200, 1e200], [1.0, 2.0, 3.0]),
        _col([5.0], [5.0]),
    ]
    for col in cases:
        rows = distribution_findings(
            "t",
            source_rows=5,
            quarantined=0,
            output_rows=0,
            columns=[col],
            tolerance_pct=5.0,
        )
        dumped = json.dumps([r.as_dict() for r in rows], allow_nan=False)
        assert json.loads(dumped) == [r.as_dict() for r in rows]
        for r in rows:
            assert r.delta_pct is None or np.isfinite(r.delta_pct)
            assert r.severity in {"info", "warning", "fail", "error"}


def test_a_row_holds_names_a_fact_a_severity_and_a_delta_and_nothing_else() -> None:
    sides = ColumnSides(
        "col", frozenset({"null_rate"}), _values([1.0, 2.0]), _values([1.0, 2.0]), 2, 2
    )
    rows = distribution_findings(
        "tbl", source_rows=2, quarantined=0, output_rows=2, columns=[sides], tolerance_pct=5.0
    )
    assert [r.as_dict() for r in rows] == [
        {"table": "tbl", "column": None, "fact": "row_count", "severity": "info", "delta_pct": 0.0},
        {
            "table": "tbl",
            "column": "col",
            "fact": "null_rate",
            "severity": "info",
            "delta_pct": 0.0,
        },
    ]
