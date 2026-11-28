"""Mapping cells compare by content, not key order; a categorical decodes only the used categories."""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.internal.cell_identity import distinct_values, identity_facts
from decoy_engine.internal.cell_text import UnreadableCellError, column_text

A = {"id": 1, "tags": ["x", "y"], "inner": {"p": 1, "q": 2}}
A_REORDERED = {"inner": {"q": 2, "p": 1}, "tags": ["x", "y"], "id": 1}


def _objects(*cells: object) -> pd.Series:
    return pd.Series(list(cells), dtype=object)


def identity_counts(src: pd.Series, out: pd.Series) -> tuple[int, int]:
    facts = identity_facts(src, out)
    return facts.comparable, facts.identical


def _alike(src: pd.Series, out: pd.Series) -> bool:
    """Every row of the two columns is the same value (what equal text keys used to say)."""
    return identity_facts(src, out).all_same


def test_identity_counts_ignore_dict_key_order() -> None:
    assert identity_counts(_objects(A, "a@b.c"), _objects(A_REORDERED, "a@b.c")) == (2, 2)


def test_a_dict_with_a_changed_value_still_differs() -> None:
    changed = {**A_REORDERED, "id": 2}
    assert identity_counts(_objects(A), _objects(changed)) == (1, 0)


def test_source_distinct_counts_reordered_dicts_once() -> None:
    assert distinct_values(_objects(A, A_REORDERED)) == 1


def test_dict_key_order_is_not_a_change() -> None:
    assert _alike(_objects(A, "a@b.c"), _objects(A_REORDERED, "a@b.c"))


def test_a_dict_with_a_changed_value_is_kept_apart() -> None:
    assert not _alike(_objects(A), _objects({**A, "id": 2}))


def _bytes_categorical(cells: list[bytes]) -> pd.Series:
    return pd.Series(pd.Categorical(cells, categories=[b"ok@x.io", b"\xff\xfe", b"two@x.io"]))


def test_an_unused_invalid_category_does_not_fail_the_decode() -> None:
    kept = _bytes_categorical([b"ok@x.io", b"two@x.io", b"ok@x.io"])
    assert list(column_text(kept)) == ["ok@x.io", "two@x.io", "ok@x.io"]


def test_a_filtered_out_invalid_category_does_not_fail_the_decode() -> None:
    column = _bytes_categorical([b"ok@x.io", b"\xff\xfe", b"two@x.io"])
    kept = column[column != b"\xff\xfe"]
    assert list(column_text(kept)) == ["ok@x.io", "two@x.io"]


def test_a_used_invalid_category_still_raises() -> None:
    with pytest.raises(UnreadableCellError):
        column_text(_bytes_categorical([b"ok@x.io", b"\xff\xfe"]))


def _array_cell(mapping: dict[str, object]) -> np.ndarray:
    cell = np.empty(1, dtype=object)
    cell[0] = mapping
    return cell


def test_dict_key_order_inside_an_array_cell_is_not_a_change() -> None:
    first = _objects(_array_cell(A))
    second = _objects(_array_cell(A_REORDERED))
    assert _alike(first, second)
    assert not _alike(first, _objects(_array_cell({**A, "id": 2})))


class _Point(NamedTuple):
    x: int
    y: int


def test_a_namedtuple_cell_equals_its_plain_tuple() -> None:
    assert _alike(_objects(_Point(1, 2)), _objects((1, 2)))


def test_a_dict_cell_is_not_equal_to_a_set_of_pairs() -> None:
    assert not _alike(_objects({"id": 1}), _objects({("id", 1)}))
    assert distinct_values(_objects({"id": 1}, {("id", 1)})) == 2


def test_equal_typed_array_cells_of_different_units_are_alike() -> None:
    seconds = np.zeros(1, dtype="timedelta64[s]")
    nanos = np.zeros(1, dtype="timedelta64[ns]")
    assert _alike(_objects(seconds), _objects(nanos))


def test_a_zero_dimensional_array_cell_compares_its_payload() -> None:
    scalar = np.array(7)
    assert identity_counts(_objects(scalar, "x"), _objects(7, "x")) == (2, 2)
    boxed = np.empty((), dtype=object)
    boxed[()] = A
    other = np.empty((), dtype=object)
    other[()] = A_REORDERED
    changed = np.empty((), dtype=object)
    changed[()] = {**A, "id": 2}
    assert _alike(_objects(boxed), _objects(other))
    assert not _alike(_objects(boxed), _objects(changed))


def test_a_duration_array_is_alike_in_every_unit() -> None:
    one_second = np.array([1], dtype="timedelta64[s]")
    in_millis = np.array([1000], dtype="timedelta64[ms]")
    assert _alike(_objects(one_second, "x"), _objects(in_millis, "x"))


def test_an_int_array_equals_an_object_array_of_the_same_ints() -> None:
    typed = np.array([1, 2])
    boxed = np.empty(2, dtype=object)
    boxed[:] = [1, 2]
    assert _alike(_objects(typed, "x"), _objects(boxed, "x"))


def test_a_zero_dimensional_array_cell_survives_the_identity_check() -> None:
    cells = _objects(np.array(7), "x")
    assert identity_counts(cells, _objects(np.array(7), "x")) == (2, 2)
    assert distinct_values(cells) == 2


def test_a_zero_dimensional_nat_is_not_comparable() -> None:
    nat = np.array(np.datetime64("NaT"))
    assert identity_counts(_objects(nat, "x"), _objects(nat, "x")) == (1, 1)
    assert distinct_values(_objects(nat, "x")) == 1


def test_identity_counts_walk_both_sides_when_the_dtypes_differ() -> None:
    lists = _objects([1, 2], [3])
    arrow = pd.Series(pd.arrays.ArrowExtensionArray(pa.array([[1, 2], [3]])))
    assert lists.dtype != arrow.dtype
    assert identity_counts(lists, arrow) == (2, 2)


def test_source_distinct_walks_a_datetime_column() -> None:
    column = pd.Series(pd.to_datetime(["2020-01-01", None, "2020-01-01", "2020-01-02"]))
    assert distinct_values(column) == 2
