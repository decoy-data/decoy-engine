"""OUTPUT-METADATA-LEAK E1: the one rule for output Parquet metadata (`safe_output`).

An output schema keeps no field metadata at any depth and one schema key, `b"pandas"`, in a form
rebuilt from the output schema, the running pyarrow and pandas versions and the descriptor
registry. Nothing in the blob is copied because it looks valid.
"""

from __future__ import annotations

import datetime as dt
import decimal
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine._pandas_meta import COLUMN_INDEX_ENTRY
from decoy_engine.execution._transactional_sink import ParquetTransactionalSink
from decoy_engine.safe_output import _file_metadata as fm
from decoy_engine.safe_output import output_schema, output_table, sanitized_schema_metadata
from tests.security._metadata_canary import schema_texts

CANARY = b"DCY-CANARY"
PD = b"pandas"


def _fld(name: str, typ: pa.DataType, *, nullable: bool = True) -> pa.Field:
    meta = {b"comment": CANARY, b"PARQUET:field_id": b"7"}
    return pa.field(name, typ, nullable=nullable, metadata=meta)


# Predicates at the pin that name a type with no child field (or are aggregates of others).
SCALAR_PREDICATES = frozenset(
    [
        "is_binary",
        "is_binary_view",
        "is_boolean",
        "is_date",
        "is_date32",
        "is_date64",
        "is_decimal",
        "is_decimal128",
        "is_decimal256",
        "is_decimal32",
        "is_decimal64",
        "is_duration",
        "is_fixed_size_binary",
        "is_float16",
        "is_float32",
        "is_float64",
        "is_floating",
        "is_int16",
        "is_int32",
        "is_int64",
        "is_int8",
        "is_integer",
        "is_interval",
        "is_large_binary",
        "is_large_string",
        "is_large_unicode",
        "is_nested",
        "is_null",
        "is_primitive",
        "is_signed_integer",
        "is_string",
        "is_string_view",
        "is_temporal",
        "is_time",
        "is_time32",
        "is_time64",
        "is_timestamp",
        "is_uint16",
        "is_uint32",
        "is_uint64",
        "is_uint8",
        "is_unicode",
        "is_unsigned_integer",
        "is_integer_value",
        "is_float_value",
        "is_boolean_value",
    ]
)

NESTED: dict[str, Callable[[], pa.DataType]] = {
    "struct": lambda: pa.struct([_fld("c", pa.int64()), _fld("d", pa.string())]),
    "list": lambda: pa.list_(_fld("item", pa.int64())),
    "large_list": lambda: pa.large_list(_fld("item", pa.int64())),
    "fixed_size_list": lambda: pa.list_(_fld("item", pa.int64()), 2),
    "list_view": lambda: pa.list_view(_fld("item", pa.int64())),
    "large_list_view": lambda: pa.large_list_view(_fld("item", pa.int64())),
    "map_key": lambda: pa.map_(_fld("key", pa.string(), nullable=False), pa.int64()),
    "map_item": lambda: pa.map_(pa.string(), _fld("value", pa.int64())),
    "dense_union": lambda: pa.union([_fld("a", pa.int64()), _fld("b", pa.string())], "dense"),
    "sparse_union": lambda: pa.union([_fld("a", pa.int64()), _fld("b", pa.string())], "sparse"),
    "dictionary_value": lambda: pa.dictionary(pa.int8(), pa.struct([_fld("c", pa.int64())])),
    "run_end_encoded": lambda: pa.run_end_encoded(pa.int32(), pa.struct([_fld("c", pa.int64())])),
    "deep": lambda: pa.list_(_fld("item", pa.struct([_fld("c", pa.list_(_fld("x", pa.int8())))]))),
}


def _dirty(typ: pa.DataType) -> pa.Schema:
    return pa.schema(
        [_fld("n", typ), _fld("plain", pa.int64(), nullable=False)],
        metadata={b"table_comment": CANARY},
    )


@pytest.mark.parametrize("kind", NESTED)
def test_fields_stripped_recursively(kind: str) -> None:
    typ = NESTED[kind]()
    out = output_schema(_dirty(typ))
    blob = b"".join(schema_texts(out))
    assert CANARY not in blob
    assert b"PARQUET:field_id" not in blob
    assert out.names == ["n", "plain"]
    assert out.field("n").type == typ
    assert out.field("plain").nullable is False
    assert out.metadata is None


