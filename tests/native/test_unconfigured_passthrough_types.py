"""B8 acceptance tests 3 and 4: unconfigured columns of every Arrow type.

Test 3 runs the whole type catalogue, with and without a null, as an unconfigured column
beside redact, truncate and hash columns on the native route and on the forced oracle
route. Test 4 puts more than thirty unusual columns in one table. The column must come
back as the source column and field in both runs; a type that diverges stops the build for
a plan revision, it is not filtered out.
"""

from __future__ import annotations

import datetime as dt
import decimal
import functools
import io
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from decoy_engine import run_mask_pipeline_chunked
from decoy_engine.execution import run_pipeline
from decoy_engine.execution._fk_keys import _rebuilds_with_source_type
from tests.native._b8_support import (
    Run,
    assert_same_as_oracle,
    identical,
    run_pair,
    same_field,
)
from tests.native._chunked_entry_support import (
    NEEDS_COMPANION,
    faker_col,
    hash_col,
    key_provider,
    redact,
    truncate,
)
from tests.native._rev9_type_catalogue import CATALOGUE
from tests.unit.execution._auto_chunk_support import (
    TABLE,
    fixed_list_job,
    make_cfg,
    pass_col,
    redact_col,
    write_source,
)

_PARAMS = [(name, null) for name in CATALOGUE for null in (False, True)]
_IDS = [f"{name}-{'null' if null else 'nonull'}" for name, null in _PARAMS]


def _strs(values: list[str | None]) -> dict[str, pa.Array]:
    return {
        "s": pa.array(values, pa.string()),
        "t": pa.array([None if v is None else v * 2 for v in values], pa.string()),
        "h": pa.array(values, pa.string()),
    }


def _source(arr: pa.Array, values: list[str | None]) -> pa.Table:
    return pa.table({**_strs(values), "x": arr})


def _o3_narrowed(table: pa.Table) -> pa.Table:
    """O3: a pass-through `large_string` column leaves the route as `string` while its values
    fit 32-bit offsets, so that is the carried column's expected type."""
    for i, field in enumerate(table.schema):
        if pa.types.is_large_string(field.type):
            table = table.set_column(
                i, field.with_type(pa.string()), table.column(i).cast(pa.string())
            )
    return table


def _x_column(run: Run) -> list[pa.ChunkedArray]:
    return [t.column("x") for t in run.out]


@NEEDS_COMPANION
@pytest.mark.parametrize(("name", "null"), _PARAMS, ids=_IDS)
def test_type_catalogue_as_an_unconfigured_column(name: str, null: bool) -> None:
    arr = CATALOGUE[name](null)
    names: list[str | None] = ["a", "b", "c", "d", "e"]
    full = _source(arr, names)
    empty = pa.Table.from_batches([], schema=full.schema)
    chunks = [full, empty, full]
    native, forced = run_pair([redact("s"), truncate("t"), hash_col("h")], chunks)
    assert_same_as_oracle(native, forced)
    for out, src in zip(native.out, map(_o3_narrowed, chunks), strict=True):
        assert same_field(out.schema.field("x"), src.schema.field("x"))
        assert identical(out.select(["x"]), src.select(["x"]))


# ---------------------------------------------------------------------------
# Test 4
# ---------------------------------------------------------------------------

_SIZES = (5, 3, 4, 1, 4)
_I64MIN = -(2**63)
_I64MAX = 2**63 - 1
# The reader refuses a date outside years 1 to 9999 (DATE-RANGE-SENTINEL S5), so the extremes
# here are the edges of that calendar. The ns columns keep the int64 extremes: they lie in 1677
# to 2262.
_DAY = 86_400
_FIRST_DAY, _LAST_DAY = -719_162, 2_932_896
_PER_SECOND = {"s": 1, "ms": 10**3, "us": 10**6}


def _timestamp_extremes(unit: str, zoned: bool) -> list[int]:
    """Five values holding both ends of the calendar; a zoned column stays a day inside each end
    so the local date fits in any zone."""
    if unit == "ns":
        return [_I64MIN, _I64MAX, 0, _I64MIN + 1, 7]
    per = _PER_SECOND[unit]
    low = (_FIRST_DAY + 1) * _DAY * per if zoned else _FIRST_DAY * _DAY * per
    high = _LAST_DAY * _DAY * per if zoned else (_LAST_DAY + 1) * _DAY * per - 1
    return [low, high, 0, low + 1, 7]


