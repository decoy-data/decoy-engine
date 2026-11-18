"""F24 lifecycle-estimate accuracy worker: one child process does what the CLI does.

Plan: docs/plans/2026-11-17-f24-lifecycle-estimate.md section 8.2. The child reads every file
source whole through the engine readers in config order, holds them, calls `run_pipeline` with the
resident tables, and writes every target (CSV through `generated_table_to_pandas` then `to_csv`,
Parquet through `pq.write_table`, fixed_width through a copy-and-write like the CLI's
`_write_fixed_width`). The supervisor (`_supervisor.run_worker`) reads peak RSS from outside.

Passed to `run_pipeline`: the config, the resident tables, a key provider and the CLI's `auto`
resource kwargs (`native_threads`, `out_of_core_threads` from `detect_usable_cpus`,
`out_of_core_budget_bytes` from `resolve_conservative_ooc_budget_bytes`). The CLI itself is not
importable from the engine repo, so these come from the engine helpers the CLI also uses. The
native gate result is the default (`unified_slice_enabled` is not passed; the CLI passes it only
to turn it off). Not passed: the vault writer, quarantine path and report flags (outside the
estimate, plan section 2). The record lists them under `not_passed`.

    python scripts/fk-scale/bench_worker_lifecycle.py --cell AT-E1-17 --rows 1000000
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _supervisor import classify_failure, run_worker

SCHEMA = "f24-lifecycle-accuracy/v1"
CELLS = (
    "AT-E1-17",
    "AT-E1-18",
    "AT-E1-19",
    "AT-E1-23",
    "AT-E1-24",
    "AT-E1-25",
    "AT-E1-27",
    "AT-E2-6a",
    "AT-E2-6b",
)


# ------------------------------------------------------------------------------- fixtures


def _ids(prefix: str, start: int, n: int) -> Any:
    import numpy as np
    import pyarrow as pa

    return pa.array(np.char.add(prefix, np.arange(start, start + n).astype(str)))


def _write_csv(path: Path, table: Any) -> str:
    import pyarrow.csv as pacsv

    pacsv.write_csv(table, str(path))
    return str(path)


def _write_parquet(path: Path, table: Any) -> str:
    import pyarrow.parquet as pq

    pq.write_table(table, str(path), row_group_size=262_144)
    return str(path)


def _src(fmt: str, path: str, **extra: Any) -> dict[str, Any]:
    src: dict[str, Any] = {"type": "file", "format": fmt, "path": path, **extra}
    if fmt == "csv":
        src["has_header"] = True
    return src


def _tgt(fmt: str, path: str, **extra: Any) -> dict[str, Any]:
    return {"type": "file", "format": fmt, "path": path, **extra}


def _base(sources: dict, targets: dict, tables: list, rel: list | None = None) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "version": 2,
        "global_settings": {"seed": 20261117},
        "sources": sources,
        "targets": targets,
        "tables": tables,
    }
    if rel:
        cfg["relationships"] = rel
    return cfg


def _string_table(rows: int, columns: int, *, latin1: bool = False) -> Any:
    import pyarrow as pa

    data = {}
    for c in range(columns):
        prefix = f"café-ü{c}-" if latin1 else f"v{c}-"
        data[f"s{c}"] = _ids(prefix, 0, rows)
    return pa.table(data)


def _chain_tables(rows: int, *, numeric: bool) -> dict[str, Any]:
    import numpy as np
    import pyarrow as pa

    n_parent, n_child, n_grand = rows // 5, 2 * rows // 5, rows - rows // 5 - 2 * rows // 5
    rng = np.random.default_rng(7)

    def key(prefix: str, values: Any) -> Any:
        return pa.array(values) if numeric else pa.array(np.char.add(prefix, values.astype(str)))

    parent = pa.table(
        {
            "id": key("P", np.arange(n_parent)),
            "a": key("a", np.arange(n_parent)) if not numeric else pa.array(np.arange(n_parent)),
        }
    )
    child = pa.table(
        {
            "id": key("C", np.arange(n_child)),
            "parent_id": key("P", rng.integers(0, n_parent, n_child)),
            "b": key("b", np.arange(n_child)) if not numeric else pa.array(np.arange(n_child)),
        }
    )
    grand = pa.table(
        {
            "id": key("G", np.arange(n_grand)),
            "child_id": key("C", rng.integers(0, n_child, n_grand)),
            "c": key("c", np.arange(n_grand)) if not numeric else pa.array(np.arange(n_grand)),
        }
    )
    return {"parent": parent, "child": child, "grandchild": grand}


_CHAIN_KEYS = {
    "parent": {"id": "ns_parent"},
    "child": {"id": "ns_child", "parent_id": "ns_parent"},
    "grandchild": {"id": "ns_grand", "child_id": "ns_child"},
}


def _chain_config(root: Path, tables: dict[str, Any], *, src_fmt: str, tgt_fmt: str) -> dict:
    writers = {"csv": _write_csv, "parquet": _write_parquet}
    sources, targets, table_cfgs = {}, {}, []
    for name, table in tables.items():
        sources[name] = _src(src_fmt, writers[src_fmt](root / f"{name}.{src_fmt}", table))
        targets[name] = _tgt(tgt_fmt, str(root / f"{name}.out.{tgt_fmt}"))
        cols = [
            {"name": c, "strategy": "hash", "namespace": ns} for c, ns in _CHAIN_KEYS[name].items()
        ]
        cols += [
            {"name": c, "strategy": "redact"}
            for c in table.column_names
            if c not in _CHAIN_KEYS[name]
        ]
        table_cfgs.append({"name": name, "columns": cols})

    def rel(p: str, pc: str, c: str, cc: str, ns: str) -> dict:
        return {
            "parent": {"table": p, "columns": [pc]},
            "children": [{"table": c, "columns": [cc]}],
            "orphan_policy": "preserve",
            "namespace": ns,
        }

    rels = [
        rel("parent", "id", "child", "parent_id", "ns_parent"),
        rel("child", "id", "grandchild", "child_id", "ns_child"),
    ]
    return _base(sources, targets, table_cfgs, rels)


def _generate_table(name: str, rows: int) -> dict[str, Any]:
    """A generate table the unified core admits: a sequence and two text columns."""
    return {
        "name": name,
        "row_count": rows,
        "generate_columns": [
            {"name": "id", "type": "sequence", "start": 1},
            {"name": "status", "type": "categorical", "categories": ["active", "inactive", "new"]},
            {"name": "tier", "type": "categorical", "categories": ["bronze", "silver", "gold"]},
        ],
    }


def build_cell(cell: str, rows: int, root: Path) -> dict[str, Any]:
    """Write the fixture files under `root` and return the pipeline config for `cell`."""
    import numpy as np
    import pyarrow as pa

    root.mkdir(parents=True, exist_ok=True)
    if cell in ("AT-E1-17", "AT-E1-24", "AT-E1-25"):
        table = _string_table(rows, 6 if cell == "AT-E1-17" else 3, latin1=cell == "AT-E1-24")
        strategy = "hash" if cell == "AT-E1-25" else "redact"
        cols = [{"name": c, "strategy": strategy} for c in table.column_names]
        if strategy == "hash":
            cols = [{**c, "namespace": f"ns_{c['name']}"} for c in cols]
        return _base(
            {"t": _src("csv", _write_csv(root / "t.csv", table))},
            {"t": _tgt("csv", str(root / "t.out.csv"))},
            [{"name": "t", "columns": cols}],
        )
    if cell == "AT-E1-18":
        tables = _chain_tables(rows, numeric=False)
        return _chain_config(root, tables, src_fmt="csv", tgt_fmt="csv")
    if cell == "AT-E1-19":
        tables = _chain_tables(rows, numeric=True)
        return _chain_config(root, tables, src_fmt="parquet", tgt_fmt="csv")
    if cell == "AT-E1-23":
        table = pa.table({f"n{c}": pa.array(np.arange(rows) + c) for c in range(6)})
        cols = [{"name": c, "strategy": "redact"} for c in table.column_names]
        return _base(
            {"t": _src("parquet", _write_parquet(root / "t.parquet", table))},
            {"t": _tgt("parquet", str(root / "t.out.parquet"))},
            [{"name": "t", "columns": cols}],
        )
    if cell == "AT-E1-27":
        table = pa.table(
            {
                **{f"n{c}": pa.array(np.arange(rows) + c) for c in range(4)},
                "s0": _ids("a", 0, rows),
                "s1": _ids("b", 0, rows),
            }
        )
        cols = [{"name": f"n{c}", "strategy": "passthrough"} for c in range(4)]
        cols += [{"name": c, "strategy": "passthrough"} for c in ("s0", "s1")]
        layout_cols, start = [], 0
        for name in table.column_names:
            is_int = name.startswith("n")
            width = 12 if is_int else 16
            layout_cols.append(
                {"name": name, "start": start, "width": width, "type": "int" if is_int else "str"}
            )
            start += width
        return _base(
            {"t": _src("parquet", _write_parquet(root / "t.parquet", table))},
            {"t": _tgt("fixed_width", str(root / "t.out.txt"), layout={"columns": layout_cols})},
            [{"name": "t", "columns": cols}],
        )
    if cell == "AT-E2-6a":
        return _base(
            {},
            {"g": _tgt("csv", str(root / "g.out.csv"))},
            [_generate_table("g", rows)],
        )
    if cell == "AT-E2-6b":
        table = pa.table({f"n{c}": pa.array(np.arange(rows) + c) for c in range(4)})
        cols = [{"name": c, "strategy": "redact"} for c in table.column_names]
        return _base(
            {"m": _src("parquet", _write_parquet(root / "m.parquet", table))},
            {
                "m": _tgt("parquet", str(root / "m.out.parquet")),
                "g": _tgt("parquet", str(root / "g.out.parquet")),
            },
            [{"name": "m", "columns": cols}, _generate_table("g", rows)],
        )
    raise ValueError(f"unknown cell {cell!r}")


# ------------------------------------------------------------------------------ the child


def _read_sources(config: dict[str, Any]) -> dict[str, Any]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    from decoy_engine import read_fixed_width
    from decoy_engine.profile._csv_reader import read_csv_source, resolve_csv_dialect

    tables: dict[str, Any] = {}
    for name, src in config["sources"].items():
        fmt, path = src["format"], src["path"]
        if fmt == "parquet":
            tables[name] = pq.read_table(path)
        elif fmt == "csv":
            frame = read_csv_source(
                path, resolve_csv_dialect(src, table=name), table=name, dtype=str
            )
            tables[name] = pa.Table.from_pandas(frame, preserve_index=False)
        else:
            tables[name] = pa.Table.from_pandas(
                read_fixed_width(Path(path), src["layout"]), preserve_index=False
            )
    return tables


def _write_fixed_width(table: Any, layout: dict[str, Any], path: Path) -> None:
    import pandas as pd

    from decoy_engine import write_fixed_width

    # The CLI's `_coerce_int_columns`: to_pandas, then a deep copy, then the float and object
    # columns the layout types int are converted. The copy is the memory-relevant step.
    out = table.to_pandas().copy()
    for column in layout["columns"]:
        name = column["name"]
        if column.get("type") != "int" or name not in out.columns:
            continue
        if pd.api.types.is_float_dtype(out[name].dtype):
            out[name] = out[name].astype("Int64")
    write_fixed_width(out, layout, path)


def _write_targets(config: dict[str, Any], outputs: dict[str, Any]) -> None:
    import pyarrow.parquet as pq

    from decoy_engine import generated_table_to_pandas

    for name, table in outputs.items():
        tgt = config["targets"][name]
        path = Path(tgt["path"])
        if tgt["format"] == "csv":
            generated_table_to_pandas(table).to_csv(path, index=False)
        elif tgt["format"] == "parquet":
            pq.write_table(table, str(path))
        else:
            _write_fixed_width(table, tgt["layout"], path)


def _error_record(exc: BaseException) -> dict[str, Any]:
    frames = [
        f"{Path(f.filename).name}:{f.lineno}:{f.name}"
        for f in traceback.extract_tb(exc.__traceback__)
    ]
    return {"type": type(exc).__name__, "code": getattr(exc, "code", None), "frames": frames}


def run_child(args: argparse.Namespace) -> int:
    repo = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(repo / "src")]
    record: dict[str, Any] = {"schema": SCHEMA, "completed_inner": False}
    try:
        from decoy_engine import (
            detect_usable_cpus,
            resolve_conservative_ooc_budget_bytes,
            run_pipeline,
        )
        from decoy_engine.keyprovider import SecretKeyProvider

        config = json.loads(Path(args.config).read_text())
        threads = detect_usable_cpus()
        t0 = time.perf_counter()
        tables = _read_sources(config)
        t1 = time.perf_counter()
        result = run_pipeline(
            config,
            tables,
            engine_version="f24-lifecycle-accuracy",
            key_provider=SecretKeyProvider(b"decoy-bench-throwaway-secret-0123456789"),
            base_dir=Path(args.config).parent,
            # What the CLI's `_resources.run_pipeline_kwargs` passes for `auto` settings: the
            # usable CPUs and the conservative out-of-core budget, both from engine helpers.
            native_threads=threads,
            out_of_core_threads=threads,
            out_of_core_budget_bytes=resolve_conservative_ooc_budget_bytes(),
        )
        t2 = time.perf_counter()
        _write_targets(config, result.outputs)
        t3 = time.perf_counter()
        execution = result.quality_metrics.get("execution", {})
        record.update(
            completed_inner=True,
            realized_route=execution.get("execution_mode"),
            phase_wall_s={
                "ingest": round(t1 - t0, 2),
                "execute": round(t2 - t1, 2),
                "write": round(t3 - t2, 2),
            },
            rows_out={n: t.num_rows for n, t in result.outputs.items()},
        )
    except Exception as exc:
        record["error"] = _error_record(exc)
    Path(args.result_path).write_text(json.dumps(record))
    return 0


# ------------------------------------------------------------------------------ supervisor


def supervise(args: argparse.Namespace) -> dict[str, Any]:
    work = Path(tempfile.mkdtemp(prefix=f"f24-{args.cell}-", dir=args.work_root))
    try:
        config_path = work / "config.json"
        # The fixtures are built in their own process: `ru_maxrss` survives exec on Linux, so a
        # supervisor that held the fixture arrays would inflate every measured peak.
        subprocess.run(  # noqa: S603
            [sys.executable, str(Path(__file__).resolve()), "--build", "--cell", args.cell,
             "--rows", str(args.rows), "--config", str(config_path)],
            check=True,
        )  # fmt: skip
        config = json.loads(config_path.read_text())
        result_path = work / "result.json"
        cmd = [
            sys.executable, str(Path(__file__).resolve()), "--child", "--cell", args.cell,
            "--rows", str(args.rows), "--config", str(config_path), "--result-path", str(result_path),
        ]  # fmt: skip
        env = {**os.environ, "ARROW_DEFAULT_MEMORY_POOL": "system"}
        outcome = run_worker(
            cmd, env=env, result_path=result_path, timeout_s=args.timeout_s, rss_kill_mb=None
        )
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    failure = classify_failure(outcome)
    record = {
        "schema": SCHEMA,
        "cell": args.cell,
        "rows": args.rows,
        "completed": failure is None,
        "failure": failure,
        "peak_rss_mb": outcome.peak_rss_mb,
        "wall_s": round(outcome.wall_s, 2),
        "result": outcome.result or {},
        "config": config,
        "work_dir": str(work) if args.keep else None,
        "not_passed": ["vault_writer", "quarantine_path", "report flags"],
    }
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    return record


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--cell", required=True, choices=CELLS)
    ap.add_argument("--rows", type=int, required=True)
    ap.add_argument("--work-root", default=None)
    ap.add_argument("--timeout-s", type=float, default=3600.0)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--out", default=None, help="also write the full record (with config) here")
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--build", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--config", help=argparse.SUPPRESS)
    ap.add_argument("--result-path", help=argparse.SUPPRESS)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.build:
        config_path = Path(args.config)
        config_path.write_text(json.dumps(build_cell(args.cell, args.rows, config_path.parent)))
        return 0
    if args.child:
        return run_child(args)
    record = supervise(args)
    if args.out:
        Path(args.out).write_text(json.dumps(record))
    print(f"BENCH_JSON {json.dumps({k: v for k, v in record.items() if k != 'config'})}")
    return 0 if record["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
