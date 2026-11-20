"""AT-14: labelling the first-chunk profile as a sample moves no masked byte.

Characterization control, captured green before the `_as_chunk_sample` change. A
chunked mask run of one source at two chunk sizes gives identical output, and the
route evidence holds no profile or plan hash.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pyarrow as pa
import pytest

from tests._declared_schema import declared_schema
from tests.native._b8_support import (
    run_mask_pipeline_chunked_below_gate,
    run_one,
)
from tests.native._chunked_entry_support import (
    ENGINE_VERSION,
    NEEDS_COMPANION,
    TABLE,
    hash_col,
    key_provider,
    make_config,
    passthrough,
)

ROWS = 4_000


def _source() -> pa.Table:
    return pa.table(
        {
            "id": [f"id-{i}" for i in range(ROWS)],
            "email": [f"user{i}@example.com" for i in range(ROWS)],
            "note": [f"n{i % 9}" for i in range(ROWS)],
        }
    )


def _chunks(size: int) -> list[pa.Table]:
    table = _source()
    return [table.slice(i, size) for i in range(0, ROWS, size)]


def _config() -> dict[str, Any]:
    return make_config([passthrough("id"), hash_col("email"), passthrough("note")])


def _rows(chunks: list[pa.Table]) -> list[dict[str, Any]]:
    return pa.concat_tables(chunks).to_pylist()


def _no_hashes(obj: Any) -> None:
    text = repr(dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) else obj)
    assert "profile_hash" not in text
    assert "plan_hash" not in text


def test_oracle_lane_output_is_chunk_size_independent() -> None:
    runs = [
        list(
            run_mask_pipeline_chunked_below_gate(
                _config(),
                _chunks(size),
                table=TABLE,
                source_schema=declared_schema(_config(), TABLE),
                engine_version=ENGINE_VERSION,
                key_provider=key_provider(),
            )
        )
        for size in (1_000, 2_000)
    ]
    assert _rows(runs[0]) == _rows(runs[1])


@NEEDS_COMPANION
def test_native_lane_output_and_evidence_are_chunk_size_independent() -> None:
    small = run_one(_config(), _chunks(1_000))
    large = run_one(_config(), _chunks(2_000))
    assert _rows(small.out) == _rows(large.out)
    assert [e.native_admitted for e in small.ev] == [True]
    assert [e.native_admitted for e in large.ev] == [True]
    assert small.ev[0].reroute_reason == large.ev[0].reroute_reason
    for run in (small, large):
        for ev in run.ev:
            _no_hashes(ev)


def test_oracle_output_holds_no_profile_or_plan_hash() -> None:
    out = list(
        run_mask_pipeline_chunked_below_gate(
            _config(),
            _chunks(1_000),
            table=TABLE,
            source_schema=declared_schema(_config(), TABLE),
            engine_version=ENGINE_VERSION,
            key_provider=key_provider(),
        )
    )
    assert all(isinstance(t, pa.Table) for t in out)
    assert not any("hash" in n and "profile" in n for t in out for n in t.schema.names)


@pytest.mark.parametrize("name", ["profile_hash", "plan_hash"])
def test_route_evidence_has_no_hash_field(name: str) -> None:
    from decoy_engine.execution.native._dispatch import NativeRouteEvidence

    fields = {f.name for f in dataclasses.fields(NativeRouteEvidence)}
    assert "native_admitted" in fields  # the evidence class under test is the real one
    assert name not in fields
