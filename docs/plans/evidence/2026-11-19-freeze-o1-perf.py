"""O1 performance probe: peak RSS and `when:` evaluation time for one cell, in a fresh process.

Usage: python 2026-11-19-freeze-o1-perf.py <route> <cls> <rows> <variant>
  route:   full_frame | unified | chunked (65,536-row chunks through the chunked oracle leg)
  cls:     plain | fk | declared | anchor
  variant: numexpr (in-range ints, int literal) | object_value (one value beyond 2**53)
           | object_literal (int literal beyond 2**53) | float_literal (`v > 5.5`)
Prints one JSON line. Run it against two checkouts (PYTHONPATH=<checkout>/src, cwd=<checkout>) and
compare. The source table is built the same way on both, so the RSS difference is the run itself.
"""

from __future__ import annotations

import json
import resource
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa

route, cls, rows_s, variant = sys.argv[1:5]
N = int(rows_s)
CHUNK = 65_536
PRED = {
    "numexpr": "v > 5",
    "object_value": "v > 5",
    "object_literal": "v > 9007199254740993",
    "float_literal": "v > 5.5",
}[variant]


def col(name: str, strategy: str = "passthrough", **kw: Any) -> dict[str, Any]:
    return {"name": name, "strategy": strategy, **kw}


def build() -> tuple[dict[str, Any], dict[str, pa.Table]]:
    from tests._declared_schema import declare_rest

    from decoy_engine.config import PipelineConfig

    rng = np.random.default_rng(7)
    v = rng.integers(0, 1_000_000, N).astype(np.int64)
    if variant == "object_value":
        v[N // 2] = 2**60
    nulls = rng.random(N) < 0.05
    ints = pa.array(v, mask=nulls)
    base: dict[str, pa.Array] = {"id": pa.array(np.arange(N, dtype=np.int64)), "v": ints}
    cols = [col("id"), col("v"), {**col("m", "redact"), "when": PRED}]
    tables: dict[str, pa.Table] = {}
    extra: list[dict[str, Any]] = []
    rels: list[dict[str, Any]] = []
    if cls == "declared":
        base["v"] = pa.array(
            [None if n else str(x) for x, n in zip(v.tolist(), nulls.tolist(), strict=True)],
            pa.string(),
        )
        cols[1] = col(
            "v",
            logical_type="integer",
            parse_format={"id": "integer/ascii/v1", "signed": True, "bit_width": 64},
        )
    elif cls == "anchor":
        base["d"] = pa.array(["2020-01-01"] * N, pa.string())
        cols.append(
            col(
                "d",
                "date_shift",
                provider_config={"max_shift_days": 3, "group_by": "v"},
                deterministic=True,
                namespace="ns_d",
            )
        )
    base["m"] = pa.array(["abcdef"] * N, pa.string())
    if cls == "fk":
        tables["parent"] = pa.table({"pid": pa.array(np.unique(v))})
        extra.append({"name": "parent", "columns": [col("pid")]})
        rels.append(
            {
                "parent": {"table": "parent", "columns": ["pid"]},
                "children": [{"table": "t", "columns": ["v"]}],
                "orphan_policy": "remap",
                "namespace": "ns_fk",
            }
        )
    tables["t"] = pa.table(base)
    tmp = Path(tempfile.mkdtemp())
    raw = {
        "version": 2,
        "global_settings": {"seed": 7},
        "sources": {
            n: {"type": "file", "format": "csv", "has_header": True, "path": str(tmp / f"{n}.csv")}
            for n in tables
        },
        "tables": [{"name": "t", "columns": cols}, *extra],
        "targets": {
            n: {"type": "file", "format": "csv", "path": str(tmp / f"{n}.out")} for n in tables
        },
        "relationships": rels,
        "namespaces": {},
    }
    for n, t in tables.items():
        (tmp / f"{n}.csv").write_text(
            ",".join(t.column_names) + "\n" + ",".join("x" for _ in t.column_names) + "\n"
        )
    return PipelineConfig.model_validate(declare_rest(raw, tables)).model_dump(), tables


stats = {"eval_s": 0.0, "calls": 0, "frame_s": 0.0}


def patch() -> None:
    import decoy_engine.execution._when_gate as wg

    def wrap(mod: Any, name: str, key: str) -> None:
        real = getattr(mod, name, None)
        if real is None:
            return

        def timed(*a: Any, **k: Any) -> Any:
            t0 = time.perf_counter()
            try:
                return real(*a, **k)
            finally:
                stats[key] += time.perf_counter() - t0
                if key == "eval_s":
                    stats["calls"] += 1

        setattr(mod, name, timed)

    wrap(wg, "_eval_predicate", "eval_s")
    for modname in (
        "decoy_engine.execution._unified_slice_when",
        "decoy_engine.execution.native._when_mask",
    ):
        __import__(modname)
        wrap(sys.modules[modname], "_eval_predicate", "eval_s")
    # `_eval_predicate` calls `when_eval_frame` through its module global on the O1 head only.
    wrap(wg, "when_eval_frame", "frame_s")


def main() -> None:
    from tests.native._b8_support import run_mask_pipeline_chunked_below_gate
    from tests.native._chunked_entry_support import ENGINE_VERSION, key_provider

    from decoy_engine.execution._pipeline import run_pipeline

    cfg, tables = build()
    rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    patch()
    t0 = time.perf_counter()
    if route == "chunked":
        t = tables["t"]
        chunks = (t.slice(i, CHUNK) for i in range(0, N, CHUNK))
        for _ in run_mask_pipeline_chunked_below_gate(
            cfg,
            chunks,
            table="t",
            source_schema=t.schema,
            engine_version=ENGINE_VERSION,
            key_provider=key_provider(),
        ):
            pass
    else:
        run_pipeline(
            cfg,
            tables,
            engine_version="o1",
            key_provider=key_provider(),
            execution_mode="full_frame",
            auto_chunk=False,
            unified_slice_enabled=route == "unified",
        )
    wall = time.perf_counter() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(
        json.dumps(
            {
                "route": route,
                "cls": cls,
                "rows": N,
                "variant": variant,
                "rss_before_mb": round(rss0 / 1024),
                "peak_rss_mb": round(rss / 1024),
                "wall_s": round(wall, 2),
                "eval_s": round(stats["eval_s"], 3),
                "frame_s": round(stats["frame_s"], 3),
                "eval_calls": stats["calls"],
            }
        )
    )


main()