def _per_chunk(make: Any) -> list[pa.Array]:
    return [make(i, n) for i, n in enumerate(_SIZES)]


def _vals(n: int, i: int, fn: Any, null_at: int | None = 1) -> list[Any]:
    return [
        None if (null_at is not None and j == null_at and n > 1) else fn(i, j) for j in range(n)
    ]


def _dict_array(i: int, n: int, values: list[Any], index_type: Any = None) -> pa.Array:
    index_type = index_type or pa.int32()
    idx = [None if j == 1 else j % len(values) for j in range(n)]
    return pa.DictionaryArray.from_arrays(pa.array(idx, index_type), pa.array(values))


def _unusual() -> dict[str, list[pa.Array]]:
    cols: dict[str, list[pa.Array]] = {}
    for width in ("int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64"):
        t = getattr(pa, width)()
        cols[f"int_{width}"] = _per_chunk(
            lambda i, n, t=t: pa.array(_vals(n, i, lambda i, j: j), t)
        )
    cols["uint64_max"] = _per_chunk(
        lambda i, n: pa.array([2**64 - 1 - j for j in range(n)], pa.uint64())
    )
    cols["int64_above_2_53"] = _per_chunk(
        lambda i, n: pa.array(_vals(n, i, lambda i, j: 2**53 + 1 + j), pa.int64())
    )
    cols["float16"] = _per_chunk(lambda i, n: pa.array([1.5] * n, pa.float16()))
    cols["float_nan_inf"] = _per_chunk(
        lambda i, n: pa.array(
            [[float("nan"), float("inf"), float("-inf"), -0.0, 1.5][j % 5] for j in range(n)],
            pa.float64(),
        )
    )
    cols["large_string"] = _per_chunk(
        lambda i, n: pa.array([f"l{j}" for j in range(n)], pa.large_string())
    )
    cols["string_view"] = _per_chunk(
        lambda i, n: pa.array([f"v{j}" for j in range(n)], pa.string_view())
    )
    cols["binary_view"] = _per_chunk(
        lambda i, n: pa.array([b"b%d" % j for j in range(n)], pa.binary_view())
    )
    cols["fixed_size_binary"] = _per_chunk(
        lambda i, n: pa.array([b"%02d" % j for j in range(n)], pa.binary(2))
    )
    cols["decimal128_38_10"] = _per_chunk(
        lambda i, n: pa.array(
            [decimal.Decimal(f"{10**27 + j}.0123456789") for j in range(n)], pa.decimal128(38, 10)
        )
    )
    cols["decimal256_1e60"] = _per_chunk(
        lambda i, n: pa.array([decimal.Decimal(10**60 + j) for j in range(n)], pa.decimal256(76, 0))
    )
    cols["date32_far"] = _per_chunk(
        lambda i, n: pa.array([_LAST_DAY - j for j in range(n)], pa.date32())
    )
    cols["date32_ordinary"] = _per_chunk(
        lambda i, n: pa.array([dt.date(2020, 1, 1 + j) for j in range(n)], pa.date32())
    )
    cols["date64_far"] = _per_chunk(
        lambda i, n: pa.array([(_LAST_DAY - j) * _DAY * 1000 for j in range(n)], pa.date64())
    )
    cols["time64_ns_unaligned"] = _per_chunk(
        lambda i, n: pa.array([1000 * j + 1 for j in range(n)], pa.time64("ns"))
    )
    for unit in ("s", "ms", "us", "ns"):
        for tz in (None, "America/New_York", "+05:30"):
            t = pa.timestamp(unit, tz=tz)
            cols[f"ts_{unit}_{tz or 'naive'}"] = _per_chunk(
                lambda i, n, t=t, u=unit, z=tz is not None: pa.array(
                    _timestamp_extremes(u, z)[:n] + [0] * max(0, n - 5), t
                )
            )
        d = pa.duration(unit)
        cols[f"dur_{unit}"] = _per_chunk(
            lambda i, n, d=d: pa.array([_I64MIN, _I64MAX, 0, 1, -1][:n] + [0] * max(0, n - 5), d)
        )
    cols["month_day_nano"] = _per_chunk(
        lambda i, n: pa.array(
            [pa.MonthDayNano([1, 2, j]) for j in range(n)], pa.month_day_nano_interval()
        )
    )
    for itype in (pa.int8(), pa.int32(), pa.uint64()):
        cols[f"dict_str_{itype}"] = _per_chunk(
            lambda i, n, itype=itype: _dict_array(i, n, [f"d{i}{k}" for k in range(3)], itype)
        )
    cols["dict_null_in_dictionary"] = _per_chunk(lambda i, n: _dict_array(i, n, ["a", None, "c"]))
    cols["dict_duplicate"] = _per_chunk(lambda i, n: _dict_array(i, n, ["a", "a", "b"]))
    cols["dict_nan"] = _per_chunk(lambda i, n: _dict_array(i, n, [1.0, float("nan"), 2.0]))
    cols["dict_differs_per_chunk"] = _per_chunk(
        lambda i, n: _dict_array(i, n, [f"chunk{i}-{k}" for k in range(i + 2)])
    )
    cols["list_int"] = _per_chunk(
        lambda i, n: pa.array([[j, j + 1] for j in range(n)], pa.list_(pa.int64()))
    )
    cols["struct"] = _per_chunk(
        lambda i, n: pa.array(
            [{"a": j, "b": f"s{j}"} for j in range(n)],
            pa.struct([("a", pa.int64()), ("b", pa.string())]),
        )
    )
    cols["map"] = _per_chunk(
        lambda i, n: pa.array([[(f"k{j}", j)] for j in range(n)], pa.map_(pa.string(), pa.int64()))
    )
    cols["union"] = _per_chunk(_dense_union)
    cols["extension_uuid"] = _per_chunk(
        lambda i, n: pa.ExtensionArray.from_storage(
            pa.uuid(), pa.array([bytes([j]) * 16 for j in range(n)], pa.binary(16))
        )
    )
    cols["field_metadata"] = _per_chunk(lambda i, n: pa.array([f"m{j}" for j in range(n)]))
    cols["non_nullable"] = _per_chunk(lambda i, n: pa.array(list(range(n)), pa.int32()))
    return cols


