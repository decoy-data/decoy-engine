"""Native admission decides the same before and after its pandas table moved to the registry.

The corpus and its expected decisions are fixed in this file. It was written and run green on the
base first, so a registry change that moves an admission decision turns it red.
"""

from __future__ import annotations

import decimal
import json
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.execution.native._faker_deterministic_admission import metadata_shape_admits

_PD = b"pandas"


def _blob(columns: list[dict[str, Any]], **over: Any) -> bytes:
    body: dict[str, Any] = {
        "index_columns": [],
        "column_indexes": [],
        "columns": columns,
        "attributes": {},
        "creator": {"library": "pyarrow", "version": "24.0.0"},
        "pandas_version": "2.3.3",
    }
    body.update(over)
    return json.dumps(body).encode()


def _col(name: str, pandas_type: str, numpy_type: str, meta: Any = None) -> dict[str, Any]:
    return {
        "name": name,
        "field_name": name,
        "pandas_type": pandas_type,
        "numpy_type": numpy_type,
        "metadata": meta,
    }


def _real(frame: pd.DataFrame, **kw: Any) -> pa.Schema:
    return pa.Table.from_pandas(frame, **kw).schema


INT = pa.field("a", pa.int64())
STR = pa.field("s", pa.string())
RANGE = {"kind": "range", "name": None, "start": 0, "stop": 2, "step": 1}
INDEX_ENTRY = {
    "name": None,
    "field_name": None,
    "pandas_type": "unicode",
    "numpy_type": "object",
    "metadata": {"encoding": "UTF-8"},
}


def _with(fields: list[pa.Field], blob: bytes | None, field_meta: dict[bytes, bytes] | None = None):
    if field_meta:
        fields = [f.with_metadata(field_meta) if i == 0 else f for i, f in enumerate(fields)]
    schema = pa.schema(fields)
    return schema if blob is None else schema.with_metadata({_PD: blob})


# (id, schema, column, ordinal, expected decision at the base)
CORPUS: list[tuple[str, pa.Schema, str, int, bool]] = [
    ("no_metadata_int", pa.schema([INT, STR]), "a", 0, True),
    ("no_metadata_float_target", pa.schema([pa.field("a", pa.float64())]), "a", 0, False),
    (
        "real_int_string",
        _real(pd.DataFrame({"a": [1, 2], "s": ["x", "y"]}), preserve_index=False),
        "a",
        0,
        True,
    ),
    (
        "real_range_index",
        _real(pd.DataFrame({"a": [1, 2], "s": ["x", "y"]}), preserve_index=None),
        "a",
        0,
        True,
    ),
    (
        "real_nullable_int",
        _real(pd.DataFrame({"a": pd.array([1, None], dtype="Int64")}), preserve_index=False),
        "a",
        0,
        False,
    ),
    (
        "real_bool_pyarrow_dtype",
        _real(pd.DataFrame({"a": pd.array([True], dtype="bool[pyarrow]")}), preserve_index=False),
        "a",
        0,
        False,
    ),
    (
        "real_timestamp_companion",
        _real(pd.DataFrame({"a": [1], "t": pd.to_datetime(["2020-01-01"])}), preserve_index=False),
        "a",
        0,
        False,
    ),
    (
        "real_decimal_companion",
        _real(
            pd.DataFrame({"a": [1], "d": [decimal.Decimal("1.5")]}),
            preserve_index=False,
        ),
        "a",
        0,
        False,
    ),
    (
        "real_float_string_companions",
        _real(pd.DataFrame({"a": [1], "f": [1.5], "s": ["x"]}), preserve_index=False),
        "a",
        0,
        True,
    ),
    (
        "forged_pair_int64_as_bool",
        _with([INT], _blob([_col("a", "int64", "bool[pyarrow]")])),
        "a",
        0,
        False,
    ),
    ("forged_pair_wrong_numpy", _with([INT], _blob([_col("a", "int64", "int32")])), "a", 0, False),
    (
        "forged_pair_wrong_pandas_type",
        _with([INT], _blob([_col("a", "unicode", "int64")])),
        "a",
        0,
        False,
    ),
    ("pair_ok_manual", _with([INT], _blob([_col("a", "int64", "int64")])), "a", 0, True),
    (
        "pair_large_string_companion",
        _with(
            [INT, pa.field("s", pa.large_string())],
            _blob([_col("a", "int64", "int64"), _col("s", "unicode", "object")]),
        ),
        "a",
        0,
        True,
    ),
    (
        "column_metadata_not_null",
        _with([INT], _blob([_col("a", "int64", "int64", {"x": 1})])),
        "a",
        0,
        False,
    ),
    (
        "attributes_non_empty",
        _with([INT], _blob([_col("a", "int64", "int64")], attributes={"k": "v"})),
        "a",
        0,
        False,
    ),
    (
        "attributes_absent",
        _with([INT], _blob([_col("a", "int64", "int64")]).replace(b'"attributes": {}, ', b"")),
        "a",
        0,
        True,
    ),
    (
        "creator_not_pyarrow",
        _with(
            [INT], _blob([_col("a", "int64", "int64")], creator={"library": "x", "version": "1"})
        ),
        "a",
        0,
        False,
    ),
    (
        "range_index_ok",
        _with(
            [INT],
            _blob(
                [_col("a", "int64", "int64")], index_columns=[RANGE], column_indexes=[INDEX_ENTRY]
            ),
        ),
        "a",
        0,
        True,
    ),
    (
        "range_index_named",
        _with(
            [INT],
            _blob(
                [_col("a", "int64", "int64")],
                index_columns=[dict(RANGE, name="x")],
                column_indexes=[INDEX_ENTRY],
            ),
        ),
        "a",
        0,
        False,
    ),
    (
        "range_index_bad_column_indexes",
        _with(
            [INT], _blob([_col("a", "int64", "int64")], index_columns=[RANGE], column_indexes=[])
        ),
        "a",
        0,
        False,
    ),
    ("not_json", _with([INT], b"not json"), "a", 0, False),
    ("json_list", _with([INT], b"[]"), "a", 0, False),
    ("duplicate_keys", _with([INT], b'{"index_columns": [], "index_columns": []}'), "a", 0, False),
    (
        "extra_schema_key",
        pa.schema([INT]).with_metadata({_PD: _blob([_col("a", "int64", "int64")]), b"k": b"v"}),
        "a",
        0,
        False,
    ),
    ("field_metadata", _with([INT], None, {b"k": b"v"}), "a", 0, False),
    ("extension_metadata", _with([INT], None, {b"ARROW:extension:name": b"x"}), "a", 0, False),
    ("wrong_ordinal", pa.schema([INT, STR]), "a", 1, False),
    ("target_uint8", pa.schema([pa.field("a", pa.uint8())]), "a", 0, True),
]


@pytest.mark.parametrize(
    ("schema", "column", "ordinal", "expected"),
    [pytest.param(s, c, o, e, id=i) for i, s, c, o, e in CORPUS],
)
def test_admission_decision_is_unchanged(
    schema: pa.Schema, column: str, ordinal: int, expected: bool
) -> None:
    assert metadata_shape_admits(schema, column=column, ordinal=ordinal) is expected
