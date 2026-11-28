"""A wide CSV sample parses as `main` parses it (F25 G7-1, case 10).

`low_memory=False` on a wide window raises the parser's working set; `main` does not set it.
Four fresh subprocesses run under one `RLIMIT_AS` (address space after the imports plus a
margin): `main`'s parse and head's `sample_frame` and `schema` succeed, and a control parse
with `low_memory=False` fails. The control proves the limit catches the regression; the
`main` run proves the limit is not too tight. `RLIMIT_AS` is not enforced on macOS.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="RLIMIT_AS is not enforced on this platform"
)

ROOT = Path(__file__).resolve().parents[3]
ROWS, COLS = 8_000, 1_050
# Calibrated on Linux (Dell WSL2, Python 3.10, pandas 2.3.3, pyarrow 24): `main`'s parse, head's
# sample and head's schema pass from 280 MiB up, and the `low_memory=False` control fails up to
# 280 MiB and passes at 300 MiB, so 280 MiB is the one limit that separates them.
MARGIN = 280 << 20

_CHILD = textwrap.dedent(
    """
    import io, resource, sys
    import pandas as pd
    import pyarrow as pa
    sys.path[:0] = [sys.argv[3] + "/src", sys.argv[3]]
    from decoy_engine.profile import _cloud_readers
    from tests._cloud_fakes import FakeS3

    def address_space() -> int:
        for line in open("/proc/self/status"):
            if line.startswith("VmSize"):
                return int(line.split()[1]) * 1024
        raise SystemExit(2)

    data = open(sys.argv[1], "rb").read()
    mode, margin, rows = sys.argv[2], int(sys.argv[4]), int(sys.argv[5])
    base = address_space()
    if margin:
        resource.setrlimit(resource.RLIMIT_AS, (base + margin, base + margin))
    if mode == "main":
        frame = pd.read_csv(io.BytesIO(data), nrows=rows)
    elif mode == "control":
        frame = pd.read_csv(io.BytesIO(data), nrows=rows, low_memory=False)
    else:
        fake = FakeS3(data)
        _cloud_readers._clients.s3_client = lambda **_kw: fake
        source = _cloud_readers.S3CsvSource({"format": "csv", "bucket": "b", "key": "k"})
        frame = source.sample_frame(rows) if mode == "sample" else source.schema()
    print("rows", len(frame))
    for line in open("/proc/self/status"):
        if line.startswith("VmPeak"):
            print("peak", int(line.split()[1]) * 1024 - base)
    """
)


@pytest.fixture(scope="module")
def wide_csv(tmp_path_factory: pytest.TempPathFactory) -> Path:
    rng = np.random.default_rng(0)
    path = tmp_path_factory.mktemp("wide") / "wide.csv"
    with path.open("w") as fh:
        fh.write(",".join(f"c{i}" for i in range(COLS)) + "\n")
        for _ in range(ROWS):
            fh.write(",".join(map(str, rng.integers(0, 1000, COLS).tolist())) + "\n")
    return path


def _run(path: Path, mode: str, margin: int = MARGIN) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - argv is the test interpreter and fixed paths
        [sys.executable, "-c", _CHILD, str(path), mode, str(ROOT), str(margin), str(ROWS)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


@pytest.mark.parametrize("mode", ["main", "sample", "schema"])
def test_reads_that_main_completes_still_complete(wide_csv: Path, mode: str) -> None:
    done = _run(wide_csv, mode)
    assert done.returncode == 0, done.stderr[-300:]
    assert done.stdout.strip().startswith("rows ")


def test_the_limit_catches_a_low_memory_false_parse(wide_csv: Path) -> None:
    done = _run(wide_csv, "control")
    assert done.returncode != 0
    assert "MemoryError" in done.stderr


def _peak(path: Path, mode: str) -> int:
    done = _run(path, mode, margin=0)
    assert done.returncode == 0, done.stderr[-300:]
    return int(done.stdout.split("peak ")[1].split()[0])


def test_sample_peak_is_one_parse_over_the_fetched_bytes(wide_csv: Path) -> None:
    """The ranged sample parses once, over the bytes it fetched, never over an earlier frame.

    `main`'s parse runs on bytes already in memory. The sample also holds its own copy of the
    object, and the address space its ranged pieces used (the allocator may keep it mapped),
    so `3 * size` (93 MiB here) is allowed on top. A prefix frame kept while the next window
    parses, or a parse per window, goes over. Measured on Linux (Dell WSL2 and GCP): `main`
    + 142 MiB with a parse per window, + 109 MiB with only the earlier frame released, + 77 MiB
    with one parse."""
    size = wide_csv.stat().st_size
    assert _peak(wide_csv, "sample") <= _peak(wide_csv, "main") + 3 * size