def test_fields_stripped_at_the_top_level() -> None:
    out = output_schema(_dirty(pa.int64()))
    assert [f.metadata for f in out] == [None, None]


def test_nested_types_enumerated() -> None:
    """Every `pa.types.is_*` predicate at the pin is either handled here or known not nested, so a
    new pyarrow nested type turns this red; an unhandled nested type fails closed."""
    predicates = {n for n in dir(pa.types) if n.startswith("is_")}
    assert predicates <= fm.HANDLED_PREDICATES | SCALAR_PREDICATES
    assert {
        "is_struct",
        "is_list",
        "is_large_list",
        "is_fixed_size_list",
        "is_list_view",
        "is_large_list_view",
        "is_map",
        "is_union",
        "is_dictionary",
        "is_run_end_encoded",
    } == fm.HANDLED_PREDICATES


def test_unhandled_nested_type_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fm, "_REBUILDERS", ())
    with pytest.raises(TypeError):
        output_schema(_dirty(NESTED["struct"]()))


def test_only_allowed_schema_keys() -> None:
    frame = pd.DataFrame({"a": [1, 2]})
    good = pa.Table.from_pandas(frame, preserve_index=False).schema.metadata[PD]
    meta = {
        PD: good,
        b"table_comment": CANARY,
        b"PANDAS_ATTRS": b'{"k": "DCY-CANARY"}',
        b"\xff\xfe": CANARY,
        b"DCY-CANARY-SKEY": b"x",
    }
    out = output_schema(pa.schema([pa.field("a", pa.int64())], metadata=meta))
    assert out.metadata == {PD: good}


def test_no_allowed_key_leaves_no_metadata() -> None:
    schema = pa.schema([pa.field("a", pa.int64())], metadata={b"table_comment": CANARY})
    assert output_schema(schema).metadata is None
    assert sanitized_schema_metadata({b"x": b"y"}, for_schema=pa.schema([])) is None
    assert sanitized_schema_metadata(None, for_schema=pa.schema([])) is None


# -- the pandas blob ---------------------------------------------------------------------------


def _from_pandas(frame: pd.DataFrame, **kw: Any) -> pa.Table:
    return pa.Table.from_pandas(frame, **kw)


def _blob(schema: pa.Schema) -> dict[str, Any]:
    return json.loads((schema.metadata or {})[PD])


def test_pandas_blob_sanitized() -> None:
    frame = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    frame.attrs["note"] = CANARY.decode()
    frame.columns.name = "DCY-CANARY-COLIDX"
    frame.index.name = "DCY-CANARY-RIDX"
    source = _from_pandas(frame, preserve_index=None).schema
    assert CANARY in source.metadata[PD]
    out = output_schema(source)
    assert CANARY not in b"".join(schema_texts(out))
    blob = _blob(out)
    assert blob["attributes"] == {}
    assert blob["index_columns"] == []
    assert [c["name"] for c in blob["columns"]] == ["a", "b"]


DTYPES: dict[str, pd.Series] = {
    "categorical": pd.Series(["a", "b", "a"], dtype="category"),
    "tz_datetime": pd.Series(pd.to_datetime(["2020-01-01"] * 3).tz_localize("UTC")),
    "decimal": pd.Series([decimal.Decimal("1.50")] * 3),
    "nullable_int": pd.Series([1, None, 3], dtype="Int64"),
    "string_pyarrow": pd.Series(["a", None, "c"], dtype="string[pyarrow]"),
    "datetime_ms": pd.Series(pd.to_datetime(["2020-01-01"] * 3).astype("datetime64[ms]")),
    "bool": pd.Series([True, False, True]),
    "float": pd.Series([1.5, 2.5, 3.5]),
    "date": pd.Series([dt.date(2020, 1, 1)] * 3),
    "plain_object": pd.Series(["x", "y", "z"]),
}


@pytest.mark.parametrize("dtype", DTYPES)
def test_clean_blob_identical(dtype: str) -> None:
    frame = pd.DataFrame({"c": DTYPES[dtype], "non_asciié": [1, 2, 3]})
    table = _from_pandas(frame, preserve_index=False)
    out = output_schema(table.schema)
    if dtype == "categorical":
        meta = next(c for c in _blob(out)["columns"] if c["name"] == "c")["metadata"]
        assert meta == {"ordered": False}
    else:
        assert out.metadata == table.schema.metadata
    assert list(output_table(table).to_pandas().dtypes) == list(table.to_pandas().dtypes)
    buf = io.BytesIO()
    pq.write_table(output_table(table), buf)
    back = pq.read_table(pa.BufferReader(buf.getvalue()))
    assert list(back.to_pandas().dtypes) == list(table.to_pandas().dtypes)


