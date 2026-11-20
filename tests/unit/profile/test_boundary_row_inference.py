"""Row n + 1 never changes the type of the sample.

A text source (CSV) infers each column's type from the rows it parses. The profiled frame is
parsed from exactly `n` rows. The proof that row `n + 1` exists is a separate read whose frame
is dropped, so a late "outside" or empty cell cannot turn an int column into object or float.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from decoy_engine.profile import profile_source
from decoy_engine.profile._readers import build_profile_source
from tests._declared_schema import declare_rest

N = 10
BODIES = {
    "text_after_ints": "outside",
    "empty_after_ints": "",
}


def _csv(late: str) -> bytes:
    rows = [f"{i},{i}" for i in range(1, N + 1)] + [f"{N + 1},{late}"]
    return ("id,v\n" + "\n".join(rows) + "\n").encode()


def _config(path: Path) -> dict[str, Any]:
    return declare_rest(
        {
            "global_settings": {"seed": 0},
            "sources": {
                "t": {"type": "file", "format": "csv", "path": str(path), "has_header": True}
            },
            "relationships": [],
        }
    )


@pytest.mark.parametrize("late", sorted(BODIES), ids=str)
def test_profile_source_dtype_ignores_row_n_plus_1(tmp_path: Path, late: str) -> None:
    path = tmp_path / "f.csv"
    path.write_bytes(_csv(BODIES[late]))
    table = profile_source(_config(path), sample_rows=N, seed=0).tables[0]
    column = next(c for c in table.columns if c.name == "v")
    assert column.dtype == "int64"
    assert column.sampled is True
    assert column.is_candidate_key_sampled is False


@pytest.mark.parametrize("late", sorted(BODIES), ids=str)
def test_local_csv_sample_frame_dtype_ignores_row_n_plus_1(tmp_path: Path, late: str) -> None:
    path = tmp_path / "f.csv"
    path.write_bytes(_csv(BODIES[late]))
    source = build_profile_source(
        {"type": "file", "format": "csv", "path": str(path), "has_header": True}
    )
    frame = source.sample_frame(N)
    assert len(frame) == N
    assert str(frame["v"].dtype) == "int64"


def _with_malformed_row_n_plus_1() -> bytes:
    rows = [f"{i},{i}" for i in range(1, N + 1)] + ["11,1,2,3"]
    return ("id,v\n" + "\n".join(rows) + "\n").encode()


def test_malformed_row_n_plus_1_still_profiles_and_reads_as_a_sample(tmp_path: Path) -> None:
    """The proof read only asks whether a row exists past n. A row there that does not
    parse counts as a row, and it never fails a profile whose first n rows are valid."""
    path = tmp_path / "f.csv"
    path.write_bytes(_with_malformed_row_n_plus_1())
    table = profile_source(_config(path), sample_rows=N, seed=0).tables[0]
    assert [c.name for c in table.columns] == ["id", "v"]
    for column in table.columns:
        assert column.sampled is True
        assert column.is_candidate_key_sampled is False
        assert column.dtype == "int64"
