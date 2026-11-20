"""ENGINE-THREADS-DEFAULT: `run_pipeline()` with no `native_threads` uses the usable cores.

Plan: docs/plans/2026-11-19-speed-batch-f1-f3-f4.md, section S3. Thread count never changes output
data on any route, so the default can move from 1 to the usable cores; the run record names where
the count came from (`explicit`, `auto`, `auto_fallback`).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import reasons
from decoy_engine.execution import run_pipeline
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution.native._chunked_entry import MAX_NATIVE_THREADS
from decoy_engine.execution.pipeline import _host
from decoy_engine.profile._readers import LazySource
from tests._declared_schema import declare_rest
from tests.parity import _f2_mixed_support as mx
from tests.parity import _gap9_jobs as jobs
from tests.unit.execution import _auto_chunk_support as support
from tests.unit.execution import _multi_table_support as mt

pytestmark = pytest.mark.serial  # patches the host CPU probe and compares thread counts

ENGINE = "s3-threads-default"


def _patch_cpus(monkeypatch: pytest.MonkeyPatch, cpus: int) -> None:
    monkeypatch.setattr(_host, "detect_usable_cpus", lambda **_: cpus)


def _patch_cpus_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**_: Any) -> int:
        raise ExecutionError(
            code=reasons.runtime.CPU_DETECTION_FAILED, message="cpu_limit_unreadable (test)"
        )

    monkeypatch.setattr(_host, "detect_usable_cpus", boom)


def _small_job(tmp_path: Path) -> tuple[dict[str, Any], dict[str, pa.Table]]:
    table = pa.table({"h": pa.array([f"u{i}@x.example" for i in range(40)])})
    path = tmp_path / "t.parquet"
    pq.write_table(table, path)
    cfg = support.make_cfg([support.hash_col("h")], path=str(path))
    return declare_rest(cfg), {support.TABLE: table}


def _run_small(tmp_path: Path, **kwargs: Any) -> Any:
    cfg, sources = _small_job(tmp_path)
    return run_pipeline(cfg, sources, engine_version=ENGINE, auto_chunk=False, **kwargs)


def _pair(block: dict[str, Any]) -> tuple[int, str]:
    record = block["native_threads"]
    return record["count"], record["source"]


def _block(result: Any) -> dict[str, Any]:
    return result.quality_metrics["execution"]


def test_default_resolves_to_usable_cpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cpus(monkeypatch, 3)
    block = _block(_run_small(tmp_path))
    assert _pair(block) == (3, "auto")


@pytest.mark.parametrize("threads", [1, 2])
def test_explicit_value_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, threads: int) -> None:
    _patch_cpus(monkeypatch, 8)
    block = _block(_run_small(tmp_path, native_threads=threads))
    assert _pair(block) == (threads, "explicit")


def test_detection_failure_falls_back_to_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_cpus_failing(monkeypatch)
    block = _block(_run_small(tmp_path))
    assert _pair(block) == (1, "auto_fallback")
    block = _block(_run_small(tmp_path, native_threads=2))
    assert _pair(block) == (2, "explicit")


def test_other_detection_errors_are_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**_: Any) -> int:
        raise ExecutionError(code=reasons.runtime.INVALID_EXECUTION_KNOB, message="x")

    monkeypatch.setattr(_host, "detect_usable_cpus", boom)
    with pytest.raises(ExecutionError):
        _host.native_threads_for_run(None)


def test_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cpus(monkeypatch, 5000)
    block = _block(_run_small(tmp_path))
    assert _pair(block) == (MAX_NATIVE_THREADS, "auto")
    assert MAX_NATIVE_THREADS == 1024


@pytest.mark.parametrize("bad", [0, -1, 1025, True, "4"])
def test_invalid_values_still_refused(tmp_path: Path, bad: Any) -> None:
    cfg, sources = _small_job(tmp_path)
    with pytest.raises(ExecutionError) as caught:
        run_pipeline(cfg, sources, engine_version=ENGINE, native_threads=bad)
    assert caught.value.code == reasons.runtime.INVALID_EXECUTION_KNOB


def test_isolated_run_resolves_in_the_child(tmp_path: Path) -> None:
    """An omitted value is forwarded as omitted; the child resolves and records the source."""
    from decoy_engine.execution import run_pipeline_isolated
    from tests.unit.execution.test_isolated_run import _mask_config, _mask_sources

    cfg = _mask_config(tmp_path, n_cols=2)
    sources = _mask_sources(tmp_path, n_rows=50, n_cols=2)
    result = run_pipeline_isolated(cfg, sources, engine_version=ENGINE)
    assert result.outcome == "completed", result.error
    block = _block(result)
    assert block["native_threads"]["source"] == "auto"
    assert block["native_threads"]["count"] >= 1


# -- every route -------------------------------------------------------------------------------

Outputs = dict[str, pa.Table]
Driver = Callable[[Path, Any], tuple[Any, Outputs]]


def _single(tmp_path: Path, columns: list[dict[str, Any]], table: pa.Table) -> dict[str, Any]:
    path = tmp_path / "single.parquet"
    pq.write_table(table, path)
    return declare_rest(support.make_cfg(columns, path=str(path)))


def _strings(n: int = 200) -> pa.Table:
    return pa.table(
        {
            "h": pa.array([f"u{i}@x.example" for i in range(n)]),
            "r": pa.array([f"s{i}" for i in range(n)]),
        }
    )


def _single_cols() -> list[dict[str, Any]]:
    return [support.hash_col("h"), support.redact_col("r")]


def _kw(**extra: Any) -> dict[str, Any]:
    return {"engine_version": ENGINE, **extra}


def drive_full_frame(tmp_path: Path, threads: Any) -> tuple[Any, Outputs]:
    table = _strings()
    cfg = _single(tmp_path, _single_cols(), table)
    result = run_pipeline(
        cfg,
        {support.TABLE: table},
        **_kw(
            execution_mode="full_frame",
            auto_chunk=False,
            unified_slice_enabled=False,
            native_threads=threads,
        ),
    )
    return result, result.outputs


def drive_unified_slice(tmp_path: Path, threads: Any) -> tuple[Any, Outputs]:
    table = _strings()
    cfg = _single(tmp_path, _single_cols(), table)
    result = run_pipeline(
        cfg, {support.TABLE: table}, **_kw(auto_chunk=False, native_threads=threads)
    )
    return result, result.outputs


def drive_chunked(tmp_path: Path, threads: Any) -> tuple[Any, Outputs]:
    table = _strings()
    cfg = _single(tmp_path, _single_cols(), table)
    result = run_pipeline(
        cfg,
        {support.TABLE: table},
        **_kw(auto_chunk_threshold_rows=10, chunk_size_rows=16, native_threads=threads),
    )
    return result, result.outputs


def drive_chunked_lazy_parquet(tmp_path: Path, threads: Any) -> tuple[Any, Outputs]:
    table = _strings()
    cfg = _single(tmp_path, _single_cols(), table)
    lazy = {support.TABLE: LazySource(path=tmp_path / "single.parquet")}
    result = run_pipeline(
        cfg,
        lazy,
        **_kw(auto_chunk_threshold_rows=10, chunk_size_rows=16, native_threads=threads),
    )
    return result, result.outputs


def drive_sequential(tmp_path: Path, threads: Any) -> tuple[Any, Outputs]:
    config, sources = jobs.seq_job(tmp_path, legacy_faker=False)
    kwargs = {} if threads is None else {"native_threads": threads}
    result = jobs.run_seq(config, sources, **kwargs)
    return result, result.outputs


def drive_out_of_core(tmp_path: Path, threads: Any) -> tuple[Any, Outputs]:
    config, paths = jobs.ooc_job(tmp_path)
    kwargs = {} if threads is None else {"native_threads": threads}
    result, tables = jobs.run_ooc(config, paths, tmp_path / "out", lane="batch", **kwargs)
    return result, tables


def drive_mixed(tmp_path: Path, threads: Any) -> tuple[Any, Outputs]:
    child = mx.child_table(pa.array([f"P{i % 5}" for i in range(60)], pa.string()))
    cfg = mx.mixed_config(tmp_path, child, coupled=False)
    result = mx.run(cfg, {mx.CHILD: child}, native_threads=threads)
    assert "mixed_route" in result.quality_metrics
    return result, result.outputs


def drive_generate_mask(tmp_path: Path, threads: Any) -> tuple[Any, Outputs]:
    child = mx.child_table(pa.array([f"P{i % 5}" for i in range(60)], pa.string()))
    cfg = mx.mixed_config(tmp_path, child, coupled=False)
    result = mx.run(cfg, {mx.CHILD: child}, mode="full_frame", native_threads=threads)
    return result, result.outputs


def drive_multi_table(tmp_path: Path, threads: Any) -> tuple[Any, Outputs]:
    tables = {
        "big": (mt.std_columns("nsb"), mt.string_table(mt.BIG, "b")),
        "big2": (mt.std_columns("nsc"), mt.string_table(mt.BIG, "c")),
    }
    cfg, sources = mt.build_job(tmp_path, tables)
    result = run_pipeline(cfg, sources=sources, **mt.kw(native_threads=threads))
    return result, result.outputs


def drive_pure_generate(tmp_path: Path, threads: Any) -> tuple[Any, Outputs]:
    raw = {
        "version": 2,
        "global_settings": {"seed": 5},
        "sources": {},
        "targets": {"gen": {"type": "file", "format": "csv", "path": "gen.out.csv"}},
        "tables": [
            {
                "name": "gen",
                "row_count": 50,
                "generate_columns": [{"name": "id", "type": "sequence", "start": 0, "step": 1}],
            }
        ],
        "relationships": [],
    }
    from decoy_engine.config import PipelineConfig

    cfg = PipelineConfig.model_validate(declare_rest(raw)).model_dump()
    result = run_pipeline(cfg, {}, **_kw(native_threads=threads))
    return result, result.outputs


ROUTES: dict[str, Driver] = {
    "full_frame": drive_full_frame,
    "unified_slice": drive_unified_slice,
    "chunked_native_lane": drive_chunked,
    "chunked_lazy_parquet": drive_chunked_lazy_parquet,
    "sequential": drive_sequential,
    "out_of_core": drive_out_of_core,
    "mixed": drive_mixed,
    "generate_mask_full_frame": drive_generate_mask,
    "multi_table": drive_multi_table,
    "pure_generate_full_frame": drive_pure_generate,
}


@mx.NEEDS_COMPANION
@pytest.mark.parametrize("route", sorted(ROUTES))
def test_default_output_bytes_equal_single_thread_per_route(
    route: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_cpus(monkeypatch, 4)
    drive = ROUTES[route]
    (tmp_path / "one").mkdir()
    (tmp_path / "auto").mkdir()
    one, want = drive(tmp_path / "one", 1)
    auto, got = drive(tmp_path / "auto", None)
    assert _block(one)["native_threads"]["count"] == 1
    assert _block(auto)["native_threads"]["count"] == 4
    assert sorted(got) == sorted(want)
    for name in want:
        assert got[name].schema.equals(want[name].schema), (route, name)
        assert mx.ipc_bytes(got[name]) == mx.ipc_bytes(want[name]), (route, name)


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_source_on_every_route(route: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The stamp is written once, after the route returns, so no route can skip it."""
    _patch_cpus(monkeypatch, 3)
    result, _ = ROUTES[route](tmp_path, None)
    block = _block(result)
    assert _pair(block) == (3, "auto"), route
    (tmp_path / "explicit").mkdir()
    result, _ = ROUTES[route](tmp_path / "explicit", 2)
    assert _block(result)["native_threads"]["source"] == "explicit", route


