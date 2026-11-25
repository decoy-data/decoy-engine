"""PREFLIGHT-ARROW-PROFILE S1b: the bounded Parquet profile recovers a flat date/time schema.

A valid Parquet file can hold a `time64[ns]` with a sub-microsecond part or a `date32` past year
9999. The whole-sample conversion to pandas fails; the profile then reads the sample column by
column and profiles the unholdable temporal column from Arrow (plan rev 6, sections 3 to 7).
Every other profile is the base one. The reference is built in `_arrow_support` from pyarrow and
pandas alone. Do not edit it to pass a cell.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.profile import _source
from decoy_engine.profile.arrow import _recovery
from tests.unit.profile._arrow_support import (
    PARQUET_KINDS,
    SAFE_FAILURE,
    assert_matches_base,
    base_profile,
    bounded_profile,
    make_reader,
    parquet_bytes,
)

T_NS_BAD = 3_600_000_000_000 + 987_654_321  # 01:00:00.987654321, not whole microseconds
EMAILS = ["a@x.test", "b@x.test", "c@x.test", "d@x.test"]


def _times(last: int = T_NS_BAD) -> pa.Array:
    return pa.array([0, 1000, 2000, last], pa.time64("ns"))


def _dates(last: int) -> pa.Array:
    return pa.array([0, 1, 2, last], pa.date32())


# (bad column, representable twin with the same distinct count)
TEMPORAL = {
    "time64_ns": (_times(), _times(3000)),
    "date_year_minus_768": (_dates(-1_000_000), _dates(1000)),
    "date_year_10183": (_dates(3_000_000), _dates(1000)),
}


def _column(profile: Any, name: str) -> Any:
    return next(c for c in profile.columns if c.name == name)


def _profile(table: pa.Table, kind: str, tmp_path: Path, mp: pytest.MonkeyPatch, **kw: Any) -> Any:
    reader = make_reader(kind, table, parquet_bytes(table), tmp_path, mp)
    return bounded_profile(reader, kind, **kw)


# ------------------------------------------------------------------ AT-1 / AT-2


@pytest.mark.parametrize("kind", PARQUET_KINDS)
@pytest.mark.parametrize("fixture", sorted(TEMPORAL))
def test_at2_a_value_pandas_cannot_hold_is_profiled(
    fixture: str, kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad, good = TEMPORAL[fixture]
    ours = _profile(pa.table({"t": bad, "email": EMAILS}), kind, tmp_path, monkeypatch)
    control_table = pa.table({"t": good, "email": EMAILS})
    control = base_profile(kind, control_table, parquet_bytes(control_table))
    t = _column(ours, "t")
    assert (t.dtype, t.null_count, t.distinct_count) == ("object", 0, 4)
    assert (t.avg_length, t.max_length, t.sampled) == (None, None, False)
    assert t.shape == _column(control, "t").shape
    assert _column(ours, "email") == _column(control, "email")


WITH_NULL = {
    "time64_ns": pa.array([0, None, 2000, T_NS_BAD, 5000], pa.time64("ns")),
    "date_year_minus_768": pa.array([0, None, 2, -1_000_000, 5], pa.date32()),
    "date_year_10183": pa.array([0, None, 2, 3_000_000, 5], pa.date32()),
}


@pytest.mark.parametrize("kind", PARQUET_KINDS)
@pytest.mark.parametrize("fixture", sorted(WITH_NULL))
def test_at2_a_missing_value_beside_the_bad_one(
    fixture: str, kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = pa.table({"t": WITH_NULL[fixture], "n": [1, 2, 3, 4, 5]})
    t = _column(_profile(table, kind, tmp_path, monkeypatch), "t")
    assert (t.null_count, t.distinct_count, t.row_count) == (1, 4, 5)
    assert t.dtype == "object"


@pytest.mark.parametrize("kind", PARQUET_KINDS)
@pytest.mark.parametrize("bad_at", ["first", "middle", "last"])
def test_at2_companions_and_order_hold_wherever_the_bad_field_sits(
    bad_at: str, kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = {
        "first": ["t", "email", "n"],
        "middle": ["email", "t", "n"],
        "last": ["email", "n", "t"],
    }[bad_at]

    def build(t: pa.Array) -> pa.Table:
        parts = {"t": t, "email": pa.array(EMAILS), "n": pa.array([1, 2, 3, 4])}
        return pa.table({name: parts[name] for name in layout})

    ours = _profile(build(_times()), kind, tmp_path, monkeypatch)
    twin = build(_times(3000))
    control = base_profile(kind, twin, parquet_bytes(twin))
    assert [c.name for c in ours.columns] == layout
    for name in ("email", "n"):
        assert _column(ours, name) == _column(control, name)


@pytest.mark.parametrize("kind", PARQUET_KINDS)
def test_at2_key_fields_follow_the_recovered_and_the_companion_columns(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = {
        "declared_pk": frozenset({"t"}),
        "fk_specs": {"email": ("parent", "mail"), "t": ("parent", "tm")},
    }
    table = pa.table({"t": _times(), "email": EMAILS})
    reader = make_reader(kind, table, parquet_bytes(table), tmp_path, monkeypatch)
    ours = bounded_profile(reader, kind, **keys)
    twin = pa.table({"t": _times(3000), "email": EMAILS})
    control = base_profile(kind, twin, parquet_bytes(twin), **keys)
    t, email = _column(ours, "t"), _column(ours, "email")
    assert (t.declared_pk, t.is_fk, t.fk_target) == (True, True, ("parent", "tm"))
    assert t.is_candidate_key_sampled is True
    assert (email.is_fk, email.fk_target) == (True, ("parent", "mail"))
    assert email == _column(control, "email")
    assert (t.declared_pk, t.is_fk, t.fk_target, t.is_candidate_key_sampled) == (
        _column(control, "t").declared_pk,
        _column(control, "t").is_fk,
        _column(control, "t").fk_target,
        _column(control, "t").is_candidate_key_sampled,
    )


@pytest.mark.parametrize("kind", PARQUET_KINDS)
def test_at2_two_bad_temporals_and_a_good_one(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = pa.table(
        {"d": _dates(3_000_000), "email": EMAILS, "t": _times(), "ok": _dates(1000)[:4]}
    )
    ours = _profile(table, kind, tmp_path, monkeypatch)
    assert [c.name for c in ours.columns] == ["d", "email", "t", "ok"]
    assert (_column(ours, "d").dtype, _column(ours, "t").dtype) == ("object", "object")
    assert (_column(ours, "d").distinct_count, _column(ours, "t").distinct_count) == (4, 4)
    assert _column(ours, "ok").distinct_count == 4


# ------------------------------------------------------------------ AT-6 / AT-9 / AT-10


@pytest.mark.parametrize("bad_row", [0, 9_999, 10_000, 80_000])
def test_at6_the_bad_value_counts_only_inside_the_bounded_sample(
    bad_row: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    n = 80_001
    values = [(i % 6000) * 1000 for i in range(n)]
    values[bad_row] = T_NS_BAD
    table = pa.table({"t": pa.array(values, pa.time64("ns")), "email": ["e"] * n})
    rng = random.Random(5)
    state = rng.getstate()
    reader = make_reader("local", table, parquet_bytes(table), tmp_path, monkeypatch)
    profile = bounded_profile(reader, "local", rng=rng)
    t = _column(profile, "t")
    assert (profile.row_count, profile.row_count_exact, t.row_count, t.sampled) == (
        n,
        True,
        n,
        True,
    )
    assert rng.getstate() == state  # recovery draws nothing
    if bad_row < 10_000:
        assert t.dtype == "object"
        assert t.distinct_count == len(set(values[:10_000]))
        assert t.is_candidate_key_sampled is False


@pytest.mark.parametrize("kind", ["s3", "gcs"])
def test_at9_cloud_readers_recover_the_same_column(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    n = 3_000
    values = [i * 1000 for i in range(n)]
    values[n - 1] = T_NS_BAD
    table = pa.table({"t": pa.array(values, pa.time64("ns")), "email": ["e"] * n})
    local = _profile(table, "local", tmp_path, monkeypatch, sample_rows=2_000)
    cloud = _profile(table, kind, tmp_path, monkeypatch, sample_rows=2_000)
    assert _column(cloud, "t") == _column(local, "t")
    assert _column(cloud, "t").distinct_count == 2_000  # the bad row sits past the sample


def test_at9_the_collector_keeps_the_batch_schema_not_the_separate_one() -> None:
    from decoy_engine.profile.arrow import head_table_from_batches

    batch = pa.record_batch(
        [pa.array([1, 2])], schema=pa.schema([("a", pa.int64())]).with_metadata({"k": "batch"})
    )
    supplied = pa.schema([("a", pa.int64())]).with_metadata({"k": "other"})
    table = head_table_from_batches(iter([batch]), 10, supplied)
    assert table.schema.metadata == {b"k": b"batch"}
    assert head_table_from_batches(iter([]), 10, supplied).schema.metadata == {b"k": b"other"}
    assert head_table_from_batches(iter([batch, batch]), 3, supplied).num_rows == 3


# ------------------------------------------------------------------ AT-3: parity with base


def _catalogue() -> dict[str, pa.Array]:
    from tests.native._rev9_profile_cases import CASES
    from tests.native._rev9_type_catalogue import CATALOGUE

    n = 12
    cases: dict[str, pa.Array] = {
        **CASES,
        "list_int": pa.array([[i] if i % 4 else None for i in range(n)]),
        "struct": pa.array([{"a": i, "b": "x"} if i % 5 else None for i in range(n)]),
        "map": pa.array(
            [[("k", i)] if i % 3 else None for i in range(n)], pa.map_(pa.string(), pa.int64())
        ),
    }
    for name, build in CATALOGUE.items():
        cases[f"cat_{name}_nonull"] = build(False)
        cases[f"cat_{name}_null"] = build(True)
    return cases


PARITY = _catalogue()


@pytest.mark.parametrize("kind", ["local", "resident"])
@pytest.mark.parametrize("ratio", ["whole", "capped"])
@pytest.mark.parametrize("case", sorted(PARITY))
def test_at3_every_type_profiles_as_base_does(
    case: str, ratio: str, kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arr = PARITY[case]
    table = pa.table({"x": arr, "s": pa.array([f"v{i}" for i in range(len(arr))])})
    sample = len(arr) if ratio == "whole" else max(1, len(arr) // 10)
    assert_matches_base(table, kind, tmp_path, monkeypatch, sample_rows=sample)


@pytest.mark.parametrize("kind", [*PARQUET_KINDS, "resident"])
def test_at3_zero_rows_and_table_level_fields(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = pa.table({"x": pa.array([], pa.int64()), "s": pa.array([], pa.string())})
    assert_matches_base(empty, kind, tmp_path, monkeypatch)
    table = pa.table({"id": list(range(40)), "ref": [i % 4 for i in range(40)], "v": ["x"] * 40})
    keys = {"declared_pk": frozenset({"id"}), "fk_specs": {"ref": ("p", "id")}}
    for rows in (100, 10):
        assert_matches_base(table, kind, tmp_path, monkeypatch, sample_rows=rows, **keys)


def test_at3_time64_ns_counts_one_to_five(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    table = pa.table({"t": pa.array([1, 2, 3, 4, 5], pa.time64("ns"))})
    # A resident table is text on base; Parquet raises on base and recovers.
    resident = base_profile("resident", table, b"")
    assert _column(resident, "t").dtype == "object"
    assert_matches_base(table, "resident", tmp_path, monkeypatch)
    recovered = _profile(table, "local", tmp_path, monkeypatch)
    assert _column(recovered, "t").distinct_count == 5
    holdable = pa.table({"t": pa.array([1000, 2000, 3000, 4000, 5000], pa.time64("ns"))})
    assert_matches_base(holdable, "local", tmp_path, monkeypatch)


# ------------------------------------------------------------------ AT-4: dispatch counts


class _Spy:
    def __init__(self, mp: pytest.MonkeyPatch) -> None:
        self.recover = 0
        self.arrow: list[str] = []
        real_recover = _source.recover_temporal_profile
        real_arrow = _recovery.arrow_column_profile

        def recover(*a: Any, **k: Any) -> Any:
            self.recover += 1
            return real_recover(*a, **k)

        def arrow(name: str, *a: Any, **k: Any) -> Any:
            self.arrow.append(name)
            return real_arrow(name, *a, **k)

        mp.setattr(_source, "recover_temporal_profile", recover)
        mp.setattr(_recovery, "arrow_column_profile", arrow)


def test_at4_success_never_enters_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _Spy(monkeypatch)
    table = pa.table({"t": _times(3000), "email": EMAILS})
    for kind in ("resident", "local"):
        _profile(table, kind, tmp_path, monkeypatch)
    assert (spy.recover, spy.arrow) == (0, [])


def test_at4_recovery_runs_once_and_profiles_only_the_bad_temporals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _Spy(monkeypatch)
    table = pa.table({"d": _dates(3_000_000), "email": EMAILS, "t": _times(), "ok": _dates(7)})
    _profile(table, "local", tmp_path, monkeypatch)
    assert spy.recover == 1
    assert spy.arrow == ["d", "t"]


def test_at4_an_ineligible_failure_never_profiles_from_arrow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import decimal

    spy = _Spy(monkeypatch)
    table = pa.table({"t": _times(), "dec": pa.array([decimal.Decimal("1.5")] * 4)})
    with pytest.raises(ValueError, match=SAFE_FAILURE):
        _profile(table, "local", tmp_path, monkeypatch)
    assert spy.arrow == []


class _BrokenTable:
    """A sample whose whole conversion fails with a producer error that quotes a cell."""

    def __init__(self, table: pa.Table) -> None:
        self._table = table
        self.num_rows = table.num_rows

    def __len__(self) -> int:
        return self.num_rows

    def to_pandas(self) -> Any:
        raise KeyError("MARKER-CELL")


class _BrokenReader:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def row_count(self) -> Any:
        return self._inner.row_count()

    def schema(self) -> pa.Schema:
        return self._inner.schema()

    def sample_table(self, sample_rows: int) -> Any:
        return _BrokenTable(self._inner.sample_table(sample_rows))

    def sample_frame(self, sample_rows: int) -> Any:  # pragma: no cover - never read
        raise AssertionError("the bounded profile reads the sample as a table")


def test_at4_a_key_error_at_conversion_is_labelled_and_never_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = pa.table({"t": _times(), "email": EMAILS})
    reader = _BrokenReader(make_reader("local", table, parquet_bytes(table), tmp_path, monkeypatch))
    spy = _Spy(monkeypatch)
    with pytest.raises(ValueError) as caught:
        bounded_profile(reader, "local")  # type: ignore[arg-type]
    assert str(caught.value) == "bounded source profile failed (KeyError)"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert (spy.recover, spy.arrow) == (0, [])


# ------------------------------------------------------------------ eligibility cells


def _schema(**fields: pa.DataType) -> pa.Schema:
    return pa.schema(list(fields.items()))


ELIGIBLE = _schema(t=pa.time64("ns"), e=pa.string(), n=pa.int16(), u=pa.uint64(), d=pa.date32())


def test_the_eligible_schema_is_exactly_the_closed_set() -> None:
    assert _recovery._eligible(ELIGIBLE)
    assert _recovery._eligible(_schema(d=pa.date32()))
    bad = {
        "decimal": _schema(t=pa.time64("ns"), x=pa.decimal128(10, 2)),
        "float": _schema(t=pa.time64("ns"), x=pa.float64()),
        "large_string": _schema(t=pa.time64("ns"), x=pa.large_string()),
        "dictionary": _schema(t=pa.time64("ns"), x=pa.dictionary(pa.int32(), pa.string())),
        "date64": _schema(t=pa.time64("ns"), x=pa.date64()),
        "time64_us": _schema(t=pa.time64("us")),
        "no_temporal": _schema(e=pa.string(), n=pa.int64()),
        "nested": _schema(t=pa.time64("ns"), x=pa.list_(pa.int64())),
        "timestamp": _schema(t=pa.time64("ns"), x=pa.timestamp("us")),
    }
    for label, schema in bad.items():
        assert not _recovery._eligible(schema), label
    for blob in (b"{}", b"", b"not json", b'{"columns": []}'):
        assert not _recovery._eligible(ELIGIBLE.with_metadata({b"pandas": blob})), blob
    assert _recovery._eligible(ELIGIBLE.with_metadata({b"other": b"x"}))
    duplicate = pa.schema([("t", pa.time64("ns")), ("t", pa.string())])
    assert not _recovery._eligible(duplicate)


# ------------------------------------------------------------------ the physical explanation


def test_the_physical_values_must_explain_the_failure() -> None:
    day = 86_400_000_000_000

    def check(values: list[int | None], t: pa.DataType) -> bool:
        return _recovery._explains_failure(pa.chunked_array([pa.array(values, t)]))

    ns = pa.time64("ns")
    assert check([0, 1, 2000], ns)  # sub-microsecond
    assert not check([0, 1000, 2000], ns)  # nothing to explain
    assert check([1, day - 1], ns)  # inside the civil day and fractional
    assert not check([1, day], ns)  # out of the civil day
    assert not check([None, None], ns)
    assert check([None, 1, 1000], ns)
    assert check([0, 3_000_000], pa.date32())
    assert check([-1_000_000, 1], pa.date32())
    assert not check([0, 2_932_896], pa.date32())  # year 9999-12-31 holds
    assert check([0, 2_932_897], pa.date32())
    assert not check([None], pa.date32())


@pytest.mark.parametrize("kind", PARQUET_KINDS)
def test_an_out_of_day_time_beside_a_fractional_one_is_refused(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = 86_400_000_000_000
    table = pa.table({"t": pa.array([1, 2000, day + 5, 3000], pa.time64("ns")), "e": EMAILS})
    with pytest.raises(ValueError, match=SAFE_FAILURE):
        _profile(table, kind, tmp_path, monkeypatch)


# ------------------------------------------------------------------ the S1a column profile


def test_a_dense_union_column_has_no_distinct_count() -> None:
    """`count_distinct` has no kernel for a union; the S1a profile reports None, not an error.
    The chunked first-chunk profile reaches this without the bounded profile's admission."""
    import pyarrow.compute as pc

    from decoy_engine.profile.arrow import arrow_column_profile

    union = pa.UnionArray.from_dense(
        pa.array([0, 1, 0], pa.int8()),
        pa.array([0, 0, 1], pa.int32()),
        [pa.array([1, 2], pa.int64()), pa.array(["x"])],
    )
    with pytest.raises(pa.ArrowNotImplementedError):
        pc.count_distinct(union)
    assert arrow_column_profile("u", union).distinct_count is None
