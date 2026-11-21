"""AT-12: a partial read never claims a key.

A column read that did not cover the whole source is `sampled` and carries no
candidate-key flag. "Did not cover" is computed from the fixture length, never
from the profile under test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.execution._chunked_profile import first_chunk_profile
from decoy_engine.profile import profile_source
from tests._declared_schema import declare_rest

ROWS = 25_000


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


def _write(path: Path, rows: list[str]) -> Path:
    path.write_text("id,n,u,pad\n" + "\n".join(rows) + "\n")
    return path


def _hostile(path: Path) -> Path:
    rows = [f"{i % 12000},{'' if (i > 10_000 and i % 7 == 0) else i},{i},x" for i in range(ROWS)]
    return _write(path, rows)


def _wide(path: Path) -> Path:
    pad = "w" * 280
    rows = [f"{i if i < 10_000 else i % 10_000},{i},{i},{pad}" for i in range(ROWS)]
    return _write(path, rows)


def _skewed(path: Path) -> Path:
    wide = "w" * 190
    rows = [
        f"{i if i < 10_000 else i % 10_000},{i},{i},{wide if i < 1_000 else 'x'}"
        for i in range(ROWS)
    ]
    return _write(path, rows)


@pytest.mark.parametrize("build", [_hostile, _wide, _skewed], ids=["hostile", "wide", "skewed"])
@pytest.mark.parametrize("limit", [10, 1_000, 10_000])
def test_profile_source_partial_read_claims_no_key(tmp_path: Path, build: Any, limit: int) -> None:
    path = build(tmp_path / "f.csv")
    assert limit < ROWS  # every cell is a partial read of the 25,000-row source
    table = profile_source(_config(path), sample_rows=limit, seed=0).tables[0]
    for col in table.columns:
        assert col.sampled is True, col.name
        assert col.is_candidate_key_sampled is False, col.name


@pytest.mark.parametrize("prefix", [1, 10, 999, 1_000])
@pytest.mark.parametrize("carried", [frozenset(), frozenset({"id"})])
def test_first_chunk_profile_claims_no_key(prefix: int, carried: frozenset[str]) -> None:
    full = pa.table({"id": list(range(4_000)), "v": [i % 5 for i in range(4_000)]})
    chunk = full.slice(0, prefix)
    profile = first_chunk_profile(chunk, table="t", engine_version="0", carried=carried)
    for col in profile.tables[0].columns:
        assert col.sampled is True, col.name
        assert col.is_candidate_key_sampled is False, col.name


# AT-15: a source read to its end hashes as it did before the `n + 1` read. The value
# was captured on the pre-change base (origin/main cc0149152).
# One digest per source format. COLUMN-SHAPE E1a moved them: each hashed column now carries its
# `shape`, which is `text` for csv and `integer` for these parquet columns. The sample limit
# still does not move either digest, which is what this test pins.
_WHOLE_READ_HASH = {
    "csv": "01f0580a0d67b06d105edbd814b31ff1f0b25022b150c4b17e29e1d0452eb98b",
    "parquet": "ecf5675343a95c48b9dda7623d7ba611bf273484b92d1f09b94947176eecc84e",
}


@pytest.mark.parametrize("fmt", ["csv", "parquet"])
@pytest.mark.parametrize("limit", [10_000, 500])
def test_fully_read_source_hash_is_unchanged(tmp_path: Path, fmt: str, limit: int) -> None:
    from decoy_engine.profile import profile_hash

    rows = 500
    if fmt == "csv":
        path = tmp_path / "a.csv"
        path.write_text("id,v\n" + "\n".join(f"{i},{i % 7}" for i in range(rows)) + "\n")
        descriptor: dict[str, Any] = {
            "type": "file",
            "format": "csv",
            "path": str(path),
            "has_header": True,
        }
    else:
        import pyarrow.parquet as pq

        path = tmp_path / "a.parquet"
        pq.write_table(pa.table({"id": list(range(rows)), "v": [i % 7 for i in range(rows)]}), path)
        descriptor = {"type": "file", "format": "parquet", "path": str(path)}
    config = declare_rest(
        {"global_settings": {"seed": 0}, "sources": {"t": descriptor}, "relationships": []}
    )
    profile = profile_source(config, sample_rows=limit, seed=0)
    assert profile_hash(profile) == _WHOLE_READ_HASH[fmt]
