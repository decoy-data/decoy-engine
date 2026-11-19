"""The one Arrow-to-pandas descriptor registry (`decoy_engine._pandas_meta`).

It holds facts about what pyarrow writes into the `b"pandas"` footer blob, so native admission
and the output sanitizer read one table. The pairs are checked against the pinned pyarrow and
pandas here, so a library bump that writes a new pair turns a cell red.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
from types import MappingProxyType
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine._pandas_meta import (
    COLUMN_INDEX_ENTRY,
    PLAIN_PAIRS,
    column_metadata,
    pairs_for,
)

# The thirteen pairs native admission accepted before the registry existed.
OLD_ADMISSION_PAIRS = {
    pa.bool_(): ("bool", "bool"),
    pa.int8(): ("int8", "int8"),
    pa.int16(): ("int16", "int16"),
    pa.int32(): ("int32", "int32"),
    pa.int64(): ("int64", "int64"),
    pa.uint8(): ("uint8", "uint8"),
    pa.uint16(): ("uint16", "uint16"),
    pa.uint32(): ("uint32", "uint32"),
    pa.uint64(): ("uint64", "uint64"),
    pa.float32(): ("float32", "float32"),
    pa.float64(): ("float64", "float64"),
    pa.string(): ("unicode", "object"),
    pa.large_string(): ("unicode", "object"),
}

# One pandas column per case, covering every dtype family the engine reads from pandas.
_STAMPS = pd.to_datetime(["2020-01-01", "2020-01-02"])
CASES: dict[str, Any] = {
    "bool": pd.Series([True, False]),
    "boolean": pd.Series([True, None], dtype="boolean"),
    "int8": pd.Series([1, 2], dtype="int8"),
    "uint64": pd.Series([1, 2], dtype="uint64"),
    "int64": pd.Series([1, 2]),
    "Int64": pd.Series([1, None], dtype="Int64"),
    "UInt32": pd.Series([1, None], dtype="UInt32"),
    "float32": pd.Series([1.0, 2.0], dtype="float32"),
    "float64": pd.Series([1.0, 2.0]),
    "Float64": pd.Series([1.0, None], dtype="Float64"),
    "object": pd.Series(["a", "b"]),
    "string": pd.Series(["a", None], dtype="string"),
    "string_pyarrow": pd.Series(["a", None], dtype="string[pyarrow]"),
    "datetime": pd.Series(_STAMPS),
    "datetime_ms": pd.Series(_STAMPS.astype("datetime64[ms]")),
    "datetime_tz": pd.Series(_STAMPS.tz_localize("UTC")),
    "date": pd.Series([dt.date(2020, 1, 1)] * 2),
    "decimal": pd.Series([decimal.Decimal("1.50")] * 2),
    "category": pd.Series(["a", "b"], dtype="category"),
    "ordered": pd.Series(pd.Categorical(["a", "b"], ordered=True)),
    "bytes": pd.Series([b"a", b"b"]),
    "timedelta": pd.Series(pd.to_timedelta([1, 2], unit="s")),
    "time": pd.Series([dt.time(1, 2)] * 2),
    "arrow_int64": pd.Series([1, 2], dtype=pd.ArrowDtype(pa.int64())),
    "arrow_string": pd.Series(["a", "b"], dtype=pd.ArrowDtype(pa.string())),
}


def test_admission_view_equals_the_old_thirteen_pairs() -> None:
    assert dict(PLAIN_PAIRS) == OLD_ADMISSION_PAIRS


def test_column_index_entry_is_pyarrows_default() -> None:
    frame = pd.DataFrame({"a": [1]})
    blob = json.loads(pa.Table.from_pandas(frame, preserve_index=True).schema.metadata[b"pandas"])
    assert blob["column_indexes"] == [COLUMN_INDEX_ENTRY]


@pytest.mark.parametrize("case", CASES)
def test_every_pair_pyarrow_writes_is_listed(case: str) -> None:
    table = pa.Table.from_pandas(pd.DataFrame({"c": CASES[case]}), preserve_index=False)
    entry = json.loads(table.schema.metadata[b"pandas"])["columns"][0]
    typ = table.schema.field("c").type
    assert (entry["pandas_type"], entry["numpy_type"]) in pairs_for(typ)
    written = entry["metadata"]
    derived = column_metadata(typ)
    # `num_categories` counts source categories, which a schema alone cannot know: never derived.
    assert derived == (
        {k: v for k, v in written.items() if k != "num_categories"} if written else None
    )


@pytest.mark.parametrize("typ", list(OLD_ADMISSION_PAIRS), ids=str)
def test_the_plain_pair_is_the_default(typ: pa.DataType) -> None:
    assert pairs_for(typ)[0] == OLD_ADMISSION_PAIRS[typ]


@pytest.mark.parametrize(
    "typ", [pa.list_(pa.int64()), pa.struct([("a", pa.int64())]), pa.map_(pa.string(), pa.int64())]
)
def test_a_type_outside_the_registry_has_no_pairs(typ: pa.DataType) -> None:
    assert pairs_for(typ) == ()


def test_the_shared_tables_are_read_only() -> None:
    assert isinstance(PLAIN_PAIRS, MappingProxyType)
    assert isinstance(COLUMN_INDEX_ENTRY, MappingProxyType)
    assert isinstance(COLUMN_INDEX_ENTRY["metadata"], MappingProxyType)
    with pytest.raises(TypeError):
        COLUMN_INDEX_ENTRY["name"] = "x"  # type: ignore[index]


def test_pandas_period_and_interval_pairs_follow_their_parameters() -> None:
    frame = pd.DataFrame(
        {"p": pd.period_range("2020-01", periods=2, freq="M"), "i": pd.interval_range(0, 2)}
    )
    table = pa.Table.from_pandas(frame, preserve_index=False)
    entries = json.loads(table.schema.metadata[b"pandas"])["columns"]
    for entry, field in zip(entries, table.schema, strict=True):
        assert (entry["pandas_type"], entry["numpy_type"]) in pairs_for(field.type)
