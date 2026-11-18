"""F24 84-E1: the lifecycle estimate against measured peak RSS (opt-in, test VM only).

Plan: docs/plans/2026-11-17-f24-lifecycle-estimate.md section 8.2 and 8.3. Every cell asserts
`measured <= predicted`. A cell marked bounded also asserts `predicted <= 1.5 * measured` when
the realized route equals the predicted route and the job has at least 1,000,000 rows. The
tolerance is fixed by the plan and is never widened in a build.

The worker (`scripts/fk-scale/bench_worker_lifecycle.py`) reads every source, holds it, runs the
pipeline and writes every target in one child process; the supervisor reads `ru_maxrss` from
outside. Predicted and measured phase figures are printed for the calibration record.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.benchmark

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "fk-scale"
sys.path.insert(0, str(_SCRIPTS))

from decoy_engine import PipelineConfig, estimate_job  # noqa: E402

_MIB = 1024 * 1024
UPPER_BOUND = 1.5
TIERS = {"1M": 1_000_000, "3M": 3_000_000}
# Bound class per cell (plan 8.3). "lower" cells are string output or carry the TB-4 string margin.
BOUND = {
    "AT-E1-17": "lower",
    "AT-E1-18": "lower",
    "AT-E1-19": "lower",
    "AT-E1-23": "lower",
    "AT-E1-24": "lower",
    "AT-E1-25": "lower",
    "AT-E1-27": "bounded",
}


def _run(cell: str, rows: int, tmp_path: Path) -> dict[str, Any]:
    # A fresh process, so this test's own memory never reaches the measured peak.
    out = tmp_path / "record.json"
    subprocess.run(  # noqa: S603
        [sys.executable, str(_SCRIPTS / "bench_worker_lifecycle.py"), "--cell", cell,
         "--rows", str(rows), "--work-root", str(tmp_path), "--keep", "--out", str(out)],
        check=False, capture_output=True,
    )  # fmt: skip
    return json.loads(out.read_text())  # type: ignore[no-any-return]


@pytest.mark.parametrize("tier", list(TIERS))
@pytest.mark.parametrize("cell", list(BOUND))
def test_lifecycle_estimate_bounds_the_measured_peak(cell: str, tier: str, tmp_path: Path) -> None:
    rows = TIERS[tier]
    record = _run(cell, rows, tmp_path)
    assert record["completed"] is True, record["failure"]
    config = PipelineConfig.model_validate(record["config"]).model_dump()
    est = estimate_job(config, tmp_path)
    assert est.lifecycle_peak_bytes is not None, est.notes
    predicted_mb = est.lifecycle_peak_bytes / _MIB
    measured_mb = record["peak_rss_mb"]
    realized = record["result"].get("realized_route")
    print(
        f"F24_CELL {cell} {tier} predicted_route={est.route} realized_route={realized} "
        f"limiting={est.limiting_phase} predicted_mb={predicted_mb:.0f} measured_mb={measured_mb} "
        f"ratio={predicted_mb / measured_mb:.2f} "
        f"phases_mb={[(n, round(b / _MIB)) for n, b in est.phase_bytes]} "
        f"wall_s={record['result'].get('phase_wall_s')}"
    )
    assert measured_mb <= predicted_mb, "the estimate is below the measured peak"
    same_route = realized == est.route
    if BOUND[cell] == "bounded" and same_route:
        assert predicted_mb <= UPPER_BOUND * measured_mb
