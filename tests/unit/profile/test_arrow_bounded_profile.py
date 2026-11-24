"""PREFLIGHT-ARROW-PROFILE S1b: the bounded profile of a source that holds Arrow is computed from
the Arrow sample, never through pandas.

AT-2 (a value pandas cannot hold), AT-3 (parity with the pandas walk over every type), AT-4 (the
conversion spy), AT-6 (sample bounds), AT-8 (the one value that moves), AT-9 (cloud readers).
The oracle is `walk_dataframe` over `sample_frame`, unchanged. Do not edit it to pass a cell.
Companions: `test_arrow_bounded_profile_metadata.py` (AT-3b, AT-3c).
"""

from __future__ import annotations

import dataclasses
import random
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pytest

from decoy_engine.profile import _source
from decoy_engine.profile._readers import ParquetFileSource
from tests.native._rev9_profile_cases import CASES
from tests.native._rev9_type_catalogue import CATALOGUE
from tests.unit.profile._arrow_support import (
    READER_KINDS,
    assert_same_profile,
    bounded_profile,
    make_reader,
    oracle_profile,
    parquet_bytes,
)

T_NS_BAD = 3_600_000_000_000 + 987_654_321  # 01:00:00.987654321, not whole microseconds
EMAILS = ["a@x.test", "b@x.test", "c@x.test", "d@x.test"]


def _t_ns(bad: int | None = T_NS_BAD) -> pa.Table:
    value = 1000 if bad is None else bad
    return pa.table(
        {"t": pa.array([0, 1000, 2000, value], pa.time64("ns")), "email": EMAILS},
    )


def _d_far(days: int | None, *, null_at: int | None = None) -> pa.Table:
    values: list[int | None] = [0, 1, 2, 1000 if days is None else days]
    if null_at is not None:
        values[null_at] = None
    return pa.table({"t": pa.array(values, pa.date32()), "email": EMAILS})


FIXTURES = {
    "time64_ns": (_t_ns(), _t_ns(None)),
    "date_year_minus_768": (_d_far(-1_000_000), _d_far(None)),
    "date_year_10183": (_d_far(3_000_000), _d_far(None)),
}


def _column(profile: Any, name: str = "t") -> Any:
    return next(c for c in profile.columns if c.name == name)


# ------------------------------------------------------------------ AT-2