def _dense_union(i: int, n: int) -> pa.Array:
    types = pa.array([j % 2 for j in range(n)], pa.int8())
    offsets = pa.array([j // 2 for j in range(n)], pa.int32())
    ints = pa.array(list(range((n + 1) // 2)), pa.int64())
    strs = pa.array([f"u{j}" for j in range(n // 2 + 1)], pa.string())
    return pa.UnionArray.from_dense(types, offsets, [ints, strs])


def _wide_chunks() -> tuple[list[pa.Table], pa.Schema]:
    unusual = _unusual()
    fields: list[pa.Field] = [
        pa.field("s", pa.string()),
        pa.field("t", pa.string()),
        pa.field("h", pa.string()),
        pa.field("f", pa.string()),
    ]
    for name, arrays in unusual.items():
        field = pa.field(name, arrays[0].type)
        if name == "field_metadata":
            field = field.with_metadata({b"owner": b"b8"})
        if name == "non_nullable":
            field = field.with_nullable(False)
        fields.append(field)
    schema = pa.schema(fields)
    chunks = []
    for i, n in enumerate(_SIZES):
        arrays = [
            pa.array([f"s{i}{j}" for j in range(n)]),
            pa.array([f"abcdef{i}{j}" for j in range(n)]),
            pa.array([f"h{i}{j}" for j in range(n)]),
            pa.array([f"f{i}{j}" for j in range(n)]),
            *[arrs[i] for arrs in unusual.values()],
        ]
        chunks.append(pa.Table.from_arrays(arrays, schema=schema))
    return chunks, schema


@NEEDS_COMPANION
def test_many_unusual_columns_in_one_table() -> None:
    chunks, schema = _wide_chunks()
    unconfigured = sorted(set(schema.names) - {"s", "t", "h", "f"})
    assert len(unconfigured) >= 30
    native, forced = run_pair([redact("s"), truncate("t"), hash_col("h"), faker_col("f")], chunks)
    assert_same_as_oracle(native, forced)
    for result, out, src in zip(native.sink, native.out, map(_o3_narrowed, chunks), strict=True):
        (warning,) = result.warnings
        # A name list in a warning detail is joined by the QualityWarning constructor.
        assert warning.detail["undeclared_columns"] == ", ".join(unconfigured)
        for name in unconfigured:
            assert same_field(out.schema.field(name), src.schema.field(name)), name
            assert identical(out.select([name]), src.select([name])), name


# ---------------------------------------------------------------------------
# CHUNKED-STRUCT: untouched nested columns keep their source type on every route that
# rebuilds output from pandas (docs/plans/2026-11-21-chunked-struct.md, AT-2 and AT-4).
# ---------------------------------------------------------------------------

_NESTED = ("addr", "tags", "attrs")
_ADDR = pa.struct([("city", pa.string()), ("zip", pa.int32())])


def _nested_table(
    nulls: set[int] | None = None, rows: int = 3, *, email: bool = True, all_null: bool = False
) -> pa.Table:
    """Fixture F: rows 0 and 1 hold cells, the rest are null in every nested column."""
    nulls = set(range(rows)) if all_null else (nulls if nulls is not None else {2})
    cols: dict[str, pa.Array] = {}
    if email:
        cols["email"] = pa.array([f"u{i}@x.test" for i in range(rows)], pa.string())
    cols["addr"] = pa.array(
        [None if i in nulls else {"city": f"c{i}", "zip": i} for i in range(rows)], _ADDR
    )
    cols["tags"] = pa.array(
        [None if i in nulls else [f"t{i}", "x"] for i in range(rows)], pa.list_(pa.string())
    )
    cols["attrs"] = pa.array(
        [None if i in nulls else [("k", f"v{i}")] for i in range(rows)],
        pa.map_(pa.string(), pa.string()),
    )
    return pa.table(cols)


def _run(table: pa.Table, call: Callable[[dict[str, Any]], pa.Table]) -> pa.Table:
    """`call` gets a config whose source file holds `table` (the profile reads the file)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = write_source(table, Path(tmp) / "t.parquet")
        cols = [redact_col(n) if n == "email" else pass_col(n) for n in table.column_names]
        return call(make_cfg(cols, path=path))


def _resident(table: pa.Table) -> pa.Table:
    return _run(
        table,
        lambda cfg: run_pipeline(
            cfg, sources={TABLE: table}, engine_version="chunked-struct-test", auto_chunk=False
        ).outputs[TABLE],
    )


def _oracle(table: pa.Table, chunk: int) -> pa.Table:
    chunks = [table.slice(i, chunk) for i in range(0, table.num_rows, chunk)]
    return _run(
        table,
        lambda cfg: pa.concat_tables(
            list(
                run_mask_pipeline_chunked(
                    cfg,
                    chunks,
                    table=TABLE,
                    source_schema=table.schema,
                    engine_version="chunked-struct-test",
                    key_provider=key_provider(),
                )
            )
        ),
    )


def _assert_nested_exact(out: pa.Table, src: pa.Table) -> None:
    names = [n for n in src.column_names if n != "email"]
    assert out.num_rows == src.num_rows
    assert out.select(names).schema == src.select(names).schema
    assert out.select(names).equals(src.select(names))


@pytest.mark.parametrize("nulls", [{2}, {0}, {0, 1, 2}])
def test_oracle_keeps_nested_types_equal_to_resident(nulls: set[int]) -> None:
    """AT-2a and AT-2b: chunk 2 leaves a one-row final chunk; the null row also goes first."""
    src = _nested_table(nulls)
    out = _oracle(src, 2)
    _assert_nested_exact(out, src)
    assert out.equals(_resident(src))


@settings(derandomize=True, max_examples=25, deadline=None)
@given(data=st.data())
def test_oracle_nested_types_property(data: st.DataObject) -> None:
    """AT-2c: row count, chunk size and null positions are drawn."""
    rows = data.draw(st.integers(1, 8))
    chunk = data.draw(st.integers(1, rows))
    nulls = {i for i in range(rows) if data.draw(st.booleans())}
    src = _nested_table(nulls, rows)
    out = _oracle(src, chunk)
    _assert_nested_exact(out, src)
    assert out.equals(_resident(src))


@pytest.mark.parametrize("name", ["addr", "tags", "attrs"])
def test_oracle_all_nested_table_keeps_rows_and_types(name: str) -> None:
    """AT-2e: no scalar column, so the rebuild has nothing for from_pandas to count rows by."""
    src = _nested_table(email=False)
    for table in (src, src.select([name])):
        out = _oracle(table, 2)
        assert out.num_rows == 3
        _assert_nested_exact(out, table)


@pytest.mark.parametrize("all_null", [False, True])
def test_resident_keeps_nested_types(all_null: bool) -> None:
    """AT-4a: int32 struct field kept; with every cell null the types do not become `null`."""
    src = _nested_table(all_null=all_null)
    out = _resident(src)
    _assert_nested_exact(out, src)
    assert out.schema.field("addr").type == _ADDR


@pytest.mark.parametrize("columns", [("attrs",), _NESTED])
def test_resident_all_nested_table_keeps_rows(columns: tuple[str, ...]) -> None:
    """AT-4b: a map-only table raised `ArrowInvalid` (length 0) on main."""
    src = _nested_table(email=False).select(list(columns))
    out = _resident(src)
    assert out.num_rows == 3
    _assert_nested_exact(out, src)


def _storable(arr: pa.Array) -> bool:
    try:
        pq.write_table(pa.table({"x": arr}), io.BytesIO())
    except pa.ArrowNotImplementedError:
        return False
    return True


_NESTED_PARAMS = [(n, null) for n, null in _PARAMS if pa.types.is_nested(CATALOGUE[n](False).type)]


@pytest.mark.parametrize(
    ("name", "null"),
    _NESTED_PARAMS,
    ids=[f"{n}-{'null' if z else 'nonull'}" for n, z in _NESTED_PARAMS],
)
def test_catalogue_nested_types_are_placed(name: str, null: bool) -> None:
    """AT-2d: a nested type Parquet can store is rebuilt exactly; a type it cannot store is
    outside the predicate. A fixed-size list with a null cell is a type Parquet stores but this
    cell it cannot: pyarrow's writer raises `ArrowNotImplementedError` before any engine code
    runs (plan section 4), so a source file cannot hold it."""
    arr = CATALOGUE[name](null)
    if not _storable(CATALOGUE[name](False)):
        assert not _rebuilds_with_source_type(arr.type)
        return
    assert _rebuilds_with_source_type(arr.type)
    if not _storable(arr):
        with pytest.raises(pa.ArrowNotImplementedError):
            pq.write_table(pa.table({"x": arr}), io.BytesIO())
        return
    src = pa.table({"email": pa.array(["a", "b", "c", "d", "e"]), "x": arr})
    resident = functools.partial(_resident, src)
    oracle = functools.partial(_oracle, src, 2)

    for run in (resident, oracle):
        out = run()
        assert out.schema.field("x").type == src.schema.field("x").type
        assert out.column("x").to_pylist() == src.column("x").to_pylist()


@pytest.mark.parametrize("auto_chunk", [False, True])
@pytest.mark.parametrize(
    ("dtype", "values", "clean"),
    [
        (pa.list_(pa.int32(), 2), [[0, 0], None, [2, 2]], [0, 0]),
        (pa.list_(pa.int64(), 1), [[0], None, [2]], [0]),
        (pa.list_(pa.string(), 2), [["a", "b"], None, ["c", "d"]], ["a", "b"]),
        (pa.list_(pa.int32(), 2), [[0, 0], None, [2, 2], None, [4, 4]], [0, 0]),
    ],
)
def test_fixed_list_resident(tmp_path, auto_chunk, dtype, values, clean):
    cfg, sources = fixed_list_job(tmp_path, dtype, values, clean)
    result = run_pipeline(cfg, sources, auto_chunk=auto_chunk, engine_version="fixed-list")
    assert str(result.outputs[TABLE]["x"].type) == str(dtype)
    assert result.outputs[TABLE]["x"].to_pylist() == values


@pytest.mark.parametrize(
    ("nulls", "redact", "mode"),
    [
        ({0}, False, "auto"),
        ({2}, False, "auto"),
        ({0, 1, 2}, False, "auto"),
        ({1}, True, "auto"),
        ({1}, False, "full_frame"),
    ],
)
def test_fixed_list_route(tmp_path, nulls, redact, mode):
    dtype = pa.list_(pa.int32(), 2)
    values = [None if i in nulls else [i, i] for i in range(3)]
    cfg, sources = fixed_list_job(tmp_path, dtype, values, [0, 0], redact=redact)
    result = run_pipeline(cfg, sources, execution_mode=mode, engine_version="fixed-list")
    assert str(result.outputs[TABLE]["x"].type) == str(dtype)
    assert result.outputs[TABLE]["x"].to_pylist() == values
