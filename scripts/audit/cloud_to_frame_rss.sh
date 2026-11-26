#!/usr/bin/env bash
# Peak RSS of a cloud Parquet to_frame over a 256 MiB fake S3 object, head against main's route.
# Each route runs in its own fresh process on the same bytes. Building the file peaks higher than
# reading it, so a first process writes it and the measuring processes read it back.
#   head: S3ParquetSource.to_frame (ranged column-chunk reads)
#   main: one whole-object get_object, then pd.read_parquet over the bytes
# Prints both peak growths and exits 1 when head's growth is more than 10% above main's.
# The bound is "no worse than main"; a working set below main's is a V2-LOG item.
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
rows = 256 * MiB // 32
table = pa.table({f"c{i}": rng.integers(0, 1 << 62, rows) for i in range(4)})
pq.write_table(table, f"{work}/big.parquet", row_group_size=1 << 20, compression="none")
PYEOF

measure() {
  "$PY" -I - "$WORK" "$PWD" "$1" <<'PYEOF'
import io
import resource
import sys

work, root, route = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path[:0] = [f"{root}/src", root]
import pandas as pd

from decoy_engine.profile import _cloud_readers
from tests._cloud_fakes import FakeS3

MiB = 1 << 20


def peak_mib() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / MiB if sys.platform == "darwin" else peak / 1024


with open(f"{work}/big.parquet", "rb") as fh:
    fake = FakeS3(fh.read())
_cloud_readers._clients.s3_client = lambda **_kw: fake
before = peak_mib()
if route == "head":
    frame = _cloud_readers.S3ParquetSource(
        {"format": "parquet", "bucket": "b", "key": "k"}
    ).to_frame()
else:
    body = fake.get_object(Bucket="b", Key="k")["Body"].read()
    frame = pd.read_parquet(io.BytesIO(body))
print(f"{peak_mib() - before:.1f} {len(fake.ledger.data_requests)}")
PYEOF
}

read -r head_mib head_requests < <(measure head)
read -r main_mib _ < <(measure main)
echo "object_mib=256 head_peak_growth_mib=${head_mib} head_requests=${head_requests} main_peak_growth_mib=${main_mib}"
"$PY" -I -c 'import sys; sys.exit(0 if float(sys.argv[1]) <= 1.10 * float(sys.argv[2]) else 1)' \
  "$head_mib" "$main_mib" || { echo "FAIL: head peak growth is more than 10% above main's"; exit 1; }
echo "ok: head is no worse than main"
