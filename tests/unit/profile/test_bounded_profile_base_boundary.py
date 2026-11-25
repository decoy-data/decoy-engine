"""PREFLIGHT-ARROW-PROFILE S1b: the bounded profile keeps base results and reports value-free errors.

AT-3b/3c (pandas metadata), AT-5/AT-12 (the public error), AT-8 (a resident table with a stored
index), AT-12f (the float option), AT-13/14 (text and dictionary columns). The reference is built
in `_arrow_support` from pyarrow and pandas alone. Do not edit it to pass a cell.
"""

from __future__ import annotations

import decimal
import json
import os
import traceback
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine import fileaccess, reasons
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.fileaccess import FileAccessDenied, FileRole, Root, RootedFileAccess
from decoy_engine.fileaccess._openat2 import openat2_usable
from tests.unit.profile._arrow_support import (
    SAFE_FAILURE,
    assert_matches_base,
    bounded_profile,
    make_reader,
    parquet_bytes,
)

MARKER = "123456789"


def _column(profile: Any, name: str) -> Any:
    return next(c for c in profile.columns if c.name == name)


def _formatted(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc)) + repr(exc) + str(exc)


# ------------------------------------------------------------------ AT-5: the public error


def _marker_table() -> pa.Table:
    return pa.table(
        {
            "t": pa.array([int(MARKER)], pa.time64("ns")),
            "dec": pa.array([decimal.Decimal("1.5")]),
        }
    )


def test_at5_a_failed_recovery_reports_a_closed_label_and_no_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = _marker_table()
    reader = make_reader("local", table, parquet_bytes(table), tmp_path, monkeypatch)
    with pytest.raises(ValueError) as caught:
        bounded_profile(reader, "local")
    assert str(caught.value) == "bounded source profile failed (Exception)"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert MARKER not in _formatted(caught.value)


def test_at5_capacity_hides_the_value_and_keeps_the_code(tmp_path: Path) -> None:
    import pyarrow.parquet as pq

    from decoy_engine.execution.capacity import estimate_job_capacity

    path = tmp_path / "t.parquet"
    pq.write_table(_marker_table(), path)
    config = {
        "version": 2,
        "global_settings": {"job_name": "j", "seed": 7},
        "sources": {"t": {"type": "file", "path": str(path), "format": "parquet"}},
        "targets": {
            "t": {"type": "file", "path": str(tmp_path / "o.parquet"), "format": "parquet"}
        },
        "tables": [
            {
                "name": "t",
                "columns": [
                    {"name": "t", "strategy": "passthrough"},
                    {"name": "dec", "strategy": "passthrough"},
                ],
            }
        ],
    }
    with pytest.raises(ExecutionError) as caught:
        estimate_job_capacity(config, tmp_path)
    assert caught.value.code == "capacity_source_unprofilable"
    assert MARKER not in _formatted(caught.value)
    assert "bounded source profile failed (Exception)" in str(caught.value)


class _RaisingReader:
    def __init__(self, inner: Any, exc: BaseException) -> None:
        self._inner, self._exc = inner, exc

    def row_count(self) -> Any:
        return self._inner.row_count()

    def schema(self) -> pa.Schema:
        return self._inner.schema()

    def sample_table(self, sample_rows: int) -> Any:
        raise self._exc

    def sample_frame(self, sample_rows: int) -> Any:  # pragma: no cover - never read
        raise AssertionError("the bounded profile reads the sample as a table")


def _reader_raising(exc: BaseException, tmp_path: Path, mp: pytest.MonkeyPatch) -> Any:
    table = pa.table({"a": [1, 2]})
    return _RaisingReader(make_reader("local", table, parquet_bytes(table), tmp_path, mp), exc)