_RSS_CHILD = """
import resource, sys, tempfile
from pathlib import Path
from tests._keyed_secret import THROWAWAY_KEY_PROVIDER
from tests.parity import _gap9_jobs as jobs
tmp = Path(tempfile.mkdtemp())
config, paths = jobs.ooc_job(tmp, rows=20000)
kwargs = {"key_provider": THROWAWAY_KEY_PROVIDER}
if sys.argv[1] != "auto":
    kwargs["native_threads"] = 1
jobs.run_ooc(config, paths, tmp / "out", lane="batch", **kwargs)
print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
"""


@pytest.mark.benchmark
def test_out_of_core_rss_under_memory_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate-time check: the default's peak RSS on the out-of-core route (256 MiB budget) is at
    most 15% over the one-thread run, best of 3 each, on the same node."""
    import statistics
    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[3]

    def peak(mode: str) -> int:
        out = subprocess.run(  # noqa: S603
            [sys.executable, "-c", _RSS_CHILD, mode],
            cwd=repo,
            env={**os.environ, "PYTHONPATH": str(repo)},
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()[-1]
        return int(out)

    one = statistics.median(peak("one") for _ in range(3))
    auto = statistics.median(peak("auto") for _ in range(3))
    assert auto <= one * 1.15, (one, auto)
