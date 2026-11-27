"""Owner question Q6, answer A (the plan's written default): a column that holds dates inside a
list, struct, map or dictionary of those is refused by type in V1, whether the dates are inside
the calendar or not (DATE-RANGE-SENTINEL S5, section 4.4b, AT-V3 and AT-V5).

If the owner picks answer B or C, this file and the commits that add it change; the gate tests in
`test_source_date_type_gate.py` do not."""

from __future__ import annotations

import pyarrow as pa
import pytest

from decoy_engine import reasons
from tests.unit.io.test_source_date_type_gate import (
    CODE,
    FAR_DAY,
    assert_refused_by_type,
    one,
    refusal,
)

OFFSETS = pa.array([0, 1, 3], pa.int32())


def _far(days: list[int]) -> pa.Array:
    return pa.array(days, pa.date32())


def _shapes(days: list[int]) -> dict[str, tuple[pa.Array, str]]:
    values = _far(days)
    entries = pa.StructArray.from_arrays([values.slice(0, 2)], names=["when"])
    return {
        "list": (pa.ListArray.from_arrays(OFFSETS, values), "list"),
        "large_list": (
            pa.LargeListArray.from_arrays(pa.array([0, 1, 3], pa.int64()), values),
            "large_list",
        ),
        "fixed_size_list": (
            pa.FixedSizeListArray.from_arrays(values.slice(0, 2), 1),
            "fixed_size_list",
        ),
        "struct": (entries, "struct"),
        "list_of_struct": (
            pa.ListArray.from_arrays(OFFSETS, pa.StructArray.from_arrays([values], names=["when"])),
            "list",
        ),
        "map": (pa.MapArray.from_arrays(OFFSETS, pa.array(["a", "b", "c"]), values), "map"),
        "list_of_dictionary": (
            pa.ListArray.from_arrays(
                OFFSETS,
                pa.DictionaryArray.from_arrays(pa.array([0, 0, 0], pa.int8()), _far([0, FAR_DAY])),
            ),
            "list",
        ),
        "dictionary_of_struct": (
            pa.DictionaryArray.from_arrays(
                pa.array([0, 1], pa.int8()),
                pa.StructArray.from_arrays([_far([0, 1])], names=["when"]),
            ),
            "dictionary",
        ),
    }


@pytest.mark.parametrize("days", [[0, 1, 2], [0, FAR_DAY, FAR_DAY]], ids=["in_calendar", "far"])
@pytest.mark.parametrize("shape", list(_shapes([0, 1, 2])))
def test_a_date_in_a_container_is_refused_by_type(shape: str, days: list[int]) -> None:
    column, kind = _shapes(days)[shape]
    assert_refused_by_type(one(column), kind)


@pytest.mark.parametrize("kind", ["struct", "list"])
def test_a_far_date_under_a_null_parent_is_refused_by_type_not_read(kind: str) -> None:
    far = _far([FAR_DAY, 0])
    if kind == "struct":
        column = pa.StructArray.from_arrays([far], names=["when"], mask=pa.array([True, False]))
    else:
        column = pa.ListArray.from_arrays(
            pa.array([0, 1, 2], pa.int32()), far, mask=pa.array([True, False])
        )
    assert_refused_by_type(one(column), kind)


def test_a_sliced_map_whose_far_row_is_outside_the_slice_is_refused_with_no_count() -> None:
    """AT-V5: the S5 head counted the hidden row and reported one cell. The contract is by type."""
    column = pa.MapArray.from_arrays(
        pa.array([0, 1, 2], pa.int32()), pa.array(["a", "b"]), _far([FAR_DAY, 3])
    ).slice(1, 1)
    assert_refused_by_type(one(column), "map")
    exc = refusal(one(column))
    assert exc is not None and not hasattr(exc, "count")
    assert str(exc) == (
        f"[{CODE}] {reasons.get('runtime', CODE).summary} Table 't', column 'n', type kind map. "
        "Drop the column, select it out, or cast it to a plain date or text column before the run."
    )
