"""GEN-STREAM-ALL A3 (control): a column's bytes do not depend on the batch size or the sink.

Passes before and after S1a and guards the take path and the moved assembler. Rows 1 to 10,001
are below the pooling threshold (per-row lane); 120,000 pools.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.parity._fr0_support import run_resident, run_streamed
from tests.unit.generation.stream._support import LEGACY_TEN, faker_config, table_digest

_SMALL_ROWS = (1, 9_999, 10_000, 10_001)
_BATCHES = (1, 7, 4096)


@pytest.mark.parametrize("faker_type", ["first_name", "company"])
@pytest.mark.parametrize("rows", _SMALL_ROWS)
def test_per_row_lane_is_batch_invariant(faker_type: str, rows: int) -> None:
    cfg = faker_config(faker_type, rows, null_probability=0.1)
    reference = table_digest(run_resident(cfg, batch_rows=rows)["t"])
    for batch in _BATCHES:
        assert table_digest(run_resident(cfg, batch_rows=batch)["t"]) == reference


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