def test_stored_index_column_is_kept_and_identical() -> None:
    frame = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}).set_index("a")
    table = _from_pandas(frame, preserve_index=True)
    assert output_schema(table.schema).metadata == table.schema.metadata


def test_clean_file_identical(tmp_path: Path) -> None:
    frame = pd.DataFrame({"a": [1, 2], "b": ["x", "y"], "c": pd.array([1, None], dtype="Int64")})
    table = _from_pandas(frame, preserve_index=False)
    sink = ParquetTransactionalSink(tmp_path / "published")
    sink.write("t", table)
    sink.commit()
    raw = tmp_path / "raw.parquet"
    pq.write_table(table, raw)
    assert sink.committed_table_path("t").read_bytes() == raw.read_bytes()


# -- forged blobs ------------------------------------------------------------------------------

FORGE_FRAME = pd.DataFrame(
    {
        "i": [1, 2],
        "s": ["x", "y"],
        "d": [decimal.Decimal("1.50")] * 2,
        "t": pd.to_datetime(["2020-01-01"] * 2).tz_localize("UTC"),
    }
)
FORGE_TABLE = _from_pandas(FORGE_FRAME, preserve_index=False)
CLEAN = FORGE_TABLE.schema.metadata[PD]


def _forge(edit: Callable[[dict[str, Any]], None]) -> bytes:
    body = json.loads(CLEAN)
    edit(body)
    return json.dumps(body).encode()


def _col(body: dict[str, Any], name: str) -> dict[str, Any]:
    return next(c for c in body["columns"] if c["name"] == name)


