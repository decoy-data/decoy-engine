"""The two functions that map a type to a shape, row by row against the plan's table."""

from __future__ import annotations

import pyarrow as pa
import pytest

from decoy_engine.contracts.column_shape import (
    EXACT_FLOAT_DECIMAL_DIGITS,
    TEXT_SOURCE_FORMATS,
    ColumnShape,
    classify_column,
    declared_shape,
    is_bounded_decimal,
)
from decoy_engine.profile._lazy_build import FILE_FORMATS

S = ColumnShape


@pytest.mark.parametrize(
    ("arrow_type", "expected"),
    [
        (pa.string(), S.TEXT),
        (pa.large_string(), S.TEXT),
        (pa.date32(), S.DATE),
        (pa.date64(), S.DATE),
        (pa.timestamp("us", tz="UTC"), S.TIMESTAMP_TZ),
        (pa.timestamp("ns", tz="+05:30"), S.TIMESTAMP_TZ),
        (pa.timestamp("us"), S.TIMESTAMP_NAIVE),
        (pa.int8(), S.INTEGER),
        (pa.int64(), S.INTEGER),
        (pa.uint32(), S.INTEGER),
        (pa.float32(), S.FLOAT),
        (pa.float64(), S.FLOAT),
        (pa.decimal128(15, 2), S.DECIMAL),
        (pa.decimal128(15, 15), S.DECIMAL),
        (pa.decimal128(1, 0), S.DECIMAL),
        (pa.decimal128(16, 2), S.DECIMAL_WIDE),
        (pa.decimal256(20, 2), S.DECIMAL_WIDE),
        (pa.decimal128(15, -1), S.DECIMAL_WIDE),
        (pa.decimal128(15, -5), S.DECIMAL_WIDE),
        (pa.bool_(), S.BOOLEAN),
        (pa.list_(pa.int64()), S.OTHER),
        (pa.struct([pa.field("a", pa.int64())]), S.OTHER),
        (pa.binary(), S.OTHER),
        (pa.dictionary(pa.int32(), pa.string()), S.TEXT),
        (pa.dictionary(pa.int32(), pa.large_string()), S.TEXT),
        (pa.dictionary(pa.int32(), pa.int64()), S.OTHER),
        (pa.null(), S.OTHER),
    ],
    ids=str,
)
def test_classifier_table(arrow_type: pa.DataType, expected: ColumnShape) -> None:
    assert classify_column(source_format="parquet", arrow_type=arrow_type) is expected


def test_no_arrow_type_is_unknown() -> None:
    assert classify_column(source_format=None, arrow_type=None) is S.UNKNOWN
    assert classify_column(source_format="parquet", arrow_type=None) is S.UNKNOWN


@pytest.mark.parametrize("fmt", ["csv", "fixed_width"])
@pytest.mark.parametrize("arrow_type", [None, pa.int64(), pa.float64(), pa.date32(), pa.string()])
def test_csv_is_text_even_when_reader_inferred_int(
    fmt: str, arrow_type: pa.DataType | None
) -> None:
    assert classify_column(source_format=fmt, arrow_type=arrow_type) is S.TEXT


def test_text_formats_are_real_file_formats() -> None:
    assert {"csv", "fixed_width"} == TEXT_SOURCE_FORMATS
    assert set(FILE_FORMATS) >= TEXT_SOURCE_FORMATS


def test_unlisted_arrow_type_is_other() -> None:
    for t in (
        pa.list_(pa.int64()),
        pa.struct([pa.field("a", pa.int64())]),
        pa.map_(pa.string(), pa.int64()),
    ):
        assert classify_column(source_format="parquet", arrow_type=t) is S.OTHER


@pytest.mark.parametrize(
    ("precision", "scale", "bounded"),
    [
        (15, 2, True),
        (15, 0, True),
        (15, 15, True),
        (16, 2, False),
        (15, -1, False),
        (10, 11, False),
    ],
)
def test_bounded_decimal_rule(precision: int, scale: int, bounded: bool) -> None:
    assert EXACT_FLOAT_DECIMAL_DIGITS == 15
    assert is_bounded_decimal(precision, scale) is bounded


@pytest.mark.parametrize(
    ("logical_type", "parse_format", "expected"),
    [
        ("date", {"id": "date/iso8601/v1"}, S.DATE),
        ("integer", {"id": "integer/ascii/v1"}, S.INTEGER),
        ("decimal", {"id": "decimal/plain/v1", "precision": 15, "scale": 2}, S.DECIMAL),
        ("decimal", {"id": "decimal/plain/v1", "precision": 16, "scale": 2}, S.DECIMAL_WIDE),
        ("decimal", {"id": "decimal/plain/v1", "precision": 15, "scale": -1}, S.DECIMAL_WIDE),
        ("decimal", {"id": "decimal/plain/v1"}, S.DECIMAL_WIDE),
        ("decimal", None, S.DECIMAL_WIDE),
        ("currency", {"id": "currency/explicit/v1", "precision": 12, "scale": 2}, S.DECIMAL),
        ("currency", {"id": "currency/explicit/v1", "precision": 20, "scale": 2}, S.DECIMAL_WIDE),
        ("string", {"id": "string/exact/v1"}, S.TEXT),
    ],
)
def test_declared_shape_table(
    logical_type: str, parse_format: dict | None, expected: ColumnShape
) -> None:
    assert declared_shape(logical_type=logical_type, parse_format=parse_format) is expected


def test_vocabulary_is_closed() -> None:
    assert {s.value for s in S} == {
        "text", "date", "timestamp_tz", "timestamp_naive", "integer", "float",
        "decimal", "decimal_wide", "boolean", "other", "unknown",
    }  # fmt: skip
