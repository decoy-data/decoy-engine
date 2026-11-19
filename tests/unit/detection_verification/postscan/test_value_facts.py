"""DI-T3: null counts and streamed moments in the column-facts passes (row 31, slice DI-1a).

The moments merge per-batch (count, mean, M2) tallies by the pairwise formula of Chan, Golub and
LeVeque, so the batch cuts do not change the result. Averaging per-batch means would.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from decoy_engine.profiling import KEY_BATCH_ROWS
from decoy_engine.verification.postmask import from_table
from decoy_engine.verification.postmask._column_facts import (
    Moments,
    column_facts,
    value_facts,
)
from decoy_engine.verification.postmask._stream_input import TableBatches

LIMIT = "256MB"


def _values(n: int) -> list[float | None]:
    # Uneven values with a large offset, so a naive sum of squares loses digits and batch means
    # differ from each other.
    return [
        None if k % 9 == 4 else 1e9 + ((k * 2654435761) % 100_003) / 7.0 + (k // 3)
        for k in range(n)
    ]


def _present(values: list[float | None]) -> np.ndarray:
    return np.array([v for v in values if v is not None], dtype="float64")


def _cut(table: pa.Table, size: int) -> TableBatches:
    """The table as a stream; the batch size is passed to each read, not kept here."""
    del size
    return from_table("t", table)


@pytest.mark.parametrize("size", [1, 7, 50_000])
def test_source_only_moments_equal_the_whole_column_at_every_batch_cut(
    size: int, tmp_path: Path
) -> None:
    n = 400
    vals = _values(n)
    table = pa.table({"x": pa.array(vals, pa.float64()), "i": pa.array(range(n), pa.int64())})
    got = value_facts(_cut(table, size), ["x", "i"], batch_rows=size)
    want = _present(vals)
    x = got["x"]
    assert x.rows == n and x.nulls == n - len(want) and x.non_null == len(want)
    assert x.moments is not None
    assert abs(x.moments.mean - want.mean()) <= 1e-9 * max(1.0, abs(want.mean()))
    assert abs(x.moments.std - want.std(ddof=1)) <= 1e-9 * max(1.0, want.std(ddof=1))
    i = got["i"]
    assert i.nulls == 0 and i.moments is not None
    assert abs(i.moments.mean - np.arange(n).mean()) <= 1e-9


@pytest.mark.parametrize("size", [1, 7, 50_000])
def test_output_pass_moments_equal_the_whole_column_at_every_batch_cut(
    size: int, tmp_path: Path
) -> None:
    n = 400
    vals = _values(n)
    out = pa.table({"x": pa.array(vals, pa.float64())})
    src = pa.table({"x": pa.array(range(n), pa.int64())})
    facts = column_facts(
        _cut(src, size),
        _cut(out, size),
        ["x"],
        batch_rows=size,
        scratch=tmp_path,
        memory_limit=LIMIT,
    )["x"]
    values = facts.output_values
    assert values is not None and values.moments is not None
    want = _present(vals)
    assert values.nulls == n - len(want)
    assert math.isclose(values.moments.mean, want.mean(), rel_tol=1e-9)
    assert abs(values.moments.std - want.std(ddof=1)) <= 1e-9 * max(1.0, want.std(ddof=1))


def test_averaging_batch_means_would_differ_so_the_cut_test_can_fail() -> None:
    vals = [1.0] * 10 + [100.0] * 2
    parts = [np.array(vals[:10]), np.array(vals[10:])]
    assert abs(np.mean([p.mean() for p in parts]) - np.mean(vals)) > 1.0
    merged = Moments()
    for p in parts:
        merged = merged.merge(Moments.of(p))
    assert abs(merged.mean - np.mean(vals)) <= 1e-12


def test_moment_merge_is_associative_and_an_empty_side_is_the_identity() -> None:
    a, b, c = (Moments.of(np.arange(k, k + 5, dtype="float64") ** 1.5) for k in (0, 7, 30))
    left, right = a.merge(b).merge(c), a.merge(b.merge(c))
    assert left.count == right.count == 15
    assert math.isclose(left.mean, right.mean, rel_tol=1e-12)
    assert math.isclose(left.m2, right.m2, rel_tol=1e-12)
    assert Moments().merge(a) == a and a.merge(Moments()) == a


def test_a_constant_and_a_single_value_have_a_defined_std() -> None:
    constant = Moments.of(np.full(10, 3.0))
    assert constant.std == 0.0
    assert Moments.of(np.array([3.0])).std is None
    assert Moments().std is None


def test_non_numeric_and_boolean_columns_carry_no_moments_but_count_nulls() -> None:
    table = pa.table(
        {
            "s": pa.array(["a", None, "c", None]),
            "b": pa.array([True, False, None, True]),
        }
    )
    got = value_facts(_cut(table, 2), ["s", "b"], batch_rows=2)
    assert got["s"].moments is None and got["s"].nulls == 2
    assert got["b"].moments is None and got["b"].nulls == 1


def test_a_non_finite_value_withholds_the_moments_without_failing_the_pass() -> None:
    table = pa.table(
        {"x": pa.array([1.0, float("inf"), 3.0, None]), "y": pa.array([1.0, 2.0, 3.0, 4.0])}
    )
    got = value_facts(_cut(table, 2), ["x", "y"], batch_rows=2)
    assert got["x"].moments is None and got["x"].error is None
    assert got["x"].nulls == 1
    assert got["y"].moments is not None and got["y"].moments.mean == 2.5


def test_a_missing_column_is_skipped() -> None:
    table = pa.table({"x": pa.array([1, 2, 3], pa.int64())})
    assert set(value_facts(_cut(table, 2), ["x", "nope"], batch_rows=2)) == {"x"}


def test_a_stream_shorter_than_its_declared_rows_is_refused() -> None:
    table = pa.table({"x": pa.array([1, 2, 3, 4], pa.int64())})
    short = _cut(table, 2)

    def read(columns, batch_rows):
        yield from list(short.read(columns, batch_rows))[:1]

    from dataclasses import replace

    with pytest.raises(ValueError):
        value_facts(replace(short, read=read), ["x"], batch_rows=2)


def test_the_default_batch_size_is_the_key_batch_size() -> None:
    table = pa.table({"x": pa.array([1, 2, 3], pa.int64())})
    assert value_facts(_cut(table, KEY_BATCH_ROWS), ["x"])["x"].rows == 3


def test_every_fact_is_defined_or_none_and_round_trips_through_strict_json() -> None:
    """No inf or NaN reaches a written fact: an undefined std (below two values), a column with no
    non-null value, a non-finite value and an overflowing spread all give `None`, not a float."""
    table = pa.table(
        {
            "empty": pa.array([None, None, None], pa.float64()),
            "one": pa.array([None, 5.0, None], pa.float64()),
            "const": pa.array([2.0, 2.0, 2.0], pa.float64()),
            "inf": pa.array([1.0, float("inf"), 2.0], pa.float64()),
            "nan": pa.array([1.0, float("nan"), 2.0], pa.float64()),
            "huge": pa.array([1e200, -1e200, 1e200], pa.float64()),
            "ints": pa.array([1, 2, 4], pa.int64()),
        }
    )
    got = value_facts(_cut(table, 2), list(table.column_names), batch_rows=2)
    assert got["empty"].moments == Moments() and got["empty"].moments.std is None
    assert got["empty"].non_null == 0
    assert got["one"].moments is not None and got["one"].moments.std is None
    assert got["const"].moments is not None and got["const"].moments.std == 0.0
    for name in ("inf", "nan", "huge"):
        assert got[name].moments is None, name
        assert got[name].non_finite is True, name
        assert got[name].error is None, name
    assert got["empty"].non_finite is False and got["ints"].non_finite is False
    assert got["ints"].moments is not None and got["ints"].moments.std == pytest.approx(
        np.array([1, 2, 4]).std(ddof=1)
    )
    for facts in got.values():
        json.dumps(asdict(facts), allow_nan=False)
        if facts.moments is not None:
            json.dumps({"std": facts.moments.std}, allow_nan=False)


def test_the_standard_deviation_is_the_sample_one() -> None:
    values = np.array([1.0, 2.0, 4.0, 8.0])
    assert Moments.of(values).std == pytest.approx(values.std(ddof=1))
    assert Moments.of(values).std != pytest.approx(values.std(ddof=0))


@pytest.mark.parametrize("constant", [0.1, 1e6 + 0.1, 3.0])
def test_a_constant_float_column_has_exact_moments_at_any_batch_cut(constant: float) -> None:
    """The pairwise merge of a constant leaves an M2 a few ulps above zero, which a float test
    `std > 0` would read as a spread. Source cut at 7 and output cut at 50,000 must agree."""
    from decoy_engine.verification.postmask.distribution import ColumnSides, distribution_findings

    n = 1000
    table = pa.table({"x": pa.array([constant] * n, pa.float64())})
    src = value_facts(_cut(table, 7), ["x"], batch_rows=7)["x"]
    out = value_facts(_cut(table, 50_000), ["x"], batch_rows=50_000)["x"]
    assert src.moments is not None and out.moments is not None
    assert src.moments.m2 == 0.0 and out.moments.m2 == 0.0
    assert src.moments.mean == constant == out.moments.mean
    rows = distribution_findings(
        "t",
        source_rows=n,
        quarantined=0,
        output_rows=n,
        columns=[ColumnSides("x", frozenset({"mean", "std"}), src, out, 1, 1)],
        tolerance_pct=1.0,
    )
    got = {r.fact: (r.severity, r.delta_pct) for r in rows if r.column == "x"}
    assert got == {"mean": ("info", 0.0), "std": ("info", 0.0)}


def test_a_duplicated_column_name_does_not_raise_in_the_numeric_check() -> None:
    from decoy_engine.verification.postmask._column_facts import _is_numeric

    schema = pa.schema([("x", pa.int64()), ("x", pa.string())])
    assert _is_numeric(schema, "x") is True
