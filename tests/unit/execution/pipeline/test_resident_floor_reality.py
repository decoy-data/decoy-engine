"""The footer floor is never above what the driver then holds.

The isolated readback refuses a staged output only when `lower_bound_bytes` over its Parquet
footer (rows and Arrow schema, nothing decoded) is above the kill ceiling. A floor above the
measured bytes of the decoded table for any Arrow type would refuse a run that completes, so
each type family is written through the child's own sink and the floor is held against the
buffers `pq.read_table` returns, for tables with and without nulls, empty tables and tables
with several row groups. This is an enumerated corpus, not a generative property test.

Mutation: raising the string offset width in `_lazy_column_bytes` from 4 to 16 turns the
short-string rows red.
"""

from __future__ import annotations

import datetime
import decimal
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.execution._isolated_common import StagingSink
from decoy_engine.execution.pipeline import lazy_spec, lower_bound_bytes, resident_spec

_ROWS = 5
_NULL_AT = (1, 3)
_DAY = datetime.date(2020, 1, 1)
_MOMENT = datetime.datetime(2020, 1, 1, 12, 0, 0)
_UTC = datetime.timezone.utc
_INTS = [1, 2, 3, 4, 5]
_LISTS = [[1], [2, 3], [], [4], [5, 6]]
_SHORT = ["a", "b", "c", "d", "e"]

# Each family: the Arrow type and five values. The strings are short on purpose: a floor that
# charges more than the 4-byte offset per row is above reality for them.
_CORPUS: dict[str, tuple[pa.DataType, list[Any]]] = {
    **{f"int{w}": (getattr(pa, f"int{w}")(), _INTS) for w in (8, 16, 32, 64)},
    **{f"uint{w}": (getattr(pa, f"uint{w}")(), _INTS) for w in (8, 16, 32, 64)},
    "float16": (pa.float16(), [1.0, 2.0, 3.0, 4.0, 5.0]),
    "float32": (pa.float32(), [1.5, 2.5, 3.5, 4.5, 5.5]),
    "float64": (pa.float64(), [1.5, 2.5, 3.5, 4.5, 5.5]),
    "bool": (pa.bool_(), [True, False, True, False, True]),
    "decimal128": (pa.decimal128(10, 2), [decimal.Decimal(f"{i}.25") for i in range(5)]),
    "date32": (pa.date32(), [_DAY + datetime.timedelta(days=i) for i in range(5)]),
    "timestamp": (pa.timestamp("us"), [_MOMENT + datetime.timedelta(hours=i) for i in range(5)]),
    "timestamp_tz": (
        pa.timestamp("us", tz="UTC"),
        [(_MOMENT + datetime.timedelta(hours=i)).replace(tzinfo=_UTC) for i in range(5)],
    ),
    "duration": (pa.duration("us"), [datetime.timedelta(seconds=i) for i in range(5)]),
    "string": (pa.string(), _SHORT),
    "large_string": (pa.large_string(), _SHORT),
    "binary": (pa.binary(), [s.encode() for s in _SHORT]),
    "large_binary": (pa.large_binary(), [s.encode() for s in _SHORT]),
    "fixed_size_binary": (pa.binary(2), [(s * 2).encode() for s in _SHORT]),
    **{
        f"dictionary_{index}": (
            pa.dictionary(getattr(pa, index)(), pa.string()),
            ["a", "b", "a", "c", "b"],
        )
        for index in ("int8", "int16", "int32", "int64")
    },
    "struct": (
        pa.struct([("x", pa.int64()), ("y", pa.string())]),
        [{"x": i, "y": "a"} for i in range(5)],
    ),
    "list": (pa.list_(pa.int64()), _LISTS),
    "large_list": (pa.large_list(pa.int64()), _LISTS),
    "map": (pa.map_(pa.string(), pa.int64()), [[("a", 1)], [], [("b", 2)], [("c", 3)], []]),
    "fixed_size_list": (pa.list_(pa.int64(), 2), [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10]]),
    "null": (pa.null(), [None] * 5),
}
# The two types whose floor is zero on purpose: a null column holds no buffer, and the child
# length of a fixed-size list is not in the schema, so a floor can claim nothing for it.
_ZERO_FLOOR = {"null", "fixed_size_list"}


def _array(kind: str, nulls: bool) -> pa.Array:
    arrow_type, values = _CORPUS[kind]
    if kind == "null":
        return pa.nulls(_ROWS)
    # The writer refuses a null fixed-size list, so no staged file can hold one.
    mask = [nulls and kind != "fixed_size_list" and i in _NULL_AT for i in range(_ROWS)]
    if kind == "float16":
        return pa.array(np.array(values, dtype=np.float16), mask=np.array(mask))
    return pa.array([None if m else v for m, v in zip(mask, values, strict=True)], type=arrow_type)


def _write(tmp_path: Path, table: pa.Table, *, row_groups: bool) -> Path:
    sink = StagingSink(str(tmp_path / "stage"))
    if row_groups:
        sink.write_batches("t", table.to_batches(max_chunksize=2), schema=table.schema)
    else:
        sink.write("t", table)
    return tmp_path / "stage" / "t.parquet"


def _floor_and_measured(path: Path) -> tuple[int, int]:
    footer = pq.ParquetFile(path)
    spec = lazy_spec(footer.metadata.num_rows, footer.schema_arrow, charge_pandas=False)
    measured = resident_spec(pq.read_table(path), charge_pandas=False).resident_input_bytes
    assert measured is not None
    return lower_bound_bytes([spec]), measured


@pytest.mark.parametrize("row_groups", [False, True], ids=["one_group", "several_groups"])
@pytest.mark.parametrize("nulls", [False, True], ids=["no_nulls", "with_nulls"])
@pytest.mark.parametrize("kind", sorted(_CORPUS))
def test_the_floor_is_never_above_the_measured_bytes(
    kind: str, nulls: bool, row_groups: bool, tmp_path: Path
) -> None:
    table = pa.table({"c": _array(kind, nulls)})
    floor, measured = _floor_and_measured(_write(tmp_path, table, row_groups=row_groups))
    assert floor <= measured, (kind, floor, measured)
    if kind in _ZERO_FLOOR:
        assert floor == 0  # the documented zero floor, on nonempty input
    else:
        assert floor > 0  # non-vacuity: a pricing rule exists for this family


@pytest.mark.parametrize("kind", sorted(_CORPUS))
def test_an_empty_table_has_a_zero_floor(kind: str, tmp_path: Path) -> None:
    table = pa.table({"c": pa.array([], type=_CORPUS[kind][0])})
    floor, measured = _floor_and_measured(_write(tmp_path, table, row_groups=False))
    assert floor == 0 <= measured


def test_the_floor_over_several_columns_is_the_sum_of_the_columns(tmp_path: Path) -> None:
    table = pa.table(
        {"i": _array("int64", False), "s": _array("string", False), "d": _array("date32", True)}
    )
    floor, measured = _floor_and_measured(_write(tmp_path, table, row_groups=True))
    assert floor == _ROWS * (8 + 4 + 4)
    assert floor <= measured