def _meta_key(name: str, key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def edit(body: dict[str, Any]) -> None:
        col = _col(body, name)
        col["metadata"] = {**(col["metadata"] or {}), key: value}

    return edit


def _set(name: str, key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    return lambda body: _col(body, name).__setitem__(key, value)


VALID_LOOKING: dict[str, bytes] = {
    "numpy_type_canary": _forge(_set("i", "numpy_type", "DCY-CANARY")),
    "numpy_type_plausible_wrong": _forge(_set("i", "numpy_type", "int32")),
    "pandas_type_decimal_on_string": _forge(_set("s", "pandas_type", "decimal")),
    "precision_secret": _forge(_meta_key("d", "precision", 314159265)),
    "scale_secret": _forge(_meta_key("d", "scale", 314159265)),
    "num_categories_secret": _forge(_meta_key("i", "num_categories", 314159265)),
    "timezone_canary": _forge(_meta_key("t", "timezone", "DCY-CANARY")),
    "pandas_version": _forge(lambda b: b.__setitem__("pandas_version", "9.9.9")),
    "creator": _forge(
        lambda b: b.__setitem__("creator", {"library": "pyarrow", "version": "99.0.0"})
    ),
    "creator_canary": _forge(
        lambda b: b.__setitem__("creator", {"library": "DCY-CANARY", "version": "DCY-CANARY"})
    ),
    "attributes": _forge(lambda b: b.__setitem__("attributes", {"k": "DCY-CANARY"})),
    "extra_member": _forge(lambda b: b.__setitem__("note", "DCY-CANARY")),
    "index_names_no_field": _forge(lambda b: b.__setitem__("index_columns", ["DCY-CANARY"])),
    "column_name_forged": _forge(_set("i", "name", "DCY-CANARY")),
    "column_metadata_forged": _forge(_set("s", "metadata", {"k": "DCY-CANARY"})),
    "trailing_newline_name": _forge(_set("i", "pandas_type", "int64\n")),
    "column_indexes_forged": _forge(
        lambda b: b.__setitem__("column_indexes", [{"name": "DCY-CANARY"}])
    ),
}
SHAPE_FORGERIES: dict[str, bytes] = {
    "not_json": b"DCY-CANARY not json",
    "json_list": b'["DCY-CANARY"]',
    "nan": b'{"index_columns": NaN, "creator": "DCY-CANARY"}',
    "not_utf8": b"\xff\xfe DCY-CANARY",
    "duplicate_keys": b'{"columns": [], "columns": "DCY-CANARY"}',
}
WRONG_TYPES: dict[str, bytes] = {
    "huge_columns_string": json.dumps({**json.loads(CLEAN), "columns": "x" * (1 << 20)}).encode(),
    "columns_not_list": json.dumps({**json.loads(CLEAN), "columns": "DCY-CANARY"}).encode(),
    "columns_entries_not_objects": json.dumps(
        {**json.loads(CLEAN), "columns": ["DCY-CANARY", 3]}
    ).encode(),
    "index_columns_not_list": json.dumps(
        {**json.loads(CLEAN), "index_columns": "DCY-CANARY"}
    ).encode(),
    "creator_not_object": json.dumps({**json.loads(CLEAN), "creator": ["DCY-CANARY"]}).encode(),
}


def _with_blob(blob: bytes) -> pa.Schema:
    return FORGE_TABLE.schema.with_metadata({PD: blob, b"table_comment": CANARY})


@pytest.mark.parametrize("name", VALID_LOOKING)
def test_forged_blob_not_copied(name: str) -> None:
    out = output_schema(_with_blob(VALID_LOOKING[name]))
    assert out.metadata == {PD: CLEAN}
    assert CANARY not in out.metadata[PD]
    assert b"314159265" not in out.metadata[PD]


@pytest.mark.parametrize("name", WRONG_TYPES)
def test_wrong_member_types_fall_back_to_the_derived_blob(name: str) -> None:
    out = output_schema(_with_blob(WRONG_TYPES[name]))
    assert out.metadata == {PD: CLEAN}


@pytest.mark.parametrize("name", SHAPE_FORGERIES)
def test_shape_forgeries_drop_the_blob(name: str) -> None:
    out = output_schema(_with_blob(SHAPE_FORGERIES[name]))
    assert out.metadata is None


def test_blob_versions_come_from_the_running_libraries() -> None:
    out = _blob(output_schema(_with_blob(VALID_LOOKING["creator"])))
    assert out["creator"] == {"library": "pyarrow", "version": pa.__version__}
    assert out["pandas_version"] == pd.__version__


def test_blob_entries_follow_output_schema() -> None:
    body = json.loads(CLEAN)
    body["columns"].append(
        {
            "name": "ghost",
            "field_name": "ghost",
            "pandas_type": "int64",
            "numpy_type": "int64",
            "metadata": None,
        }
    )
    body["columns"][0]["name"] = "renamed"
    body["index_columns"] = [
        {"kind": "range", "name": "DCY-CANARY", "start": 0, "stop": 9, "step": 1},
        "ghost",
    ]
    out = _blob(output_schema(_with_blob(json.dumps(body).encode())))
    assert [c["field_name"] for c in out["columns"]] == ["i", "s", "d", "t"]
    assert [c["name"] for c in out["columns"]] == ["i", "s", "d", "t"]
    assert out["index_columns"] == []


def test_a_type_outside_the_registry_gets_no_entry() -> None:
    frame = pd.DataFrame({"a": [1, 2], "l": [[1], [2]]})
    out = _blob(output_schema(_from_pandas(frame, preserve_index=False).schema))
    assert [c["name"] for c in out["columns"]] == ["a"]


# -- tables ------------------------------------------------------------------------------------


def test_output_table_passes_a_clean_table_through() -> None:
    table = _from_pandas(pd.DataFrame({"a": [1, 2]}), preserve_index=False)
    assert output_table(table) is table


def test_output_table_copies_no_buffers() -> None:
    table = pa.table({"a": pa.array([1, 2, 3])}, schema=pa.schema([_fld("a", pa.int64())]))
    out = output_table(table)
    assert out.schema.field("a").metadata is None
    assert (
        out.column("a").chunk(0).buffers()[1].address
        == table.column("a").chunk(0).buffers()[1].address
    )


def test_output_table_strips_nested_child_metadata() -> None:
    typ = pa.struct([_fld("c", pa.int64())])
    table = pa.table({"s": pa.array([{"c": 1}], typ)}, schema=pa.schema([_fld("s", typ)]))
    out = output_table(table)
    assert CANARY not in b"".join(schema_texts(out.schema))
    assert CANARY not in b"".join(schema_texts(pa.schema([pa.field("s", out.column("s").type)])))


# -- extension types -----------------------------------------------------------------------------


def _opaque() -> pa.DataType:
    child = _fld("c", pa.int64())
    return pa.opaque(pa.struct([child]), "DCY-CANARY-type", "DCY-CANARY-vendor")


def _tensor() -> pa.DataType:
    return pa.fixed_shape_tensor(pa.float64(), (2,), dim_names=["DCY-CANARY-dim"])


class _Unknown(pa.ExtensionType):
    """A Python-registered extension whose serialized parameters hold source text."""

    def __init__(self) -> None:
        super().__init__(pa.int64(), "test.unknown_ext")

    def __arrow_ext_serialize__(self) -> bytes:
        return b"DCY-CANARY-params"

    @classmethod
    def __arrow_ext_deserialize__(cls, storage_type: pa.DataType, serialized: bytes):
        return cls()


@pytest.fixture
def unknown_ext():
    pa.register_extension_type(_Unknown())
    yield _Unknown()
    pa.unregister_extension_type("test.unknown_ext")


def _storage_of(typ: pa.DataType) -> pa.DataType:
    return typ.storage_type


EXTENSIONS: dict[str, Callable[[], pa.DataType]] = {"opaque": _opaque, "tensor": _tensor}


@pytest.mark.parametrize("kind", EXTENSIONS)
def test_free_text_extension_is_written_as_its_clean_storage(kind: str) -> None:
    typ = EXTENSIONS[kind]()
    out = output_schema(_dirty(typ))
    got = out.field("n").type
    assert not isinstance(got, pa.BaseExtensionType)
    assert CANARY not in out.serialize().to_pybytes()
    assert CANARY not in b"".join(schema_texts(out))
    assert got.equals(typ.storage_type)


def test_python_registered_extension_is_written_as_its_storage(unknown_ext) -> None:
    out = output_schema(pa.schema([pa.field("n", unknown_ext)]))
    assert out.field("n").type == pa.int64()
    assert CANARY not in out.serialize().to_pybytes()


def test_extension_branch_applies_inside_nested_types() -> None:
    out = output_schema(pa.schema([pa.field("n", pa.list_(pa.field("item", _opaque())))]))
    assert CANARY not in out.serialize().to_pybytes()


ALLOWED_EXTENSIONS = {"uuid": pa.uuid, "bool8": pa.bool8, "json": pa.json_}


@pytest.mark.parametrize("kind", ALLOWED_EXTENSIONS)
def test_parameterless_extension_is_kept(kind: str) -> None:
    typ = ALLOWED_EXTENSIONS[kind]()
    out = output_schema(pa.schema([pa.field("n", typ)]))
    assert out.field("n").type == typ
    assert isinstance(out.field("n").type, pa.BaseExtensionType)


def test_extension_columns_write_and_read_back(tmp_path: Path) -> None:
    arr = pa.ExtensionArray.from_storage(
        _tensor(), pa.array([[1.0, 2.0], [3.0, 4.0]], pa.list_(pa.float64(), 2))
    )
    table = pa.table({"t": arr})
    out = output_table(table)
    path = tmp_path / "t.parquet"
    pq.write_table(out, path)
    assert pq.read_table(path).column("t").to_pylist() == [[1.0, 2.0], [3.0, 4.0]]
    assert CANARY not in path.read_bytes()


# -- index columns -------------------------------------------------------------------------------

PERIOD_FRAME = pd.DataFrame(
    {
        "a": [1, 2, 3],
        "p": pd.period_range("2020-01", periods=3, freq="M"),
        "i": pd.interval_range(0, 3),
    }
)


@pytest.mark.parametrize("index", [None, "p", "i"])
def test_period_and_interval_frames_round_trip(index: str | None) -> None:
    frame = PERIOD_FRAME if index is None else PERIOD_FRAME.set_index(index)
    table = _from_pandas(frame, preserve_index=index is not None)
    out = output_table(table)
    pd.testing.assert_frame_equal(out.to_pandas(), table.to_pandas())
    assert output_schema(table.schema).metadata == table.schema.metadata


def test_a_duplicated_index_entry_is_written_once() -> None:
    body = json.loads(CLEAN)
    body["index_columns"] = ["i"] * 5
    out = _blob(output_schema(_with_blob(json.dumps(body).encode())))
    assert out["index_columns"] == ["i"]
    assert out["column_indexes"] == [dict(COLUMN_INDEX_ENTRY, metadata={"encoding": "UTF-8"})]


def test_an_index_entry_for_a_field_with_no_column_entry_is_dropped() -> None:
    frame = pd.DataFrame({"a": [1, 2], "l": [[1], [2]]})
    schema = _from_pandas(frame, preserve_index=False).schema
    body = json.loads(schema.metadata[PD])
    body["index_columns"] = ["l"]
    out = _blob(output_schema(schema.with_metadata({PD: json.dumps(body).encode()})))
    assert out["index_columns"] == []
    assert out["column_indexes"] == []


def test_an_index_named_like_a_column_keeps_its_real_name() -> None:
    frame = pd.DataFrame({"a": [1, 2]}, index=pd.Index([5, 6], name="a"))
    table = _from_pandas(frame, preserve_index=True)
    assert output_schema(table.schema).metadata == table.schema.metadata
    assert output_table(table).to_pandas().index.name == "a"


def test_a_pandas_period_with_a_forged_frequency_is_written_as_storage() -> None:
    from pandas.core.arrays.arrow.extension_types import ArrowPeriodType

    out = output_schema(pa.schema([pa.field("n", ArrowPeriodType("DCY-CANARY"))]))
    assert out.field("n").type == pa.int64()
    assert CANARY not in out.serialize().to_pybytes()


# -- free text in type parameters ----------------------------------------------------------------

BAD_TZ = "https://user:DCY-CANARY@example.invalid/x"


def _interval(subtype: pa.DataType, closed: str = "right") -> pa.DataType:
    from pandas.core.arrays.arrow.extension_types import ArrowIntervalType

    return ArrowIntervalType(subtype, closed)


def _written(typ: pa.DataType, tmp_path: Path) -> tuple[pa.Table, bytes]:
    """Write one column of `typ` through the output rule and read the file back."""
    if isinstance(typ, pa.BaseExtensionType):
        sub = typ.storage_type[0].type
        ends = pa.array([0, 1], pa.int64()).cast(sub)
        storage = pa.StructArray.from_arrays([ends, ends], fields=list(typ.storage_type))
        column = pa.ExtensionArray.from_storage(typ, storage)
    else:
        column = pa.array([0, 1], pa.int64()).cast(typ)
    path = tmp_path / "t.parquet"
    pq.write_table(output_table(pa.table({"c": column})), path)
    return pq.read_table(path), path.read_bytes()


def test_a_timestamp_with_free_text_in_its_zone_loses_the_zone(tmp_path: Path) -> None:
    back, raw = _written(pa.timestamp("us", BAD_TZ), tmp_path)
    assert back.schema.field("c").type == pa.timestamp("us")
    assert CANARY not in raw


@pytest.mark.parametrize("tz", ["UTC", "Europe/Paris", "+05:30", "America/New_York"])
def test_a_timestamp_with_a_known_zone_keeps_it(tz: str) -> None:
    typ = pa.timestamp("ns", tz)
    assert output_schema(pa.schema([pa.field("c", typ)])).field("c").type == typ


@pytest.mark.parametrize("tz", ["", "bad", "utc", "../../etc/passwd", "x" * 80, BAD_TZ])
def test_unknown_zone_text_is_never_kept(tz: str) -> None:
    out = output_schema(pa.schema([pa.field("c", pa.timestamp("s", tz))])).field("c").type
    assert out == pa.timestamp("s")


def test_a_zone_in_a_nested_or_dictionary_type_is_checked() -> None:
    bad = pa.timestamp("s", BAD_TZ)
    schema = pa.schema(
        [
            pa.field("l", pa.list_(bad)),
            pa.field("s", pa.struct([pa.field("t", bad)])),
            pa.field("m", pa.map_(pa.string(), bad)),
            pa.field("d", pa.dictionary(pa.int8(), bad)),
        ]
    )
    assert CANARY not in output_schema(schema).serialize().to_pybytes()


def test_an_interval_with_a_free_text_zone_subtype_is_written_as_storage(tmp_path: Path) -> None:
    typ = _interval(pa.timestamp("us", BAD_TZ))
    out = output_schema(pa.schema([pa.field("c", typ)])).field("c").type
    assert not isinstance(out, pa.BaseExtensionType)
    back, raw = _written(typ, tmp_path)  # pq.read_table must succeed
    assert CANARY not in raw
    assert back.num_rows == 2


def test_an_interval_with_a_known_zone_subtype_is_kept() -> None:
    typ = _interval(pa.timestamp("us", "UTC"))
    assert output_schema(pa.schema([pa.field("c", typ)])).field("c").type == typ


def test_the_pandas_blob_never_carries_unknown_zone_text() -> None:
    table = pa.table({"c": pa.array([0], pa.int64()).cast(pa.timestamp("us", BAD_TZ))})
    meta = table.schema.with_metadata({PD: b"{}"}).metadata
    out = output_schema(table.schema.with_metadata(meta))
    assert CANARY not in out.serialize().to_pybytes()