@pytest.mark.parametrize("kind", READER_KINDS)
@pytest.mark.parametrize("fixture", sorted(FIXTURES))
def test_at2_a_value_pandas_cannot_hold_is_profiled(
    fixture: str, kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad, good = FIXTURES[fixture]
    reader = make_reader(kind, bad, parquet_bytes(bad), tmp_path, monkeypatch)
    ours = _column(bounded_profile(reader, kind))
    # Built after `ours`: a cloud stub serves one object at a time.
    control_reader = make_reader(kind, good, parquet_bytes(good), tmp_path, monkeypatch)
    control = _column(oracle_profile(control_reader, kind))
    assert (ours.dtype, ours.null_count, ours.distinct_count) == ("object", 0, 4)
    assert (ours.avg_length, ours.max_length, ours.sampled) == (None, None, False)
    assert ours.shape == control.shape


@pytest.mark.parametrize("kind", ["local", "resident"])
def test_at2_a_missing_value_beside_the_bad_one(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = pa.table(
        {"t": pa.array([0, None, 2000, T_NS_BAD, 5000], pa.time64("ns")), "n": [1, 2, 3, 4, 5]}
    )
    reader = make_reader(kind, table, parquet_bytes(table), tmp_path, monkeypatch)
    col = _column(bounded_profile(reader, kind))
    assert (col.null_count, col.distinct_count) == (1, 4)


# ------------------------------------------------------------------ AT-3 parity


def _same_as_pandas(table: pa.Table, kind: str, tmp_path: Path, mp: Any, **kw: Any) -> None:
    try:
        data = parquet_bytes(table)
    except (pa.ArrowNotImplementedError, pa.ArrowInvalid, pa.ArrowTypeError):
        if kind != "resident":
            pytest.skip("parquet does not store this type")
        data = b""
    reader = make_reader(kind, table, data, tmp_path, mp)
    try:
        if kind == "resident":
            table.to_pandas()  # a table pandas cannot hold is AT-8's cell, not parity
        oracle = oracle_profile(reader, kind, **kw)
    except Exception:
        pytest.skip("pandas refuses this column; the bounded walk is not held to it")
    assert_same_profile(bounded_profile(reader, kind, **kw), oracle, kind)


def _nested() -> dict[str, pa.Array]:
    n = 12
    return {
        "list_int": pa.array([[i] if i % 4 else None for i in range(n)]),
        "struct": pa.array([{"a": i, "b": "x"} if i % 5 else None for i in range(n)]),
        "map": pa.array(
            [[("k", i)] if i % 3 else None for i in range(n)], pa.map_(pa.string(), pa.int64())
        ),
    }


PARITY: dict[str, pa.Array] = {**CASES, **_nested()}
for _name, _build in CATALOGUE.items():
    PARITY[f"cat_{_name}_nonull"] = _build(False)
    PARITY[f"cat_{_name}_null"] = _build(True)


@pytest.mark.parametrize("kind", ["local", "resident"])
@pytest.mark.parametrize("ratio", ["total_equals_sample", "total_is_ten_times_sample"])
@pytest.mark.parametrize("case", sorted(PARITY))
def test_at3_every_type_profiles_as_the_pandas_walk_does(
    case: str, ratio: str, kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arr = PARITY[case]
    table = pa.table({"x": arr, "s": pa.array([f"v{i}" for i in range(len(arr))])})
    sample = len(arr) if ratio == "total_equals_sample" else max(1, len(arr) // 10)
    _same_as_pandas(table, kind, tmp_path, monkeypatch, sample_rows=sample)


@pytest.mark.parametrize("kind", READER_KINDS)
def test_at3_zero_rows(kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    table = pa.table({"x": pa.array([], pa.int64()), "s": pa.array([], pa.string())})
    _same_as_pandas(table, kind, tmp_path, monkeypatch)
    table = pa.Table.from_arrays(
        [PARITY[c][:0] for c in ("int64_null", "date32", "payload_long", "dict_int")],
        names=["a", "b", "c", "d"],
    )
    _same_as_pandas(table, kind, tmp_path, monkeypatch)


@pytest.mark.parametrize("kind", ["local", "s3", "gcs"])
def test_at3_multi_row_group_distinct_count(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """25,000 rows in 4,000-row groups: `count_distinct` over chunks must be exact (F-7)."""
    n = 25_000
    table = pa.table(
        {"x": pa.array([i % 7000 for i in range(n)]), "s": [str(i % 90) for i in range(n)]}
    )
    data = parquet_bytes(table, row_group_size=4_000)
    reader = make_reader(kind, table, data, tmp_path, monkeypatch)
    ours = bounded_profile(reader, kind)
    assert_same_profile(ours, oracle_profile(reader, kind), kind)
    assert _column(ours, "x").distinct_count == len({i % 7000 for i in range(10_000)})


def test_at3_a_resident_table_of_several_chunks_counts_distinct_across_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ARROW-16808: `count_distinct` over several chunks must see them as one column (F-7)."""
    chunks = [
        pa.table({"x": pa.array([i % 7000 for i in range(a, a + 4_000)])})
        for a in (0, 4_000, 8_000)
    ]
    table = pa.concat_tables(chunks)
    assert table.column("x").num_chunks == 3
    reader = make_reader("resident", table, b"", tmp_path, monkeypatch)
    ours = bounded_profile(reader, "resident")
    assert _column(ours, "x").distinct_count == 7000
    assert_same_profile(ours, oracle_profile(reader, "resident"), "resident")


@pytest.mark.parametrize("kind", READER_KINDS)
def test_at3_table_level_fields(kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Known total, sampled flag, candidate key, declared PK and FK, for empty, complete and
    capped samples; two tables profiled in one call share one rng and agree (F-11)."""
    table = pa.table({"id": list(range(40)), "ref": [i % 4 for i in range(40)], "v": ["x"] * 40})
    reader = make_reader(kind, table, parquet_bytes(table), tmp_path, monkeypatch)
    keys = {"declared_pk": frozenset({"id"}), "fk_specs": {"ref": ("p", "id")}}
    complete = bounded_profile(reader, kind, sample_rows=100, **keys)
    capped = bounded_profile(reader, kind, sample_rows=10, **keys)
    for profile, sampled, total in ((complete, False, 40), (capped, True, 40)):
        ident, ref = _column(profile, "id"), _column(profile, "ref")
        assert profile.row_count == total
        assert (ident.row_count, ident.sampled) == (total, sampled)
        assert ident.is_candidate_key_sampled is (not sampled)
        assert (ident.declared_pk, ref.is_fk, ref.fk_target) == (True, True, ("p", "id"))
        assert (_column(profile, "v").is_candidate_key_sampled, ref.declared_pk) == (False, False)
    assert capped.row_count_exact is True
    assert_same_profile(complete, oracle_profile(reader, kind, sample_rows=100, **keys), kind)
    assert_same_profile(capped, oracle_profile(reader, kind, sample_rows=10, **keys), kind)
    rng = random.Random(3)
    first = bounded_profile(reader, kind, sample_rows=10, rng=rng)
    second = bounded_profile(reader, kind, sample_rows=10, rng=rng)
    assert first == second  # the bounded walk draws nothing from rng


def test_at3_plan_cells_compile_the_same_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bounded profile feeds `compile_plan`: the plan for each strategy must equal the plan
    the pandas profile gave (acceptance test 20's four configs)."""
    from datetime import datetime, timezone

    from decoy_engine.contracts.column_shape import NO_SOURCES
    from decoy_engine.plan import compile_plan, plan_to_yaml
    from decoy_engine.profile import Profile
    from tests.native._chunked_entry_support import (
        ENGINE_VERSION,
        TABLE,
        faker_col,
        hash_col,
        make_config,
        passthrough,
        redact,
        truncate,
    )

    table = pa.table(
        {
            "s": pa.array([f"v{i}" for i in range(60)]),
            "x": CASES["payload_nonull"],
            "n": CASES["int64_null"],
        }
    )
    data = parquet_bytes(table)
    reader = make_reader("local", table, data, tmp_path, monkeypatch)

    def wrap(profile: Any) -> Profile:
        return Profile(
            schema_version=1,
            tables=(dataclasses.replace(profile, name=TABLE),),
            relationships=(),
            profiled_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            decoy_engine_version=ENGINE_VERSION,
            profile_seed=None,
        )

    arrow = wrap(bounded_profile(reader, "local", sample_rows=60))
    pandas_ = wrap(oracle_profile(reader, "local", sample_rows=60))
    for strategy in (redact, hash_col, truncate, faker_col):
        config = make_config([strategy("s"), passthrough("x"), passthrough("n")])
        yamls = [
            "\n".join(
                line
                for line in plan_to_yaml(
                    compile_plan(
                        config,
                        p,
                        decoy_engine_version=ENGINE_VERSION,
                        no_profile=True,
                        sources=NO_SOURCES,
                    )
                ).splitlines()
                if "profile_hash" not in line
            )
            for p in (arrow, pandas_)
        ]
        assert yamls[0] == yamls[1], strategy.__name__


# ------------------------------------------------------------------ AT-4 conversion spy


class _Spy:
    """Counts the functions every pandas conversion of an Arrow object passes through.

    `pa.Table.to_pandas` and the other Arrow `to_pandas` methods cannot be patched (immutable
    extension types), so the spy wraps what they reach: `pyarrow.pandas_compat.
    table_to_dataframe` (Table and RecordBatch) and `pd.Series.__init__` (Array and
    ChunkedArray), plus `pd.DataFrame.__init__` and `pd.read_parquet`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pyarrow.pandas_compat as compat

        self.calls: list[str] = []
        spy = self

        def wrap(owner: Any, name: str, label: str) -> None:
            real = getattr(owner, name)

            def counted(*a: Any, **k: Any) -> Any:
                spy.calls.append(label)
                return real(*a, **k)

            monkeypatch.setattr(owner, name, counted)

        wrap(compat, "table_to_dataframe", "table_to_dataframe")
        wrap(pd.Series, "__init__", "Series.__init__")
        wrap(pd.DataFrame, "__init__", "DataFrame.__init__")
        wrap(pd, "read_parquet", "read_parquet")


@pytest.mark.parametrize("with_pandas_metadata", [False, True])
@pytest.mark.parametrize("kind", READER_KINDS)
def test_at4_the_bounded_profile_never_converts_to_pandas(
    kind: str, with_pandas_metadata: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = pd.DataFrame(
        {"a": pd.array([1, None, 3], dtype="Int64"), "b": ["x", "yy", None], "c": [1.5, 2.5, 3.5]}
    )
    table = (
        pa.Table.from_pandas(frame)
        if with_pandas_metadata
        else pa.table({"a": [1, None, 3], "b": ["x", "yy", None], "c": [1.5, 2.5, 3.5]})
    )
    reader = make_reader(kind, table, parquet_bytes(table), tmp_path, monkeypatch)
    spy = _Spy(monkeypatch)
    bounded_profile(reader, kind)
    assert spy.calls == []


def test_at4_control_a_csv_profile_does_convert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decoy_engine.profile._readers import build_profile_source

    path = tmp_path / "t.csv"
    path.write_text("a,b\n1,x\n2,y\n")
    reader = build_profile_source(
        {"type": "file", "format": "csv", "path": str(path), "has_header": True}
    )
    spy = _Spy(monkeypatch)
    _source._profile_one_source(
        reader,
        table_name="t",
        declared_pk_cols=frozenset(),
        fk_specs={},
        sample_rows=10,
        residency="bounded",
        rng=random.Random(0),
        source_format="csv",
    )
    assert spy.calls != []


# ------------------------------------------------------------------ AT-6 sample bounds


@pytest.mark.parametrize("bad_row", [0, 9_999, 10_000, 80_000])
@pytest.mark.parametrize("kind", ["local", "resident"])
def test_at6_only_the_first_sample_rows_are_profiled(
    kind: str, bad_row: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    n = 80_001
    values: list[int | None] = [None if i % 97 == 0 else (i % 6000) * 1000 for i in range(n)]
    values[bad_row] = T_NS_BAD
    table = pa.table({"t": pa.array(values, pa.time64("ns")), "n": pa.array(range(n))})
    reader = make_reader(
        kind, table, parquet_bytes(table, row_group_size=20_000), tmp_path, monkeypatch
    )
    profile = bounded_profile(reader, kind)
    col = _column(profile)
    head = table.column("t").slice(0, 10_000)
    assert (profile.row_count, profile.row_count_exact) == (n, True)
    assert (col.row_count, col.sampled) == (n, True)
    assert col.null_count == head.null_count
    assert col.distinct_count == pc.count_distinct(head, mode="only_valid").as_py()
    assert col.is_candidate_key_sampled is False


# ------------------------------------------------------------------ AT-8 the value that moves


@pytest.mark.parametrize("fixture", ["time64_ns", "date_year_10183"])
def test_at8_a_supplied_table_with_an_unholdable_value_reports_no_text_length(
    fixture: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Frozen move (plan 6.1 a): before this row `_frame_of` cast the column to text and the
    profile reported the text form's `avg_length` and `max_length` (18 for a `time64[ns]`)."""
    bad, _ = FIXTURES[fixture]
    reader = make_reader("resident", bad, b"", tmp_path, monkeypatch)
    col = _column(bounded_profile(reader, "resident"))
    base = _column(oracle_profile(reader, "resident"))  # the text-cast frame, as before this row
    assert (base.avg_length, base.max_length) != (None, None)
    assert (col.avg_length, col.max_length) == (None, None)
    for field in ("dtype", "null_count", "distinct_count", "shape"):
        assert getattr(col, field) == getattr(base, field), field


# ------------------------------------------------------------------ AT-9 cloud readers


@pytest.mark.parametrize("kind", ["s3", "gcs"])
def test_at9_cloud_sample_table_equals_the_local_one(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = pa.Table.from_pandas(
        pd.DataFrame({"t": pd.array([1, None, 3, 4], dtype="Int64"), "e": EMAILS})
    )
    data = parquet_bytes(table)
    cloud = make_reader(kind, table, data, tmp_path, monkeypatch)
    local_dir = tmp_path / "local"
    local_dir.mkdir()
    local = make_reader("local", table, data, local_dir, monkeypatch)
    assert isinstance(local, ParquetFileSource)
    ours, theirs = cloud.sample_table(3), local.sample_table(3)  # type: ignore[attr-defined]
    assert ours.equals(theirs)
    assert ours.schema.equals(theirs.schema, check_metadata=True)
    assert ours.num_rows == 3


@pytest.mark.parametrize("kind", ["s3", "gcs"])
def test_at9_cloud_profile_returns_the_at2_column(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad, _ = FIXTURES["time64_ns"]
    reader = make_reader(kind, bad, parquet_bytes(bad), tmp_path, monkeypatch)
    col = _column(bounded_profile(reader, kind))
    assert (col.dtype, col.null_count, col.distinct_count) == ("object", 0, 4)


def test_at9_head_table_keeps_the_schema_metadata_and_the_row_bound() -> None:
    from decoy_engine.profile.arrow import head_table_from_batches

    frame = pd.DataFrame({"i": pd.array([1, None, 3, 4, 5], dtype="Int64")})
    table = pa.Table.from_pandas(frame)
    batches = table.to_batches(max_chunksize=2)
    out = head_table_from_batches(iter(batches), 3, table.schema)
    assert out.num_rows == 3
    assert out.schema.metadata == table.schema.metadata
    empty = head_table_from_batches(iter([]), 3, table.schema)
    assert empty.num_rows == 0 and empty.schema.metadata == table.schema.metadata
    for start in range(0, 5):  # a short read is only ever the end of the source
        assert head_table_from_batches(iter(batches), start + 1, table.schema).num_rows == min(
            start + 1, 5
        )


# ------------------------------------------------------------------ duplicate names (AT-5 cells)


def test_at5_duplicate_names_share_one_value_free_message() -> None:
    from decoy_engine.execution._guards import refuse_duplicate_field_names
    from decoy_engine.execution._transforms import TransformError
    from decoy_engine.profile._walk import walk_dataframe
    from decoy_engine.profile.arrow import walk_arrow_table

    text = "table 't' has 1 duplicated field name(s)"
    table = pa.Table.from_arrays([pa.array([1]), pa.array([2])], names=["secret_a", "secret_a"])
    keys: dict[str, Any] = {"declared_pk_cols": frozenset(), "fk_specs": {}}
    with pytest.raises(ValueError, match=r"^table 't' has 1 duplicated field name\(s\)$"):
        walk_arrow_table(table, table_name="t", total_row_count=1, source_format="table", **keys)
    frame = pd.DataFrame([[1, 2]], columns=["secret_a", "secret_a"])
    with pytest.raises(ValueError) as caught:
        walk_dataframe(frame, table_name="t", sample_rows=None, rng=random.Random(0), **keys)
    assert str(caught.value) == text
    with pytest.raises(TransformError) as guard:
        refuse_duplicate_field_names("t", ["secret_a", "secret_a"])
    assert (
        guard.value.message == text if hasattr(guard.value, "message") else text in str(guard.value)
    )
    assert "secret_a" not in text


# ------------------------------------------------------------------ the metadata is decoded once


def test_bounded_walk_decodes_metadata_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from decoy_engine._pandas_meta import _columns
    from decoy_engine.profile.arrow import walk_arrow_table

    frame = pd.DataFrame(
        {f"c{i}": pd.array([1, None, 3], dtype="Int8") for i in range(8)}
        | {"s": pd.array(["a", None, "c"], dtype="string")},
        index=pd.Index([10, 20, 30], name="k"),
    )
    table = pa.Table.from_pandas(frame)
    real = _columns.decode_pandas_blob
    calls: list[int] = []

    def counting(raw: Any) -> Any:
        calls.append(1)
        return real(raw)

    monkeypatch.setattr(_columns, "decode_pandas_blob", counting)
    profile = walk_arrow_table(
        table,
        table_name="t",
        declared_pk_cols=frozenset(),
        fk_specs={},
        total_row_count=3,
        source_format="table",
    )
    assert [c.name for c in profile.columns][:2] == ["c0", "c1"]
    assert "k" not in [c.name for c in profile.columns]
    assert calls == [1]