@pytest.mark.parametrize(
    ("exc", "label"),
    [
        (KeyError(MARKER), "KeyError"),
        (TypeError(MARKER), "TypeError"),
        (OverflowError(MARKER), "OverflowError"),
        (pa.ArrowInvalid(MARKER), "Exception"),
        (ValueError(f"table 't' has 1 duplicated field name(s) {MARKER}"), "ValueError"),
    ],
)
def test_at5_every_ordinary_failure_is_a_label_only(
    exc: BaseException, label: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _reader_raising(exc, tmp_path, monkeypatch)
    try:
        bounded_profile(reader, "local")
    except ValueError as caught:
        assert str(caught) == f"bounded source profile failed ({label})"
        assert caught.__cause__ is None and caught.__context__ is None
        assert MARKER not in _formatted(caught)
    else:  # pragma: no cover
        pytest.fail("no error")


def test_at5_a_coded_engine_failure_keeps_its_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coded = ExecutionError(code=reasons.runtime.FULL_FRAME_VALUE_UNREPRESENTABLE, message="m")
    reader = _reader_raising(coded, tmp_path, monkeypatch)
    with pytest.raises(ExecutionError) as caught:
        bounded_profile(reader, "local")
    assert caught.value is coded


@pytest.fixture
def rooted(tmp_path: Path) -> Iterator[RootedFileAccess]:
    if not openat2_usable():
        pytest.skip("rooted file access needs Linux openat2")
    root = tmp_path / "root"
    root.mkdir()
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    roots = [Root("main", fd, frozenset({FileRole.SOURCE}), frozenset({"read", "stat"}))]
    try:
        yield RootedFileAccess(roots)
    finally:
        os.close(fd)


def test_at5_a_file_access_decision_keeps_its_type_under_a_strict_policy(
    rooted: RootedFileAccess, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    denied = FileAccessDenied("field")
    reader = _reader_raising(denied, tmp_path, monkeypatch)
    with fileaccess.scope(rooted), pytest.raises(FileAccessDenied) as caught:
        bounded_profile(reader, "local")
    assert caught.value is denied


def test_at5_a_real_duplicate_keeps_the_shared_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = pa.Table.from_arrays([pa.array([1]), pa.array([2])], names=["a", "a"])
    for kind in ("local", "resident"):
        reader = make_reader(kind, table, parquet_bytes(table), tmp_path, monkeypatch)
        with pytest.raises(ValueError) as caught:
            bounded_profile(reader, kind)
        assert str(caught.value) == "table 't' has 1 duplicated field name(s)"


# ------------------------------------------------------------------ AT-8: a stored index


def test_at8_a_resident_table_with_a_stored_index_and_a_bad_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = pd.DataFrame(
        {"v": pd.array([2**53, 2**53 + 1, None], dtype="Int64"), "k": [1, 2, 3]}
    ).set_index("k")
    base = pa.Table.from_pandas(frame)
    bad = pa.table(
        {
            "v": base.column("v"),
            "t": pa.array([1, 2000, 3000], pa.time64("ns")),
            "k": base.column("k"),
        }
    ).replace_schema_metadata(base.schema.metadata)
    good = bad.set_column(1, "t", pa.array([1000, 2000, 3000], pa.time64("ns")))
    assert_matches_base(bad, "resident", tmp_path, monkeypatch)
    profile = bounded_profile(make_reader("resident", bad, b"", tmp_path, monkeypatch), "resident")
    assert [c.name for c in profile.columns] == ["v", "t", "k"]
    v, t, k = (_column(profile, n) for n in "vtk")
    assert (v.dtype, v.null_count, v.distinct_count) == ("float64", 1, 1)
    assert (t.avg_length, t.max_length, k.distinct_count) == (18.0, 18, 3)
    twin = bounded_profile(make_reader("resident", good, b"", tmp_path, monkeypatch), "resident")
    assert [c.name for c in twin.columns] == ["v", "t"]  # the stored index stays hidden
    assert (_column(twin, "v").dtype, _column(twin, "v").distinct_count) == ("Int64", 2)
    assert_matches_base(good, "resident", tmp_path, monkeypatch)


# ------------------------------------------------------------------ AT-3b / AT-3c: metadata


def _pandas_frame() -> pd.DataFrame:
    n = 6
    return pd.DataFrame(
        {
            "i64": pd.array([1, None, 3, 4, 5, 6], dtype="Int64"),
            "f64": pd.array([1.5, None, 3.5, 4.5, 5.5, 6.5], dtype="Float64"),
            "b": pd.array([True, None, False, True, False, True], dtype="boolean"),
            "s": pd.array(["a", None, "c", "d", "e", "f"], dtype="string"),
            "sp": pd.array(["a", None, "c", "d", "e", "f"], dtype="string[pyarrow]"),
            "cat": pd.Categorical(["a", "b", "a", None, "b", "a"]),
            "tz": pd.date_range("2024-01-01", periods=n, tz="UTC"),
            "dt": pd.date_range("2024-01-01", periods=n),
            "plain": list("abcdef"),
        }
    )


@pytest.mark.parametrize("index", ["range", "named", "filtered"])
@pytest.mark.parametrize("kind", ["local", "resident"])
def test_at3b_pandas_written_tables_profile_as_base_does(
    index: str, kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = _pandas_frame()
    if index == "named":
        frame.index = pd.Index(list("uvwxyz"), name="key")
    elif index == "filtered":
        frame = frame[frame["plain"] != "b"]
    table = pa.Table.from_pandas(frame)
    assert assert_matches_base(table, kind, tmp_path, monkeypatch, sample_rows=4)
    assert assert_matches_base(table.slice(0, 0), kind, tmp_path, monkeypatch)


@pytest.mark.parametrize("dtype", ["string[pyarrow]", "arrow_string"])
def test_at3b_both_string_footer_pairs_use_the_base_conversion(
    dtype: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrow_dtype = pd.ArrowDtype(pa.string()) if dtype == "arrow_string" else dtype
    frame = pd.DataFrame({"s": pd.array(["a", None, "b"], dtype=arrow_dtype)})
    table = pa.Table.from_pandas(frame)
    for kind in ("local", "resident"):
        assert assert_matches_base(table, kind, tmp_path, monkeypatch)


def _with_blob(table: pa.Table, edit: Any) -> pa.Table:
    blob = json.loads(table.schema.metadata[b"pandas"])
    edit(blob)
    return table.replace_schema_metadata({b"pandas": json.dumps(blob).encode()})


@pytest.mark.parametrize("kind", ["local", "resident"])
def test_at3c_a_restored_label_and_a_missing_required_key(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clean = pa.Table.from_pandas(pd.DataFrame({"01": [1, 2]}))

    def relabel(blob: dict[str, Any]) -> None:
        blob["column_indexes"][0]["numpy_type"] = "int64"

    assert [c.name for c in _profile(clean, kind, tmp_path, monkeypatch).columns] == ["01"]
    relabelled = _with_blob(clean, relabel)
    assert [c.name for c in _profile(relabelled, kind, tmp_path, monkeypatch).columns] == ["1"]
    assert_matches_base(relabelled, kind, tmp_path, monkeypatch)
    damaged = _with_blob(clean, lambda blob: blob.pop("index_columns"))
    with pytest.raises(ValueError, match=SAFE_FAILURE):
        _profile(damaged, kind, tmp_path, monkeypatch)
    assert_matches_base(damaged, kind, tmp_path, monkeypatch)


def _profile(table: pa.Table, kind: str, tmp_path: Path, mp: pytest.MonkeyPatch) -> Any:
    data = parquet_bytes(table) if kind != "resident" else b""
    return bounded_profile(make_reader(kind, table, data, tmp_path, mp), kind)


def test_at3c_pandas_metadata_never_enters_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import datetime
    import io

    import pyarrow.parquet as pq

    twin = pa.Table.from_pandas(
        pd.DataFrame(
            {
                "t": [datetime.time(0, 0, i) for i in range(4)],
                "e": ["a@x.test", "b@x.test", "c@x.test", "d@x.test"],
            }
        ),
        preserve_index=False,
    )
    twin = twin.set_column(0, "t", twin.column("t").cast(pa.time64("ns")))
    bad = twin.set_column(
        0, "t", pa.array([0, 1000, 2000, 3_600_987_654_321], pa.time64("ns"))
    ).replace_schema_metadata(twin.schema.metadata)
    assert _profile(twin, "local", tmp_path, monkeypatch).columns  # the twin converts whole
    read_back = pq.ParquetFile(io.BytesIO(parquet_bytes(bad))).schema_arrow
    assert b"pandas" in (read_back.metadata or {})
    with pytest.raises(ValueError, match=SAFE_FAILURE):
        _profile(bad, "local", tmp_path, monkeypatch)


# ------------------------------------------------------------------ AT-12: period and float


def _canary_period() -> pa.Table:
    from pandas.core.arrays.arrow.extension_types import ArrowPeriodType

    storage = pa.array([1, 2], pa.int64())
    ext = pa.ExtensionArray.from_storage(ArrowPeriodType("BAD-CANARY"), storage)
    return pa.table({"p": ext})


def test_at12_a_period_with_a_bad_frequency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = _canary_period()
    resident = bounded_profile(
        make_reader("resident", table, b"", tmp_path, monkeypatch), "resident"
    )
    p = _column(resident, "p")
    assert (p.dtype, p.distinct_count, p.avg_length, p.max_length) == ("object", 2, 1.0, 1)
    assert_matches_base(table, "resident", tmp_path, monkeypatch)
    try:
        data = parquet_bytes(table)
    except (pa.ArrowNotImplementedError, pa.ArrowInvalid, pa.ArrowTypeError):
        pytest.skip("this stack cannot write the extension type to Parquet")
    reader = make_reader("local", table, data, tmp_path, monkeypatch)
    with pytest.raises(ValueError) as caught:
        bounded_profile(reader, "local")
    assert str(caught.value) == "bounded source profile failed (ValueError)"
    assert "BAD-CANARY" not in _formatted(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.parametrize("use_inf_as_na", [True, False])
@pytest.mark.parametrize("kind", ["local", "resident"])
def test_at12f_the_inf_option_is_read_where_base_read_it(
    use_inf_as_na: bool, kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = pa.table({"x": pa.array([float("inf"), 1.0])})
    with pd.option_context("mode.use_inf_as_na", use_inf_as_na):
        assert assert_matches_base(table, kind, tmp_path, monkeypatch)
        x = _column(_profile(table, kind, tmp_path, monkeypatch), "x")
    assert (x.null_count, x.distinct_count) == ((1, 1) if use_inf_as_na else (0, 2))
    assert x.is_candidate_key_sampled is (not use_inf_as_na)


def test_a_complete_nonempty_repeated_column_is_not_a_candidate_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    x = _column(_profile(pa.table({"x": [7, 7]}), "local", tmp_path, monkeypatch), "x")
    assert (x.distinct_count, x.is_candidate_key_sampled) == (1, False)


# ------------------------------------------------------------------ AT-13 / AT-14


def _dictionary(index: pa.DataType, values: pa.Array, indices: list[int | None]) -> pa.Array:
    return pa.DictionaryArray.from_arrays(pa.array(indices, index), values)


DICTIONARIES = {
    f"dict_{idx}": _dictionary(getattr(pa, idx)(), pa.array(["a", "b", "c"]), [0, 1, None, 2, 0])
    for idx in ("int8", "int16", "int32", "int64", "uint8")
}
DICTIONARIES["dict_large_text"] = _dictionary(
    pa.int32(), pa.array(["a", "b"], pa.large_string()), [0, 1, None, 1, 0]
)
DICTIONARIES["dict_int_values"] = _dictionary(pa.int32(), pa.array([10, 20]), [0, 1, None, 1, 0])
DICTIONARIES["dict_repeated"] = _dictionary(pa.int32(), pa.array(["a", "a", "b"]), [0, 1, 2, 0, 1])
TEXT = {
    "string": pa.array(["a", "b", "c", "d", "e"]),
    "string_null": pa.array(["a", None, "c", "d", "e"]),
    "large_string": pa.array(["a", "b", None, "d", "e"], pa.large_string()),
}


@pytest.mark.parametrize("kind", ["local", "resident"])
@pytest.mark.parametrize("case", sorted({**DICTIONARIES, **TEXT}))
def test_at13_text_and_dictionary_columns_profile_as_base_does(
    case: str, kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = pa.table({"x": {**DICTIONARIES, **TEXT}[case]})
    assert_matches_base(table, kind, tmp_path, monkeypatch)
    try:
        inferring = pd.option_context("future.infer_string", True)
        inferring.__enter__()
    except (KeyError, ValueError, pd.errors.OptionError):  # pragma: no cover - option absent
        return
    try:
        assert_matches_base(table, kind, tmp_path, monkeypatch)
    finally:
        inferring.__exit__(None, None, None)


def test_at14_a_resident_dictionary_in_two_chunks_uses_the_base_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _dictionary(pa.int32(), pa.array(["a", None]), [0, 1])
    second = _dictionary(pa.int32(), pa.array(["c", "d"]), [1, 0])
    table = pa.table({"x": pa.chunked_array([first, second])})
    assert assert_matches_base(table, "resident", tmp_path, monkeypatch)
    x = _column(_profile(table, "resident", tmp_path, monkeypatch), "x")
    assert (x.dtype, x.null_count, x.distinct_count) == ("object", 1, 3)
