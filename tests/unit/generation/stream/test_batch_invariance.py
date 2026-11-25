"""GEN-STREAM-ALL A3 (control): a column's bytes do not depend on the batch size or the sink.

Guards the take path and the moved assembler. Rows 1 to 10,001 run twice: on the per-row lane
(below the pooling threshold) and on the Arrow lane with the threshold lowered, where the test
also checks that every row came through `PooledSelector.take` and none through `select`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from decoy_engine.generation import _faker_pool
from tests.parity._fr0_support import run_resident, run_streamed
from tests.unit.generation.stream._support import LEGACY_TEN, faker_config, ipc_bytes, table_digest

_SMALL_ROWS = (1, 9_999, 10_000, 10_001)
_BATCHES = (1, 7, 4096)


@pytest.mark.parametrize("faker_type", ["first_name", "company"])
@pytest.mark.parametrize("rows", _SMALL_ROWS)
def test_per_row_lane_is_batch_invariant(faker_type: str, rows: int) -> None:
    cfg = faker_config(faker_type, rows, null_probability=0.1)
    reference = table_digest(run_resident(cfg, batch_rows=rows)["t"])
    for batch in _BATCHES:
        assert table_digest(run_resident(cfg, batch_rows=batch)["t"]) == reference


def _count(monkeypatch: pytest.MonkeyPatch, name: str) -> list[int]:
    calls: list[int] = []
    real = getattr(_faker_pool.PooledSelector, name)

    def spy(self: Any, size: int) -> Any:
        calls.append(size)
        return real(self, size)

    monkeypatch.setattr(_faker_pool.PooledSelector, name, spy)
    return calls


@pytest.mark.parametrize("faker_type", ["first_name", "company"])
@pytest.mark.parametrize("rows", _SMALL_ROWS)
def test_arrow_lane_is_batch_invariant_at_the_small_row_counts(
    faker_type: str, rows: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_faker_pool, "N_THRESHOLD", 1)
    takes = _count(monkeypatch, "take")
    selects = _count(monkeypatch, "select")
    cfg = faker_config(faker_type, rows, null_probability=0.1)
    reference = ipc_bytes(run_resident(cfg, batch_rows=rows)["t"])
    for batch in _BATCHES:
        assert ipc_bytes(run_resident(cfg, batch_rows=batch)["t"]) == reference
    assert sum(takes) == rows * (1 + len(_BATCHES))
    assert selects == []


@pytest.mark.parametrize("faker_type", LEGACY_TEN)
def test_pooled_lane_is_batch_invariant_and_sink_equals_resident(
    faker_type: str, tmp_path: Path
) -> None:
    rows = 120_000
    cfg = faker_config(faker_type, rows, null_probability=0.1)
    reference = table_digest(run_resident(cfg, batch_rows=rows)["t"])
    for batch in (7, 4096):
        assert table_digest(run_resident(cfg, batch_rows=batch)["t"]) == reference
    _, sunk = run_streamed(cfg, tmp_path, batch_rows=4096)
    assert table_digest(sunk["t"]) == reference
