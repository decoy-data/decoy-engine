"""Column micro-benchmark for `apply_windowed_date` (workload A of the F1 benchmark protocol).

200,000 rows, 5% nulls, window -30..90, each distribution, two anchor shapes (ISO strings and
object `datetime.date` cells). Every configuration runs in a fresh process: one untimed warm call,
then 7 timed calls. The worker prints one JSON object with median, min, max and IQR in us/row.

Run with `-m benchmark`. `DECOY_BENCH_OUT` names a directory that receives the raw JSON.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.benchmark

ROWS = 200_000
TIMED_CALLS = 7
TARGET_US_PER_ROW = 45.0  # S1 target; the pre-change figure is about 132
SEED = b"\x01\x02\x03\x04\x05\x06\x07\x08"


def _anchors(shape: str) -> list[object]:
    import numpy as np

    rng = np.random.default_rng(7)
    base = dt.date(1970, 1, 1)
    days = rng.integers(0, 20_000, size=ROWS)
    cells: list[object]
    if shape == "iso":
        cells = [(base + dt.timedelta(days=int(d))).isoformat() for d in days]
    else:
        cells = [base + dt.timedelta(days=int(d)) for d in days]
    for k in range(0, ROWS, 20):
        cells[k] = None
    return cells


def worker(dist: str, shape: str) -> dict[str, object]:
    import pandas as pd

    from decoy_engine.transforms.windowed_date import WindowedDateConfig, apply_windowed_date

    cfg = WindowedDateConfig(anchor="a", min_days=-30, max_days=90, distribution=dist)
    df = pd.DataFrame({"a": pd.Series(_anchors(shape), dtype=object)})
    apply_windowed_date(cfg, df, SEED, "windowed_date/bench")
    samples = []
    digest = 0
    for _ in range(TIMED_CALLS):
        t0 = time.perf_counter()
        out = apply_windowed_date(cfg, df, SEED, "windowed_date/bench")
        samples.append((time.perf_counter() - t0) / ROWS * 1e6)
        digest = hash(tuple(out[:1000]))
    ordered = sorted(samples)
    q = statistics.quantiles(ordered, n=4)
    return {
        "dist": dist,
        "shape": shape,
        "rows": ROWS,
        "median_us": statistics.median(ordered),
        "min_us": ordered[0],
        "max_us": ordered[-1],
        "iqr_us": q[2] - q[0],
        "samples_us": samples,
        "head_hash_is_stable": digest != 0,
    }


@pytest.mark.parametrize("shape", ["iso", "date"])
@pytest.mark.parametrize("dist", ["uniform", "early", "late"])
def test_windowed_date_us_per_row(dist: str, shape: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), dist, shape],
        capture_output=True,
        text=True,
        check=True,
        timeout=600,
    )
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    out_dir = os.environ.get("DECOY_BENCH_OUT")
    if out_dir:
        Path(out_dir, f"windowed_date_{dist}_{shape}.json").write_text(json.dumps(result))
    assert result["median_us"] <= TARGET_US_PER_ROW, result


if __name__ == "__main__":
    print(json.dumps(worker(sys.argv[1], sys.argv[2])))
