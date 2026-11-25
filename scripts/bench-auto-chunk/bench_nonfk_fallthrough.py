"""NONFK-OOM baseline (plan 2026-11-19-nonfk-oom, section 9): peak memory of a non-FK mask job
that falls through to the full-frame route, against the strict lower bound `lower_bound_bytes`.

Workloads (one table each, Parquet in, Parquet file sink, `int64` with nulls kept as passthrough
so the chunked gate declines the table today):

  W-P  the W2 mix (3 hash, 3 passthrough, 2 redact, 2 truncate) plus `ni`, int64 with nulls
  W-S  W-P plus one `shuffle` column
  W-U  W-S plus a unique string ID column, hashed (the common PII shape)
  W-D  W-S plus two dictionary-typed string columns, a fresh dictionary per row group

Verbs, all on one file so the driver and its workers stay in step:

  drive    prepare each source, run warmup + rounds fresh processes per cell, write one JSON
  prepare  write one workload's Parquet source with a bounded writer loop
  run      one `run_pipeline` call in this process; prints evidence JSON to --out
  estimate read the source whole and print the static estimate (kept out of any measured run)
  e2e      one `decoy run` of a workload from a Parquet `path:` source under a cgroup cap, with the
           exit code, the registered code in stderr, and the target and staging checks (S5)

A refused run (`ExecutionError`) is recorded as an outcome, not a crash: the code, whether the error
chains cleanly, and every entry that appeared under the work directory or the temp root.

Run on a Linux node under the box-wide lock, from a worktree with the companion built:

    PYTHONPATH=src python scripts/bench-auto-chunk/bench_nonfk_fallthrough.py drive --out run.json

`--cgroup-bytes M` runs each worker under `systemd-run --user --scope -p MemoryMax=M`.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SEED = 20261119
TABLE = "t"
ENGINE_VERSION = "bench-nonfk-oom"
GROUP_ROWS = 1_048_576
WORKLOADS = ("W-P", "W-S", "W-U", "W-D")
ADMISSION_FRACTION = 0.85  # the plan's A = 0.85 H, recorded so the table shows the planned ceilings
SELF = Path(__file__).resolve()
REFUSAL_CODE = "nonfk_full_frame_capacity_exceeded"
EXIT_CAPACITY = 5  # `decoy run` exit for a capacity refusal (CLI exit_codes.EXIT_CAPACITY)


def refusal_evidence(exc: BaseException) -> dict[str, Any]:
    """The code and chaining of a refused run: never the message, which carries byte counts only."""
    return {
        "code": getattr(exc, "code", None),
        "clean_chaining": exc.__cause__ is None and exc.__context__ is None,
    }


def snapshot_entries(roots: list[Path]) -> set[str]:
    out: set[str] = set()
    for root in roots:
        if root.is_dir():
            out.update(str(child) for child in root.iterdir())
    return out


def new_entries(before: set[str], after: set[str]) -> list[str]:
    return sorted(after - before)


def e2e_refused_cleanly(
    exit_code: int, stderr: str, target_exists: bool, staging: list[str]
) -> bool:
    """The S5 expectation: exit 5, the registered code on stderr, no target file, no staging."""
    return (
        exit_code == EXIT_CAPACITY and REFUSAL_CODE in stderr and not target_exists and not staging
    )


def _status(key: str) -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(key + ":"):
            return int(line.split()[1]) * 1024
    raise RuntimeError(key)


def _text(prefix: str, ints: Any, suffix: str = "") -> Any:
    import pyarrow as pa
    import pyarrow.compute as pc

    return pc.binary_join_element_wise(
        pa.scalar(prefix), pc.cast(ints, pa.string()), pa.scalar(suffix), ""
    )


def build_chunk(workload: str, rng: Any, start: int, rows: int) -> Any:
    import numpy
    import pyarrow as pa

    k = pa.array(rng.integers(0, 10**9, size=rows, dtype=numpy.int64))
    ni = rng.integers(0, 2**60, size=rows, dtype=numpy.int64)
    ni_mask = (numpy.arange(rows) + start) % 7 == 0
    columns: dict[str, Any] = {
        "h1": _text("user", k, "@example.com"),
        "h2": _text("name-", k),
        "h3": _text("acct-", k),
        "p1": _text("keep-", k),
        "p2": _text("ref-", k),
        "p3": _text("note-", k),
        "r1": _text("secret-", k),
        "r2": _text("token-", k),
        "t1": _text("", k),
        "t2": _text("z", k),
        "ni": pa.array(ni, mask=ni_mask),
    }
    if workload != "W-P":
        columns["sh"] = _text("sh-", k)
    if workload == "W-U":
        columns["uid"] = _text("id-", pa.array(numpy.arange(start, start + rows)))
    if workload == "W-D":
        values = pa.array([f"dictionary-value-{i:03d}-" + "x" * 24 for i in range(40)])
        for name in ("d1", "d2"):
            codes = pa.array(rng.integers(0, 40, size=rows, dtype=numpy.int32))
            columns[name] = pa.DictionaryArray.from_arrays(codes, values)
    return pa.table(columns)


def build_config(workload: str, source_path: str) -> dict[str, Any]:
    from decoy_engine.config import PipelineConfig

    def col(name: str, strategy: str, **extra: Any) -> dict[str, Any]:
        return {"name": name, "strategy": strategy, **extra}

    columns = [
        *(col(n, "hash", namespace="bench_ns") for n in ("h1", "h2", "h3")),
        *(col(n, "passthrough") for n in ("p1", "p2", "p3", "ni")),
        *(col(n, "redact") for n in ("r1", "r2")),
        *(col(n, "truncate", provider_config={"length": 3, "keep": "head"}) for n in ("t1", "t2")),
    ]
    if workload != "W-P":
        columns.append(col("sh", "shuffle"))
    if workload == "W-U":
        columns.append(col("uid", "hash", namespace="bench_ns"))
    if workload == "W-D":
        columns += [col("d1", "passthrough"), col("d2", "passthrough")]
    return PipelineConfig.model_validate(
        {
            "version": 2,
            "global_settings": {
                "seed": 42,
                "post_validation": False,
                "mask_secret_ref": "env:DECOY_MASK_SECRET",
            },
            "sources": {TABLE: {"type": "file", "format": "parquet", "path": source_path}},
            "tables": [{"name": TABLE, "columns": columns}],
            "targets": {TABLE: {"type": "file", "format": "parquet", "path": "/dev/null"}},
        }
    ).model_dump()


def prepare(args: argparse.Namespace) -> int:
    import numpy
    import pyarrow.parquet as pq

    rng = numpy.random.default_rng(SEED)
    writer: Any = None
    start = 0
    while start < args.rows:
        rows = min(GROUP_ROWS, args.rows - start)
        chunk = build_chunk(args.workload, rng, start, rows)
        writer = writer or pq.ParquetWriter(args.path, chunk.schema)
        writer.write_table(chunk)
        start += rows
    if writer is not None:
        writer.close()
    return 0


def run(args: argparse.Namespace) -> int:
    import pyarrow.parquet as pq

    from decoy_engine.execution import ExecutionError, run_pipeline
    from decoy_engine.execution._transactional_sink import ParquetTransactionalSink
    from decoy_engine.execution.out_of_core._budget import detect_effective_memory_bytes
    from decoy_engine.execution.pipeline import lazy_spec, lower_bound_bytes, resident_spec
    from decoy_engine.profile._readers import LazySource

    config = build_config(args.workload, args.source)
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    Path("/proc/self/clear_refs").write_text("5")
    floor = _status("VmRSS")
    started = time.perf_counter()
    if args.input == "resident":
        source: Any = pq.read_table(args.source).unify_dictionaries()
        spec = resident_spec(source)
    else:
        source = LazySource(Path(args.source))
        meta = pq.ParquetFile(args.source)
        spec = lazy_spec(meta.metadata.num_rows, meta.schema_arrow)
    lower_bound = lower_bound_bytes([spec])
    watched = [workdir, workdir / "out", Path(tempfile.gettempdir())]
    before = snapshot_entries(watched)
    refusal: dict[str, Any] | None = None
    result: Any = None
    try:
        result = run_pipeline(
            config,
            sources={TABLE: source},
            sink=ParquetTransactionalSink(workdir / "out"),
            engine_version=ENGINE_VERSION,
            native_threads=1,
        )
    except ExecutionError as exc:
        refusal = refusal_evidence(exc)
    wall_s = time.perf_counter() - started
    hwm = _status("VmHWM")
    leftover = [e for e in new_entries(before, snapshot_entries(watched)) if "evidence" not in e]
    kill = detect_effective_memory_bytes()
    evidence = {
        "workload": args.workload,
        "rows": args.rows,
        "input": args.input,
        "wall_s": wall_s,
        "floor_bytes": floor,
        "peak_bytes": hwm,
        "increment_bytes": hwm - floor,
        "lower_bound_bytes": lower_bound,
        "admission_ceiling_bytes": int(kill * ADMISSION_FRACTION),
        "kill_ceiling_bytes": kill,
        "refusal": refusal,
        "new_entries": leftover,
        "auto_chunk": result.quality_metrics.get("auto_chunk") if result else None,
        "execution": result.quality_metrics.get("execution") if result else None,
        "resident_fit": result.quality_metrics.get("resident_fit") if result else None,
    }
    Path(args.out).write_text(json.dumps(evidence, allow_nan=False, indent=1))
    return 0


def estimate(args: argparse.Namespace) -> int:
    import pyarrow.parquet as pq

    from decoy_engine.execution._mem_estimate import estimate_peak_bytes
    from decoy_engine.execution._mem_estimate_schema import table_size_spec_from_table

    spec = table_size_spec_from_table(TABLE, pq.read_table(args.source))
    print(json.dumps({"estimate_bytes": estimate_peak_bytes([spec], "full_frame").estimated_bytes}))
    return 0


def passthrough_only(config: dict[str, Any]) -> dict[str, Any]:
    """The same job with every column passthrough: reads and writes, so it measures ingest."""
    plain = json.loads(json.dumps(config))
    for table in plain["tables"]:
        table["columns"] = [
            {"name": c["name"], "strategy": "passthrough"} for c in table["columns"]
        ]
    return plain


def e2e_config(workload: str, source: Path, target: Path, plain: bool = False) -> dict[str, Any]:
    config = build_config(workload, str(source))
    config["targets"] = {TABLE: {"type": "file", "format": "parquet", "path": str(target)}}
    return passthrough_only(config) if plain else config


def e2e(args: argparse.Namespace) -> int:
    """One `decoy run` under a cgroup cap; the verdict is `e2e_refused_cleanly` on what it left."""
    import yaml

    work = Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)
    source = Path(args.source)
    target = work / "out.parquet"
    target.unlink(missing_ok=True)
    cfg = work / "job.yaml"
    cfg.write_text(yaml.safe_dump(e2e_config(args.workload, source, target, args.passthrough_only)))
    watched = [work, Path(tempfile.gettempdir())]
    before = snapshot_entries(watched)
    cmd = [args.decoy, "run", str(cfg), "--quiet"]
    if args.cgroup_bytes:
        cmd = [
            "systemd-run", "--user", "--scope", "-q",
            "-p", f"MemoryMax={args.cgroup_bytes}", "-p", "MemorySwapMax=0", *cmd,
        ]  # fmt: skip
    started = time.perf_counter()
    done = subprocess.run(cmd, env=_env(), check=False, capture_output=True, text=True)  # noqa: S603
    child_peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024
    wall_s = time.perf_counter() - started
    staging = [e for e in new_entries(before, snapshot_entries(watched)) if e != str(cfg)]
    staging = [e for e in staging if Path(e) != target]
    evidence = {
        "workload": args.workload,
        "rows": args.rows,
        "cgroup_bytes": args.cgroup_bytes,
        "exit_code": done.returncode,
        "wall_s": wall_s,
        "passthrough_only": args.passthrough_only,
        "child_peak_rss_bytes": child_peak,
        "code_in_stderr": REFUSAL_CODE in done.stderr,
        "target_exists": target.exists(),
        "new_entries": staging,
        "refused_cleanly": e2e_refused_cleanly(
            done.returncode, done.stderr, target.exists(), staging
        ),
    }
    Path(args.out).write_text(json.dumps(evidence, allow_nan=False, indent=1))
    return 0


def _worker(*argv: str) -> None:
    subprocess.run([sys.executable, str(SELF), *argv], check=True, env=_env())  # noqa: S603


def _env() -> dict[str, str]:
    # A fixed throwaway secret: the keyed strategies refuse to run without one.
    secret = "0" * 64
    return {
        **os.environ,
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "DECOY_MASK_SECRET": secret,
    }


def _trial(
    cell: dict[str, Any], source: Path, work: Path, cgroup_bytes: int | None
) -> dict[str, Any]:
    out = work / "evidence.json"
    out.unlink(missing_ok=True)
    cmd = [
        sys.executable, str(SELF), "run",
        "--workload", cell["workload"], "--rows", str(cell["rows"]),
        "--source", str(source), "--input", cell["input"],
        "--workdir", str(work / "w"), "--out", str(out),
    ]  # fmt: skip
    if cgroup_bytes:
        cmd = [
            "systemd-run",
            "--user",
            "--scope",
            "-q",
            "-p",
            f"MemoryMax={cgroup_bytes}",
            "-p",
            "MemorySwapMax=0",
            *cmd,
        ]
    done = subprocess.run(cmd, env=_env(), check=False)  # noqa: S603
    if done.returncode != 0 or not out.exists():
        return {"exit_status": done.returncode}
    return {"exit_status": 0, **json.loads(out.read_text())}


def drive(args: argparse.Namespace) -> int:
    cells: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(dir=args.workdir) as tmp:
        base = Path(tmp)
        for rows in args.rows:
            for workload in args.workloads:
                source = base / f"{workload}-{rows}.parquet"
                _worker(
                    "prepare", "--workload", workload, "--rows", str(rows), "--path", str(source)
                )
                cell = {"workload": workload, "rows": rows, "input": args.input}
                if not args.no_estimate:
                    est = subprocess.run(  # noqa: S603
                        [sys.executable, str(SELF), "estimate", "--source", str(source)],
                        check=True, capture_output=True, text=True, env=_env(),
                    )  # fmt: skip
                    cell["static_estimate_bytes"] = json.loads(est.stdout)["estimate_bytes"]
                trials = [
                    _trial(cell, source, base, args.cgroup_bytes)
                    for _ in range(args.warmup + args.rounds)
                ][args.warmup :]
                refused = [t for t in trials if t["exit_status"] == 0 and t.get("refusal")]
                ok = [t for t in trials if t["exit_status"] == 0 and not t.get("refusal")]
                cell["trials"] = trials
                cell["refused"] = len(refused)
                if refused:
                    cell["refusal_codes"] = sorted({t["refusal"]["code"] for t in refused})
                    cell["refusal_wall_s_median"] = statistics.median(t["wall_s"] for t in refused)
                    cell["refusal_new_entries"] = [e for t in refused for e in t["new_entries"]]
                if ok:
                    cell["lower_bound_bytes"] = ok[0]["lower_bound_bytes"]
                    cell["peak_bytes"] = [t["peak_bytes"] for t in ok]
                    cell["peak_median"] = statistics.median(cell["peak_bytes"])
                    cell["increment_bytes"] = [t["increment_bytes"] for t in ok]
                    cell["peak_at_least_lb"] = min(cell["peak_bytes"]) >= cell["lower_bound_bytes"]
                    # The increment leaves out the interpreter and imports: the stricter reading.
                    cell["increment_at_least_lb"] = (
                        min(cell["increment_bytes"]) >= cell["lower_bound_bytes"]
                    )
                    cell["wall_s_median"] = statistics.median(t["wall_s"] for t in ok)
                cells.append(cell)
                source.unlink()
    Path(args.out).write_text(
        json.dumps({"cgroup_bytes": args.cgroup_bytes, "cells": cells}, indent=1)
    )
    bad = [
        c
        for c in cells
        if c.get("peak_at_least_lb") is False or c.get("increment_at_least_lb") is False
    ]
    for c in bad:
        print(f"PEAK BELOW LOWER BOUND: {c['workload']} {c['rows']}", file=sys.stderr)
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="verb", required=True)
    d = sub.add_parser("drive")
    d.add_argument("--out", required=True)
    d.add_argument("--rows", type=int, nargs="+", default=[1_000_000, 10_000_000])
    d.add_argument("--workloads", nargs="+", choices=WORKLOADS, default=list(WORKLOADS))
    d.add_argument("--input", choices=("lazy", "resident"), default="lazy")
    d.add_argument("--rounds", type=int, default=3)
    d.add_argument("--warmup", type=int, default=1)
    d.add_argument("--cgroup-bytes", type=int, default=None)
    d.add_argument("--no-estimate", action="store_true")
    d.add_argument("--workdir", default=tempfile.gettempdir())
    d.set_defaults(func=drive)
    p = sub.add_parser("prepare")
    p.add_argument("--workload", choices=WORKLOADS, required=True)
    p.add_argument("--rows", type=int, required=True)
    p.add_argument("--path", required=True)
    p.set_defaults(func=prepare)
    r = sub.add_parser("run")
    r.add_argument("--workload", choices=WORKLOADS, required=True)
    r.add_argument("--rows", type=int, required=True)
    r.add_argument("--source", required=True)
    r.add_argument("--input", choices=("lazy", "resident"), required=True)
    r.add_argument("--workdir", required=True)
    r.add_argument("--out", required=True)
    r.set_defaults(func=run)
    e = sub.add_parser("estimate")
    e.add_argument("--source", required=True)
    e.set_defaults(func=estimate)
    e2 = sub.add_parser("e2e")
    e2.add_argument("--workload", choices=WORKLOADS, required=True)
    e2.add_argument("--rows", type=int, required=True)
    e2.add_argument("--source", required=True)
    e2.add_argument("--workdir", required=True)
    e2.add_argument("--out", required=True)
    e2.add_argument("--decoy", default="decoy")
    e2.add_argument("--passthrough-only", action="store_true")
    e2.add_argument("--cgroup-bytes", type=int, default=None)
    e2.set_defaults(func=e2e)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
