"""End-to-end probe: `run_pipeline` with redact and truncate on a `string` and a `large_string` Parquet.

Counts calls into the per-row reference functions to show which path each run took.
Usage: python -I run_probe.py WORKDIR ROWS
"""

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DECOY_MASK_SECRET", "ab" * 32)
from unittest import mock

import pyarrow as pa
import pyarrow.parquet as pq

import decoy_engine.kernel._scalar as ks
from decoy_engine.config import PipelineConfig
from decoy_engine.execution import run_pipeline
from decoy_engine.execution._transactional_sink import ParquetTransactionalSink
from decoy_engine.profile._readers import LazySource

d = Path(sys.argv[1])
n = int(sys.argv[2])
vals = pa.array([f"user{i}@example.com" if i % 10 else None for i in range(n)])
for t in ("string", "large_string"):
    typ = pa.string() if t == "string" else pa.large_string()
    pq.write_table(
        pa.table({"secret": vals.cast(typ), "zip": vals.cast(typ)}),
        d / f"{t}.parquet",
        row_group_size=1 << 20,
    )
cfg = lambda p: PipelineConfig.model_validate(
    {
        "version": 2,
        "global_settings": {"seed": 42, "mask_secret_ref": "env:DECOY_MASK_SECRET"},
        "sources": {"t": {"type": "file", "format": "parquet", "path": str(p)}},
        "tables": [
            {
                "name": "t",
                "columns": [
                    {"name": "secret", "strategy": "redact"},
                    {
                        "name": "zip",
                        "strategy": "truncate",
                        "provider_config": {"length": 3, "keep": "head"},
                    },
                ],
            }
        ],
        "targets": {"t": {"type": "file", "format": "parquet", "path": "/dev/null"}},
    }
).model_dump()
for cell in ("resident", "lazy_sink"):
    for t in ("string", "large_string"):
        p = d / f"{t}.parquet"
        calls = {"redact_ref": 0, "trunc_ref": 0}
        ro, to = ks._redact_array_reference, ks._truncate_array_reference

        def r(*a, calls=calls, ro=ro, **k):
            calls["redact_ref"] += 1
            return ro(*a, **k)

        def tr(*a, calls=calls, to=to, **k):
            calls["trunc_ref"] += 1
            return to(*a, **k)

        with (
            mock.patch.object(ks, "_redact_array_reference", r),
            mock.patch.object(ks, "_truncate_array_reference", tr),
        ):
            src = LazySource(p) if cell == "lazy_sink" else pq.read_table(p)
            kw = (
                {"sink": ParquetTransactionalSink(d / f"out-{cell}-{t}")}
                if cell == "lazy_sink"
                else {}
            )
            t0 = time.perf_counter()
            res = run_pipeline(cfg(p), sources={"t": src}, engine_version="probe", **kw)
            w = time.perf_counter() - t0
        ex = res.quality_metrics.get("execution") or {}
        ac = res.quality_metrics.get("auto_chunk") or {}
        print(
            json.dumps(
                {
                    "cell": cell,
                    "type": t,
                    "wall_s": round(w, 2),
                    **calls,
                    "mode": ex.get("execution_mode"),
                    "auto_chunk": ac.get("mode"),
                }
            )
        )
