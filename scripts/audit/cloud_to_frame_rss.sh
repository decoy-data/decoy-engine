#!/usr/bin/env bash
# Peak RSS of a cloud Parquet to_frame over a 256 MiB fake S3 object, in a fresh process.
# Evidence only. Building the file peaks higher than reading it, so a first process writes it
# and a second one measures. Prints the peak growth above the object bytes and the result
# frame (target: under half the object size), and the request count for a 50-column file.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY="${PY:-python}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

"$PY" -I - "$WORK" <<'PYEOF'
import sys

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

work, MiB = sys.argv[1], 1 << 20
rng = np.random.default_rng(0)


def write(path: str, columns: int, rows: int, row_group: int) -> None:
    table = pa.table({f"c{i}": rng.integers(0, 1 << 62, rows) for i in range(columns)})
    pq.write_table(table, path, row_group_size=row_group, compression="none")


write(f"{work}/big.parquet", 4, 256 * MiB // 32, 1 << 20)
write(f"{work}/wide.parquet", 50, 20_000, 5_000)
PYEOF

"$PY" -I - "$WORK" "$PWD" <<'PYEOF'
import resource
import sys

work, root = sys.argv[1], sys.argv[2]
sys.path[:0] = [f"{root}/src", root]
from decoy_engine.profile import _cloud_readers
from tests._cloud_fakes import FakeS3

MiB = 1 << 20


def peak_mib() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / MiB if sys.platform == "darwin" else peak / 1024


def run(data: bytes) -> tuple[int, int]:
    fake = FakeS3(data)
    _cloud_readers._clients.s3_client = lambda **_kw: fake
    source = _cloud_readers.S3ParquetSource({"format": "parquet", "bucket": "b", "key": "k"})
    frame = source.to_frame()
    return int(frame.memory_usage(deep=True).sum()), len(fake.ledger.data_requests)


with open(f"{work}/big.parquet", "rb") as fh:
    big = fh.read()
before = peak_mib()
frame_bytes, requests = run(big)
growth = peak_mib() - before - frame_bytes / MiB
print(
    f"object_mib={len(big) / MiB:.1f} frame_mib={frame_bytes / MiB:.1f} requests={requests} "
    f"peak_growth_above_frame_mib={growth:.1f} target_lt_mib={len(big) / MiB / 2:.1f}"
)
del big
with open(f"{work}/wide.parquet", "rb") as fh:
    wide = fh.read()
print(f"fifty_columns object_kib={len(wide) // 1024} data_requests={run(wide)[1]}")
PYEOF
