"""AT-13 and AT-16: the first-chunk profile is a sample; the empty one is not."""

from __future__ import annotations

import pyarrow as pa
import pytest

from decoy_engine.execution._chunked_profile import empty_input_profile, first_chunk_profile
from decoy_engine.profile import profile_hash


def _slice() -> pa.Table:
    return pa.table({"id": list(range(1_000)), "v": [i % 4 for i in range(1_000)]})


@pytest.mark.parametrize("carried", [frozenset(), frozenset({"id"})])
def test_first_chunk_columns_are_a_sample(carried: frozenset[str]) -> None:
    profile = first_chunk_profile(_slice(), table="t", engine_version="0", carried=carried)
    columns = profile.tables[0].columns
    assert {c.name for c in columns} == {"id", "v"}
    for col in columns:
        assert col.sampled is True
        assert col.is_candidate_key_sampled is False


def test_first_chunk_keeps_table_row_count_exact_flag() -> None:
    table = first_chunk_profile(_slice(), table="t", engine_version="0").tables[0]
    assert table.row_count == 1_000
    assert table.row_count_exact is True  # execution/capacity.py reads it


def test_empty_input_profile_is_whole_and_unchanged() -> None:
    config = {"tables": [{"name": "t", "columns": [{"name": "id"}, {"name": "v"}]}]}
    profile = empty_input_profile(config, table="t", engine_version="0")
    for col in profile.tables[0].columns:
        assert col.sampled is False
    # AT-16 characterization: captured on the pre-change base.
    assert profile_hash(profile) == _EMPTY_HASH


# Moved once by COLUMN-SHAPE E1a: each hashed column now carries its `shape` (here `unknown`).
_EMPTY_HASH = "190c85ce1c9b35f07781b1c2c6ffdfe5937708ff4a24030c4076eab5a0e14155"
