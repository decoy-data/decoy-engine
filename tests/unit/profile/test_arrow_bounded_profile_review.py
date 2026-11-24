"""PREFLIGHT-ARROW-PROFILE S1b, review round 1: seven cells where the bounded Arrow walk must
give the profile the pandas walk gives. Each cell is a Codex reproduction; the oracle is
`walk_dataframe` over `sample_frame`, unchanged."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine._pandas_meta import _columns
from decoy_engine.plan import _checks
from decoy_engine.plan._errors import PlanCompileError
from tests.unit.profile._arrow_support import (
    READER_KINDS,
    assert_same_profile,
    bounded_profile,
    make_reader,
    oracle_profile,
    parquet_bytes,
)


def _col(profile: Any, name: str) -> Any:
    return next(c for c in profile.columns if c.name == name)


def _legacy_blob(table: pa.Table, *, drop: tuple[str, ...]) -> pa.Table:
    meta = json.loads(table.schema.metadata[b"pandas"])
    for entry in meta["columns"]:
        for key in drop:
            entry.pop(key, None)
    return table.replace_schema_metadata({b"pandas": json.dumps(meta).encode()})


def _resident_same(table: pa.Table, tmp_path: Path, mp: pytest.MonkeyPatch) -> Any:
    reader = make_reader("resident", table, b"", tmp_path, mp)
    ours = bounded_profile(reader, "resident")
    assert_same_profile(ours, oracle_profile(reader, "resident"), "resident")
    return ours


# 1. chunked dictionaries with disjoint int8 dictionaries


def _dict_chunk(lo: int) -> pa.Array:
    return pa.DictionaryArray.from_arrays(
        pa.array(list(range(100)) * 2, pa.int8()), pa.array([f"v{i}" for i in range(lo, lo + 100)])
    )


@pytest.mark.parametrize("kind", ["resident"])
def test_disjoint_int8_dictionary_chunks_count_every_category(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = pa.table({"c": pa.chunked_array([_dict_chunk(0), _dict_chunk(100)])})
    ours = _resident_same(table, tmp_path, monkeypatch)
    assert _col(ours, "c").distinct_count == 200


# 2. legacy entry: `name` and no `field_name`


@pytest.mark.parametrize("kind", READER_KINDS)
def test_legacy_name_only_entry_keeps_the_nullable_int_hint(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = pd.DataFrame({"i": pd.array([1, None], dtype="Int8")})
    table = _legacy_blob(pa.Table.from_pandas(frame), drop=("field_name",))
    reader = make_reader(kind, table, parquet_bytes(table), tmp_path, monkeypatch)
    ours = bounded_profile(reader, kind)
    assert_same_profile(ours, oracle_profile(reader, kind), kind)
    assert _col(ours, "i").dtype == "Int8"
    config = {"tables": [{"name": "t", "columns": [{"name": "i", "strategy": "truncate"}]}]}
    with pytest.raises(PlanCompileError):
        _checks.check_null_bearing_int_unsupported(config, _profile_of(ours))


def _profile_of(table_profile: Any) -> Any:
    from datetime import datetime, timezone

    from decoy_engine.profile._types import Profile

    return Profile(
        schema_version=1,
        tables=(table_profile,),
        relationships=(),
        profiled_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        decoy_engine_version="0",
        profile_seed=None,
    )


# 3. period and interval extension types with no pandas blob


@pytest.mark.parametrize("kind", ["local", "resident"])
def test_period_and_interval_types_map_like_pandas_without_a_blob(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = pd.DataFrame(
        {
            "p": pd.PeriodIndex(["2020-01", "2020-02", "2020-01"], freq="M"),
            "v": pd.arrays.IntervalArray.from_tuples([(0, 1), (1, 2), (0, 1)]),
        }
    )
    table = pa.Table.from_pandas(frame).replace_schema_metadata(None)
    reader = make_reader(kind, table, parquet_bytes(table), tmp_path, monkeypatch)
    ours = bounded_profile(reader, kind)
    assert_same_profile(ours, oracle_profile(reader, kind), kind)
    assert (_col(ours, "p").dtype, _col(ours, "p").distinct_count) == ("period[M]", 2)
    assert _col(ours, "v").distinct_count == 2


# 4. NaNs with different payloads


def _nan(payload: int) -> float:
    return struct.unpack("<d", struct.pack("<Q", 0x7FF8000000000000 | payload))[0]


@pytest.mark.parametrize("kind", READER_KINDS)
def test_nan_payloads_are_one_distinct_value(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np

    data = np.array([_nan(1), _nan(2), 1.0])
    mask = np.array([False, False, False])
    frame = pd.DataFrame({"f": pd.arrays.FloatingArray(data, mask)})
    table = pa.Table.from_pandas(frame)
    reader = make_reader(kind, table, parquet_bytes(table), tmp_path, monkeypatch)
    ours = bounded_profile(reader, kind)
    assert_same_profile(ours, oracle_profile(reader, kind), kind)
    assert (_col(ours, "f").distinct_count, _col(ours, "f").is_candidate_key_sampled) == (2, False)


# 5. infer_string


@pytest.mark.parametrize("kind", ["local", "resident"])
def test_plain_arrow_strings_keep_lengths_under_infer_string(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = pa.table({"s": pa.array(["abc", None])})
    reader = make_reader(kind, table, parquet_bytes(table), tmp_path, monkeypatch)
    with pd.option_context("future.infer_string", True):
        ours = bounded_profile(reader, kind)
        assert_same_profile(ours, oracle_profile(reader, kind), kind)
    assert (_col(ours, "s").avg_length, _col(ours, "s").max_length) == (3.0, 3)


# 6. the strict reader


def test_footer_with_an_overflowing_number_is_rejected() -> None:
    assert (
        _columns.decode_pandas_blob(b'{"index_columns": ["x"], "columns": [], "n": 1e999}') is None
    )
    assert _columns.decode_pandas_blob(b'{"index_columns": ["x"], "columns": []}') is not None


@pytest.mark.parametrize("kind", READER_KINDS)
def test_overflowing_footer_leaves_the_physical_column_visible(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = pa.table({"x": [1, 2], "y": [3, 4]}).replace_schema_metadata(
        {b"pandas": b'{"index_columns": ["x"], "columns": [], "n": 1e999}'}
    )
    reader = make_reader(kind, table, parquet_bytes(table), tmp_path, monkeypatch)
    assert [c.name for c in bounded_profile(reader, kind).columns] == ["x", "y"]


# 7. incompatible pair in the ArrowDtype branch


@pytest.mark.parametrize("kind", READER_KINDS)
def test_incompatible_arrowdtype_pair_is_an_ordinary_float64(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = pa.table({"a": pa.array([1, None, 3], pa.int8())})
    entry = {
        "name": "a",
        "field_name": "a",
        "pandas_type": "wrong",
        "numpy_type": "int8[pyarrow]",
        "metadata": None,
    }
    blob = json.dumps({"index_columns": [], "columns": [entry]}).encode()
    table = base.replace_schema_metadata({b"pandas": blob})
    reader = make_reader(kind, table, parquet_bytes(table), tmp_path, monkeypatch)
    assert _col(bounded_profile(reader, kind), "a").dtype == "float64"
