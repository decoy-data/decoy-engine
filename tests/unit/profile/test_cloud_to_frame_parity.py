"""Cloud `to_frame` equals the local read of the same bytes (F25 G7-1, case 11).

Parquet equals the installed `pd.read_parquet` (values, dtypes, index and `attrs`); CSV equals
`pandas_adapter.read_csv`, with and without lexeme columns. S3 and GCS.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine._lexeme import LEXEME_KEY, pandas_lexeme_kwargs
from decoy_engine.fileaccess.adapters import pandas as pandas_adapter
from decoy_engine.fileaccess.adapters.memory import StreamHandle
from decoy_engine.profile import _cloud_readers as cr
from tests.unit.profile.test_cloud_to_frame_bounded import _desc, _serve

pytest.importorskip("botocore")


def _build(provider: str) -> Callable[[dict[str, Any]], Any]:
    return cr.build_s3_profile_source if provider == "s3" else cr.build_gcs_profile_source


def _frames() -> dict[str, pd.DataFrame]:
    tz = pd.date_range("2026-01-01", periods=3, freq="h", tz="America/Chicago")
    with_attrs = pd.DataFrame({"a": [1, 2, 3]})
    with_attrs.attrs = {"source": "unit", "n": 3}
    return {
        "range_index": pd.DataFrame({"v": [1.5, 2.5, 3.5]}),
        "named_index": pd.DataFrame(
            {"v": [1.5, 2.5, 3.5]}, index=pd.Index(["x", "y", "z"], name="k")
        ),
        "categorical": pd.DataFrame({"c": pd.Categorical(["lo", "hi", "lo"])}),
        "tz_aware": pd.DataFrame({"ts": tz, "n": [1, 2, 3]}),
        "nullable_int": pd.DataFrame({"i": pd.array([1, None, 3], dtype="Int64")}),
        "attrs": with_attrs,
        "empty": pd.DataFrame({"a": pd.Series([], dtype="int64"), "b": pd.Series([], dtype=str)}),
    }


def _no_row_groups() -> bytes:
    """A Parquet file with a schema (and pandas metadata) and zero row groups."""
    frame = pd.DataFrame({"a": pd.Series([], dtype="int64")}, index=pd.Index([], name="k"))
    schema = pa.Table.from_pandas(frame).schema
    sink = io.BytesIO()
    pq.ParquetWriter(sink, schema).close()
    data = sink.getvalue()
    assert pq.ParquetFile(io.BytesIO(data)).metadata.num_row_groups == 0
    return data


def _parquet(case: str) -> bytes:
    if case == "zero_row_groups":
        return _no_row_groups()
    sink = io.BytesIO()
    _frames()[case].to_parquet(sink)
    return sink.getvalue()


@pytest.mark.parametrize("provider", ["s3", "gcs"])
@pytest.mark.parametrize("case", [*sorted(_frames()), "zero_row_groups"])
def test_parquet_to_frame_equals_read_parquet(
    monkeypatch: pytest.MonkeyPatch, provider: str, case: str
) -> None:
    data = _parquet(case)
    ledger, _ = _serve(monkeypatch, provider, data)
    descriptor = _desc(provider, "parquet")
    got = _build(provider)(descriptor).to_frame()
    expected = pd.read_parquet(io.BytesIO(data))
    pd.testing.assert_frame_equal(got, expected)
    assert got.attrs == expected.attrs
    if case == "attrs":
        assert expected.attrs  # non-vacuity: the comparison above has something to compare
    assert ledger.data_requests


def test_attrs_come_from_the_metadata_whatever_pyarrow_restores() -> None:
    """pyarrow 14 to 20 leave `attrs` to the caller; this one restores them itself. A table
    whose `to_pandas` drops them stands in for the older ones."""
    from decoy_engine.fileaccess.adapters import arrow as arrow_adapter

    class Older:
        def __init__(self, table: pa.Table) -> None:
            self.schema = table.schema
            self._table = table

        def to_pandas(self) -> pd.DataFrame:
            frame = self._table.to_pandas()
            frame.attrs = {}
            return frame

    table = pq.read_table(io.BytesIO(_parquet("attrs")))
    older: Any = Older(table)
    assert older.to_pandas().attrs == {}  # non-vacuity: the stand-in does drop them
    restored = arrow_adapter.parquet_table_to_pandas(older, lambda t: t.to_pandas())
    assert restored.attrs == {"source": "unit", "n": 3}


_CSV = b"id,age,note\n1,NA,x\n2,042,\n3,,NA\n"


@pytest.mark.parametrize("provider", ["s3", "gcs"])
@pytest.mark.parametrize("lexemes", [None, ["age"]])
def test_csv_to_frame_equals_the_local_read(
    monkeypatch: pytest.MonkeyPatch, provider: str, lexemes: list[str] | None
) -> None:
    ledger, _ = _serve(monkeypatch, provider, _CSV)
    descriptor: dict[str, Any] = _desc(provider, "csv")
    if lexemes is not None:
        descriptor[LEXEME_KEY] = lexemes
    got = _build(provider)(descriptor).to_frame()
    with StreamHandle(io.BytesIO(_CSV), "x") as handle:
        expected = pandas_adapter.read_csv(handle, **pandas_lexeme_kwargs(lexemes))
    pd.testing.assert_frame_equal(got, expected)
    if lexemes:
        assert got["age"].tolist() == ["NA", "042", ""]
    assert ledger.data_requests


@pytest.mark.parametrize("provider", ["s3", "gcs"])
def test_csv_schema_keeps_a_nullable_boolean_column_boolean(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    """True/False/NA parses as object holding bools; only mixed text and numbers become text."""
    data = b"flag,mixed\nTrue,1\nFalse,x\nNA,2\n"
    _serve(monkeypatch, provider, data)
    schema = _build(provider)(_desc(provider, "csv")).schema()
    assert pa.types.is_boolean(schema.field("flag").type)
    assert pa.types.is_string(schema.field("mixed").type)
