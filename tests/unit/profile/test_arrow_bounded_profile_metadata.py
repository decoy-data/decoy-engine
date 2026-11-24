"""PREFLIGHT-ARROW-PROFILE S1b, AT-3b and AT-3c: the bounded Arrow walk reads the pandas schema
metadata the way `to_pandas` did, and a damaged blob never stops it or moves a dtype.

AT-3b: parity with the pandas walk over the dtype corpus, with and without nulls, three index
kinds, full and zero rows, through local Parquet, S3, GCS and a resident table. AT-3c: the
blob is damaged after writing (malformed, renamed, dropped, reordered); each cell compares the
profile with a control built without the damage, never with pandas reading the damaged table.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from tests.unit.profile._arrow_support import (
    READER_KINDS,
    assert_same_profile,
    bounded_profile,
    make_reader,
    oracle_profile,
    parquet_bytes,
)

ROWS = 12


def _cycle(values: list[Any]) -> list[Any]:
    return [values[i % len(values)] for i in range(ROWS)]


def _dtype_columns() -> dict[str, Any]:
    """One column per dtype of the Probe E corpus, each with (`_n`) and without a null."""
    cols: dict[str, Any] = {}

    def add(name: str, make: Callable[[list[Any]], Any], values: list[Any]) -> None:
        cols[f"{name}"] = make(_cycle(values))
        cols[f"{name}_n"] = make([None if i % 5 == 1 else v for i, v in enumerate(_cycle(values))])

    for w in (8, 16, 32, 64):
        add(f"Int{w}", lambda v, w=w: pd.array(v, dtype=f"Int{w}"), [1, 2, 3, 2])
        add(f"UInt{w}", lambda v, w=w: pd.array(v, dtype=f"UInt{w}"), [1, 2, 3, 2])
    add("boolean", lambda v: pd.array(v, dtype="boolean"), [True, False, True])
    add("string", lambda v: pd.array(v, dtype="string"), ["a", "bcd", "a", "efghij"])
    add("string_pa", lambda v: pd.array(v, dtype="string[pyarrow]"), ["a", "bcd", "a", "efghij"])
    add("Float32", lambda v: pd.array(v, dtype="Float32"), [1.5, 2.5, 1.5])
    add("Float64", lambda v: pd.array(v, dtype="Float64"), [1.5, 2.5, 1.5, 0.0])
    add("cat", lambda v: pd.Categorical(v), ["a", "b", "a", "c"])
    add(
        "cat_ordered",
        lambda v: pd.Categorical(v, categories=["a", "b", "c"], ordered=True),
        ["a", "b"],
    )
    add(
        "tz",
        lambda v: pd.to_datetime(v).tz_localize("UTC"),
        ["2020-01-01", "2021-06-01", "2020-01-01"],
    )
    add("period", lambda v: pd.PeriodIndex(v, freq="M"), ["2020-01", "2020-02", "2020-01"])
    add(
        "interval",
        lambda v: pd.arrays.IntervalArray.from_tuples(v),
        [(0, 1), (1, 2), (0, 1)],
    )
    add("plain_int", lambda v: np.array([x if x is not None else 0 for x in v]), [1, 2, 3])
    add(
        "plain_float",
        lambda v: np.array([x if x is not None else np.nan for x in v], dtype=float),
        [1.5, 2.5],
    )
    add("plain_str", lambda v: np.array(v, dtype=object), ["p", "qq", "p"])
    return cols


def _frame(index: str, rows: int) -> pd.DataFrame:
    cols = _dtype_columns()
    df = pd.DataFrame(cols)
    if index == "named":
        df.index = pd.Index([f"k{i}" for i in range(ROWS)], name="key")
    elif index == "filtered":
        df = df.iloc[[i for i in range(ROWS) if i % 3 != 0]]
    return df.iloc[:rows] if rows == 0 else df


def _nan_in_masked_float() -> pd.DataFrame:
    """A `Float64` holding a NaN that is not NA: pandas keeps it as a value."""
    data = np.array([1.0, np.nan, 2.0, np.nan])
    mask = np.array([False, False, True, False])
    return pd.DataFrame({"f": pd.arrays.FloatingArray(data, mask), "s": ["a", "b", "c", "d"]})


def _readers(frame: pd.DataFrame, kind: str, tmp_path: Path, mp: pytest.MonkeyPatch) -> Any:
    buf = parquet_bytes_of(frame)
    table = pa.Table.from_pandas(frame)
    return make_reader(kind, table, buf, tmp_path, mp)


def parquet_bytes_of(frame: pd.DataFrame) -> bytes:
    import io

    buf = io.BytesIO()
    frame.to_parquet(buf)
    return buf.getvalue()


@pytest.mark.parametrize("sample_rows", [100, 4])
@pytest.mark.parametrize("rows", [ROWS, 0])
@pytest.mark.parametrize("index", ["range", "named", "filtered"])
@pytest.mark.parametrize("kind", READER_KINDS)
def test_at3b_the_dtype_corpus_profiles_as_the_pandas_walk_does(
    kind: str,
    index: str,
    rows: int,
    sample_rows: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _readers(_frame(index, rows), kind, tmp_path, monkeypatch)
    ours = bounded_profile(reader, kind, sample_rows=sample_rows)
    assert_same_profile(ours, oracle_profile(reader, kind, sample_rows=sample_rows), kind)
    assert "key" not in [c.name for c in ours.columns]
    assert not any(c.name.startswith("__index_level") for c in ours.columns)


@pytest.mark.parametrize("kind", READER_KINDS)
def test_at3b_a_nan_in_a_masked_float_is_a_value(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _readers(_nan_in_masked_float(), kind, tmp_path, monkeypatch)
    ours = bounded_profile(reader, kind)
    assert_same_profile(ours, oracle_profile(reader, kind), kind)
    f = next(c for c in ours.columns if c.name == "f")
    assert (f.dtype, f.null_count, f.distinct_count) == ("Float64", 1, 2)


@pytest.mark.parametrize("kind", READER_KINDS)
def test_at3b_plan_checks_over_a_null_bearing_nullable_int_are_unchanged(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`check_null_bearing_int_unsupported` and the `when:` numeric check read `dtype`: a
    nullable `Int64` with a null must stay `Int64`, not widen to `float64`."""
    frame = pd.DataFrame({"i": pd.array([1, None, 3], dtype="Int64"), "s": ["a", "b", "c"]})
    reader = _readers(frame, kind, tmp_path, monkeypatch)
    col = next(c for c in bounded_profile(reader, kind).columns if c.name == "i")
    assert (col.dtype, col.null_count) == ("Int64", 1)


