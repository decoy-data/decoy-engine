"""Mapping cells compare by content, not key order; a categorical decodes only the used categories."""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pandas as pd
import pytest

from decoy_engine.internal.cell_text import UnreadableCellError, column_text, key_text
from decoy_engine.verification.postmask._column_facts import (
    canonical_cells,
    identity_counts,
    source_distinct,
)

A = {"id": 1, "tags": ["x", "y"], "inner": {"p": 1, "q": 2}}
A_REORDERED = {"inner": {"q": 2, "p": 1}, "tags": ["x", "y"], "id": 1}


def _objects(*cells: object) -> pd.Series:
    return pd.Series(list(cells), dtype=object)


def test_identity_counts_ignore_dict_key_order() -> None:
    assert identity_counts(_objects(A, "a@b.c"), _objects(A_REORDERED, "a@b.c")) == (2, 2)


def test_a_dict_with_a_changed_value_still_differs() -> None:
    changed = {**A_REORDERED, "id": 2}
    assert identity_counts(_objects(A), _objects(changed)) == (1, 0)


def test_source_distinct_counts_reordered_dicts_once() -> None:
    assert source_distinct(_objects(A, A_REORDERED)) == 1
    assert len(set(canonical_cells(_objects(A, A_REORDERED)))) == 1


def test_text_keys_ignore_dict_key_order() -> None:
    assert key_text(_objects(A, "a@b.c")) == key_text(_objects(A_REORDERED, "a@b.c"))


def test_text_keys_keep_a_dict_with_a_changed_value_apart() -> None:
    assert key_text(_objects(A)) != key_text(_objects({**A, "id": 2}))


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


def test_text_keys_ignore_dict_key_order_inside_an_array_cell() -> None:
    first = _objects(_array_cell(A))
    second = _objects(_array_cell(A_REORDERED))
    assert key_text(first) == key_text(second)
    assert key_text(first) != key_text(_objects(_array_cell({**A, "id": 2})))


class _Point(NamedTuple):
    x: int
    y: int


def test_text_key_of_a_namedtuple_cell_renders_without_error() -> None:
    assert key_text(_objects(_Point(1, 2)))[0] == key_text(_objects((1, 2)))[0]


def test_a_dict_cell_does_not_freeze_equal_to_a_set_of_pairs() -> None:
    mapping, pairs = canonical_cells(_objects({"id": 1}, {("id", 1)}))
    assert mapping != pairs
    assert source_distinct(_objects({"id": 1}, {("id", 1)})) == 2


def test_equal_typed_array_cells_of_different_units_share_a_key() -> None:
    seconds = np.zeros(1, dtype="timedelta64[s]")
    nanos = np.zeros(1, dtype="timedelta64[ns]")
    assert key_text(_objects(seconds)) == key_text(_objects(nanos))


def test_a_zero_dimensional_array_cell_keys_its_payload() -> None:
    scalar = np.array(7)
    assert key_text(_objects(scalar, "x"))[0] is not None
    boxed = np.empty((), dtype=object)
    boxed[()] = A
    other = np.empty((), dtype=object)
    other[()] = A_REORDERED
    changed = np.empty((), dtype=object)
    changed[()] = {**A, "id": 2}
    assert key_text(_objects(boxed)) == key_text(_objects(other))
    assert key_text(_objects(boxed)) != key_text(_objects(changed))


def test_a_duration_array_keys_alike_in_every_unit() -> None:
    one_second = np.array([1], dtype="timedelta64[s]")
    in_millis = np.array([1000], dtype="timedelta64[ms]")
    assert key_text(_objects(one_second, "x")) == key_text(_objects(in_millis, "x"))


def test_an_int_array_keys_like_an_object_array_of_the_same_ints() -> None:
    typed = np.array([1, 2])
    boxed = np.empty(2, dtype=object)
    boxed[:] = [1, 2]
    assert key_text(_objects(typed, "x")) == key_text(_objects(boxed, "x"))


def test_a_zero_dimensional_array_cell_survives_the_identity_check() -> None:
    cells = _objects(np.array(7), "x")
    assert identity_counts(cells, _objects(np.array(7), "x")) == (2, 2)
    assert source_distinct(cells) == 2
