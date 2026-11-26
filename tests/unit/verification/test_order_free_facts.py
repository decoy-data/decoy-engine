"""Mapping cells compare by content, not key order; a categorical decodes only the used categories."""

from __future__ import annotations

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