def _arrow_dtype_frame() -> pd.DataFrame:
    def arr(values: list[Any], t: pa.DataType) -> Any:
        return pd.array(values, dtype=pd.ArrowDtype(t))

    return pd.DataFrame(
        {
            "i64": arr([1, None, 3, 1, 2], pa.int64()),
            "f64": arr([1.5, None, 2.5, 1.5, 0.0], pa.float64()),
            "bool": arr([True, None, False, True, True], pa.bool_()),
            "str": arr(["a", None, "bcd", "a", "ef"], pa.string()),
            "lstr": arr(["a", None, "bcd", "a", "ef"], pa.large_string()),
            "bin": arr([b"a", None, b"bcd", b"a", b"ef"], pa.binary()),
            "d32": arr([1, None, 3, 1, 2], pa.date32()),
            "ts": arr([1, None, 3, 1, 2], pa.timestamp("ns")),
        }
    )


@pytest.mark.parametrize("kind", ["local", "resident"])
def test_arrowdtype_metadata_matches_pandas(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _readers(_arrow_dtype_frame(), kind, tmp_path, monkeypatch)
    ours = bounded_profile(reader, kind)
    assert_same_profile(ours, oracle_profile(reader, kind), kind)
    assert next(c for c in ours.columns if c.name == "i64").dtype == "int64[pyarrow]"


# ------------------------------------------------------------------ AT-3c damaged metadata


def _blob(columns: list[Any], index: list[Any] | None = None) -> bytes:
    return json.dumps(
        {"index_columns": index or [], "column_indexes": [], "columns": columns, "creator": {}}
    ).encode()


def _entry(field: str, kind: str, numpy: str, name: Any = ...) -> dict[str, Any]:
    return {
        "name": field if name is ... else name,
        "field_name": field,
        "pandas_type": kind,
        "numpy_type": numpy,
        "metadata": None,
    }


NULLED = [1, None, 3, None, 5]


def _with(table: pa.Table, raw: bytes | None) -> pa.Table:
    return table.replace_schema_metadata(None if raw is None else {b"pandas": raw})


def _plain_control(table: pa.Table) -> pa.Table:
    """No metadata at all: the ordinary Arrow profile of every field."""
    return table.replace_schema_metadata(None)


def _cells() -> dict[str, tuple[pa.Table, Any, Callable[[pa.Table], pa.Table]]]:
    """cell id -> (damaged table, expected column facts, control builder).

    Expected facts are `(name, dtype, null_count, distinct_count)` in physical order."""
    two = pa.table({"a": pa.array(NULLED, pa.int8()), "b": pa.array(NULLED, pa.int8())})
    cells: dict[str, tuple[pa.Table, Any, Callable[[pa.Table], pa.Table]]] = {}
    plain = [("a", "float64", 2, 3), ("b", "float64", 2, 3)]
    for label, raw in {
        "missing": None,
        "bad_utf8": b"\xff\xfe{",
        "truncated": b'{"columns": [{"field_name": "a"',
        "deep": b"[" * 100_000 + b"]" * 100_000,
        "scalar_root": b"7",
        "list_root": b"[1, 2]",
        "duplicate_keys": b'{"columns": [], "columns": []}',
    }.items():
        cells[f"malformed-blob-{label}"] = (_with(two, raw), plain, _plain_control)
    for label, blob in {
        "columns_null": json.dumps({"index_columns": [], "columns": None}).encode(),
        "columns_object": json.dumps({"index_columns": [], "columns": {"a": 1}}).encode(),
        "index_scalar_string": json.dumps({"index_columns": "a", "columns": []}).encode(),
    }.items():
        cells[f"malformed-section-{label}"] = (_with(two, blob), plain, _plain_control)
    # A valid nullable sibling survives hostile neighbour entries; a hint that is forged, unknown,
    # of the wrong type or ambiguous (two entries for one field) has no effect.
    four = pa.table({n: pa.array(NULLED, pa.int8()) for n in "abcd"})
    good = _entry("b", "int8", "Int8")
    hostile = [
        "junk",
        3,
        None,
        {"field_name": 7, "name": 7, "pandas_type": "int8", "numpy_type": "Int8"},
        {"field_name": ["a"], "pandas_type": "int8", "numpy_type": "Int8"},
        _entry("a", "unicode", "string"),  # forged: a string hint on an integer field
        _entry("c", "int8", "CANARY_9f3"),
        _entry("c2", "int8", ["Int8"]),
        _entry("d", "int8", "Int8"),  # two entries for `d` that disagree
        _entry("d", "int8", "int8"),
        good,
    ]
    expected = [
        ("a", "float64", 2, 3),
        ("b", "Int8", 2, 3),
        ("c", "float64", 2, 3),
        ("d", "float64", 2, 3),
    ]
    cells["malformed-entry"] = (
        _with(four, _blob(hostile, [{"kind": "range", "start": 0}, 5, None])),
        expected,
        lambda t: _with(t, _blob([good])),
    )
    return cells


@pytest.mark.parametrize("kind", READER_KINDS)
@pytest.mark.parametrize("cell", sorted(_cells()))
def test_at3c_a_damaged_blob_never_changes_a_profile(
    cell: str, kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    damaged, expected, control = _cells()[cell]
    reader = make_reader(kind, damaged, parquet_bytes(damaged), tmp_path, monkeypatch)
    ours = bounded_profile(reader, kind)
    assert [(c.name, c.dtype, c.null_count, c.distinct_count) for c in ours.columns] == expected
    assert "CANARY_9f3" not in repr(ours)
    ctl = control(damaged)
    ctl_dir = tmp_path / "ctl"
    ctl_dir.mkdir()
    ctl_reader = make_reader(kind, ctl, parquet_bytes(ctl), ctl_dir, monkeypatch)
    assert bounded_profile(ctl_reader, kind) == ours


def _base_table() -> tuple[pa.Table, bytes]:
    """`n` nullable Int8, `k` a stored index, `m` nullable Int8, `p` plain int8 with nulls."""
    table = pa.table(
        {
            "n": pa.array(NULLED, pa.int8()),
            "k": pa.array([10, 20, 30, 40, 50], pa.int64()),
            "m": pa.array(NULLED, pa.int8()),
            "p": pa.array(NULLED, pa.int8()),
        }
    )
    raw = _blob(
        [
            _entry("n", "int8", "Int8"),
            _entry("k", "int64", "int64", name="idx"),
            _entry("m", "int8", "Int8"),
            _entry("p", "int8", "int8"),
        ],
        index=["k"],
    )
    return table, raw


@pytest.mark.parametrize("kind", READER_KINDS)
def test_at3c_renamed_fields_are_ordinary_arrow_and_the_stale_entry_is_dropped(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table, raw = _base_table()
    stale = _blob(
        [
            _entry("n", "int8", "Int8", name="new_n"),  # the display name now equals the new field
            _entry("k", "int64", "int64", name="new_k"),
            _entry("m", "int8", "Int8"),
            _entry("p", "int8", "int8"),
        ],
        index=["k"],
    )
    renamed = _with(table.rename_columns(["new_n", "new_k", "m", "p"]), stale)
    reader = make_reader(kind, renamed, parquet_bytes(renamed), tmp_path, monkeypatch)
    got = [(c.name, c.dtype) for c in bounded_profile(reader, kind).columns]
    # `new_n` and `new_k` have no hint of their own: ordinary Arrow profiles. `m` keeps its hint.
    assert got == [("new_n", "float64"), ("new_k", "int64"), ("m", "Int8"), ("p", "float64")]


@pytest.mark.parametrize("kind", READER_KINDS)
def test_at3c_dropped_fields_leave_their_neighbours_alone(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table, raw = _base_table()
    dropped = _with(table.drop_columns(["n", "k"]), raw)
    reader = make_reader(kind, dropped, parquet_bytes(dropped), tmp_path, monkeypatch)
    ours = bounded_profile(reader, kind)
    assert [(c.name, c.dtype, c.null_count, c.distinct_count) for c in ours.columns] == [
        ("m", "Int8", 2, 3),
        ("p", "float64", 2, 3),
    ]


@pytest.mark.parametrize("kind", READER_KINDS)
def test_at3c_reordered_fields_follow_their_names(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table, raw = _base_table()
    reordered = _with(table.select(["p", "m"]), raw)  # plain first, nullable second; index omitted
    reader = make_reader(kind, reordered, parquet_bytes(reordered), tmp_path, monkeypatch)
    ours = bounded_profile(reader, kind)
    assert [(c.name, c.dtype) for c in ours.columns] == [("p", "float64"), ("m", "Int8")]
    swapped = _with(table.select(["m", "k", "p"]), raw)  # the stored index moves between them
    reader = make_reader(kind, swapped, parquet_bytes(swapped), tmp_path, monkeypatch)
    assert [(c.name, c.dtype) for c in bounded_profile(reader, kind).columns] == [
        ("m", "Int8"),
        ("p", "float64"),
    ]


@pytest.mark.parametrize("kind", READER_KINDS)
def test_at3c_a_string_index_name_that_is_not_a_field_hides_nothing(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table, _ = _base_table()
    raw = _blob([_entry("m", "int8", "Int8")], index=["nope", {"kind": "range"}, 3])
    tbl = _with(table.select(["m", "p"]), raw)
    reader = make_reader(kind, tbl, parquet_bytes(tbl), tmp_path, monkeypatch)
    assert [c.name for c in bounded_profile(reader, kind).columns] == ["m", "p"]
