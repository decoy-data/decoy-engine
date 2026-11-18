"""DI-T4 (pipeline half), DI-T6, DI-T7, DI-T8 and DI-T9a: the distribution check inside a run (row 31).

`post_scan.distribution` adds a `distribution` section to the post-scan report: one value-free row
per checked fact of every mask table. The source side is read through the gate's `_source`, so
declared casting, subset and D8 quarantine all apply to it. All values are made up.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import run_pipeline
from decoy_engine.execution import ExecutionError, _pipeline_route_dispatch
from decoy_engine.execution._strategies import SCALAR_HANDLERS
from decoy_engine.execution._strategies._passthrough import PassthroughHandler
from decoy_engine.execution._transactional_sink import ParquetTransactionalSink
from decoy_engine.execution.pipeline._post_scan import PostScanGate
from decoy_engine.profile import LazySource
from decoy_engine.verification.postmask import distribution as distribution_module
from tests._declared_schema import file_schemas
from tests.unit.detection_verification.postscan.test_distribution_preserved_facts import _fixtures
from tests.unit.execution import _auto_chunk_support as support
from tests.unit.execution import _subset_run_support as subset_sup
from tests.unit.execution.post_scan.test_wiring import _run as _wired_run
from tests.unit.execution.test_lazy_path_route_admission import (
    _ooc_eligible_config,
    _parent_child_tables,
)
from tests.unit.execution.test_sequential_run_kills import _fk_bucketize_config
from tests.unit.execution.test_sequential_run_kills import _sources as _bucketize_sources

V = "di-1b-gate"
CANARY = "CANARY-di1b-5521"
SINGLE_ROUTES = ["full_frame", "chunked"]
FK_ROUTES = ["full_frame", "sequential", "out_of_core"]
DEFERRED = "post_scan_distribution_deferred"
TRANSFORMED = "post_scan_integrity_transforms_unsupported"


@pytest.fixture(autouse=True)
def _subset_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(subset_sup.VAR, "ab" * 32)


def _table(n: int = 40) -> pa.Table:
    x: list[float | None] = [float(i) for i in range(n)]
    x[3] = None
    s: list[str | None] = [f"{CANARY}-{i}" for i in range(n)]
    s[5] = None
    return pa.table(
        {
            "x": pa.array(x, pa.float64()),
            "k": pa.array([f"k{i}" for i in range(n)], pa.string()),
            "s": pa.array(s, pa.string()),
        }
    )


COLUMNS = [
    support.pass_col("x"),
    support.hash_col("k"),
    support.redact_col("s"),
]


def _config(
    tmp_path: Path,
    table: pa.Table,
    columns: list[dict[str, Any]],
    *,
    tolerance: float = 5,
    distribution: bool = True,
) -> tuple[dict[str, Any], LazySource]:
    path = support.write_source(table, tmp_path / "t.parquet")
    cfg = support.make_cfg(columns, path=path)
    cfg["post_scan"] = {"integrity": True}
    if distribution:
        cfg["post_scan"]["distribution"] = {"tolerance_pct": tolerance}
    return cfg, LazySource(Path(path))


def _run(tmp_path: Path, cfg: dict[str, Any], table: pa.Table, lazy: LazySource, route: str) -> Any:
    """The single-table job on `full_frame` (resident output) or `chunked` (staged through the
    engine sink, so the gate reads staged files). The sequential and out-of-core routes need a
    relationship; `_fk_job` covers them."""
    if route == "full_frame":
        return run_pipeline(cfg, sources={support.TABLE: table}, engine_version=V, auto_chunk=False)
    return run_pipeline(
        cfg,
        sources={support.TABLE: lazy},
        sink=ParquetTransactionalSink(tmp_path / f"published-{route}"),
        engine_version=V,
        auto_chunk_threshold_rows=1,
        chunk_size_rows=7,
    )


def _fk_job(
    tmp_path: Path,
    *,
    note: dict[str, Any] | None = None,
    values: list[Any] | None = None,
    tolerance: float = 5,
) -> tuple[dict[str, Any], dict[str, pa.Table]]:
    """The parent/child job every bounded route admits, with `post_scan.distribution` on. `note`
    replaces the parent's `note` column spec and `values` its source cells."""
    parent, child = _parent_child_tables()
    if values is not None:
        parent = parent.set_column(1, "note", pa.array(values))
    cfg = _ooc_eligible_config(tmp_path, "parquet", tables=(parent, child))
    cfg["post_scan"] = {"integrity": True, "distribution": {"tolerance_pct": tolerance}}
    if note is not None:
        table = next(t for t in cfg["tables"] if t["name"] == "parent")
        table["columns"] = [c for c in table["columns"] if c["name"] != "note"] + [
            {**note, "name": "note"}
        ]
    return cfg, {"parent": parent, "child": child}


def _fk_run(tmp_path: Path, cfg: dict[str, Any], tables: dict[str, pa.Table], route: str) -> Any:
    sink = None if route == "full_frame" else ParquetTransactionalSink(tmp_path / f"out-{route}")
    result, seen = _wired_run(cfg, route, sources=tables, sink=sink)
    assert seen == [route]
    return result


def _rows(result: Any) -> list[dict[str, Any]]:
    return result.quality_metrics["post_scan_integrity"]["distribution"]


def _key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row["table"], row["column"], row["fact"])


# ----- DI-T4: a breach and a no-breach cell ----------------------------------------------------


class _Scale(PassthroughHandler):
    """A test-only handler: a passthrough that scales the column, so the facts really move."""

    output_is_input = False

    def run(self, df: Any, column: str, plan: Any, ctx: Any) -> tuple[Any, list[Any]]:
        if column != "x":
            return df, []
        out = df.copy()
        out[column] = out[column] * 1.5
        return out, []


def test_a_scaling_handler_in_place_of_passthrough_gives_breach_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = _table()
    cfg, lazy = _config(tmp_path, table, [support.pass_col("x")])
    monkeypatch.setitem(SCALAR_HANDLERS, "passthrough", _Scale())
    result = _run(tmp_path, cfg, table, lazy, "full_frame")
    rows = {_key(r): r for r in _rows(result)}
    for fact in ("mean", "std"):
        breach = rows[("t", "x", fact)]
        assert breach["severity"] == "warning" and breach["delta_pct"] is not None
    assert rows[("t", "x", "null_rate")]["severity"] == "info"
    assert rows[("t", None, "row_count")]["severity"] == "info"
    report = result.quality_metrics["post_scan_integrity"]
    assert report["warning_count"] >= 2
    assert report["verdict"]["blocking"] is False


def test_the_same_job_without_the_scaling_handler_has_no_breach_row(tmp_path: Path) -> None:
    table = _table()
    cfg, lazy = _config(tmp_path, table, [support.pass_col("x")])
    result = _run(tmp_path, cfg, table, lazy, "full_frame")
    rows = [r for r in _rows(result) if r["column"] in (None, "x")]
    assert {_key(r) for r in rows} == {
        ("t", None, "row_count"),
        ("t", "x", "null_rate"),
        ("t", "x", "mean"),
        ("t", "x", "std"),
        ("t", "x", "distinct_ratio"),
    }
    assert {r["severity"] for r in rows} == {"info"}
    assert result.quality_metrics["post_scan_integrity"]["warning_count"] == 0


def test_a_weighted_categorical_column_on_twenty_rows_gives_no_mean_or_distinct_row(
    tmp_path: Path,
) -> None:
    table = pa.table({"c": pa.array([["a", "b", "c"][i % 3] for i in range(20)], pa.string())})
    column = {
        "name": "c",
        "strategy": "categorical",
        "namespace": "c_ns",
        "provider_config": {"categories": ["a", "b", "c"], "weights": [0.5, 0.3, 0.2]},
    }
    cfg, lazy = _config(tmp_path, table, [column])
    rows = _rows(_run(tmp_path, cfg, table, lazy, "full_frame"))
    facts = {r["fact"] for r in rows if r["column"] == "c"}
    assert facts == {"null_rate"}


@pytest.mark.parametrize("route", SINGLE_ROUTES)
def test_the_report_holds_names_and_numbers_never_a_cell_value(tmp_path: Path, route: str) -> None:
    table = _table()
    cfg, lazy = _config(tmp_path, table, COLUMNS)
    report = _run(tmp_path, cfg, table, lazy, route).quality_metrics["post_scan_integrity"]
    text = json.dumps(report, allow_nan=False)
    assert CANARY not in text
    assert json.loads(text)["distribution"] == report["distribution"]


def test_a_run_without_the_block_has_no_distribution_section(tmp_path: Path) -> None:
    table = _table()
    cfg, lazy = _config(tmp_path, table, COLUMNS, distribution=False)
    report = _run(tmp_path, cfg, table, lazy, "full_frame").quality_metrics["post_scan_integrity"]
    assert "distribution" not in report


# ----- DI-T8: every route gives the resident rows ------------------------------------------------


def test_every_route_gives_the_rows_of_the_resident_run(tmp_path: Path) -> None:
    cfg, tables = _fk_job(tmp_path)
    seen = {route: _rows(_fk_run(tmp_path, cfg, tables, route)) for route in FK_ROUTES}
    resident = seen["full_frame"]
    # parent: row_count, id (null_rate, distinct_ratio), note (null_rate); child: the same for
    # its row count and its two hashed columns.
    assert {_key(r) for r in resident} >= {
        ("parent", None, "row_count"),
        ("parent", "id", "distinct_ratio"),
        ("parent", "note", "null_rate"),
        ("child", None, "row_count"),
        ("child", "parent_id", "distinct_ratio"),
    }
    assert {r["severity"] for r in resident} == {"info"}
    for route, rows in seen.items():
        assert rows == resident, route


def test_the_chunked_route_gives_the_rows_of_the_resident_run(tmp_path: Path) -> None:
    table = _table()
    cfg, lazy = _config(tmp_path, table, COLUMNS)
    resident = _rows(_run(tmp_path, cfg, table, lazy, "full_frame"))
    assert len(resident) == 8  # row_count; x: 4; k: 2; s: 1
    assert _rows(_run(tmp_path, cfg, table, lazy, "chunked")) == resident
    assert {r["severity"] for r in resident} == {"info"}


STREAMED_STRATEGIES = ["hash", "fpe", "categorical", "bucket_perturb", "text_redact", "text_mask"]


def _null_row(rows: list[dict[str, Any]], column: str) -> dict[str, Any]:
    return {_key(r): r for r in rows}[("t" if column == "val" else "parent", column, "null_rate")]


@pytest.mark.parametrize("strategy", STREAMED_STRATEGIES)
def test_a_null_bearing_column_keeps_its_null_rate_on_the_chunked_route(
    tmp_path: Path, strategy: str
) -> None:
    columns, values = _fixtures()[strategy]
    values = [None if i % 5 == 2 else v for i, v in enumerate(values)]
    table = pa.table({"val": pa.array(values)})
    cfg, lazy = _config(tmp_path, table, columns)
    nulls = _null_row(_rows(_run(tmp_path, cfg, table, lazy, "chunked")), "val")
    # A native kernel that filled the nulls would move this by 20 points.
    assert nulls["severity"] == "info" and nulls["delta_pct"] == 0.0, strategy


@pytest.mark.parametrize("strategy", STREAMED_STRATEGIES)
def test_a_null_bearing_column_keeps_its_null_rate_on_the_out_of_core_route(
    tmp_path: Path, strategy: str
) -> None:
    columns, values = _fixtures()[strategy]
    # The fixtures hold 20 values; the parent has 40 rows.
    cells = [None if i % 5 == 2 else values[i % 20] for i in range(40)]
    note = {**columns[0], "deterministic": True} if strategy == "categorical" else columns[0]
    cfg, tables = _fk_job(tmp_path, note=note, values=cells)
    nulls = _null_row(_rows(_fk_run(tmp_path, cfg, tables, "out_of_core")), "note")
    assert nulls["severity"] == "info" and nulls["delta_pct"] == 0.0, strategy


# ----- DI-T8 and DI-T9a: refusals before any route read -----------------------------------------


class _Dispatch:
    """Counts the route executors, so a refusal that came too late shows as a call."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []
        for name in (
            "execute_sequential_route",
            "execute_out_of_core_route",
            "execute_mixed_route",
        ):
            real = getattr(_pipeline_route_dispatch, name)
            monkeypatch.setattr(_pipeline_route_dispatch, name, self._wrap(name, real))

    def _wrap(self, name: str, real: Any) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            return real(*args, **kwargs)

        return call


def _refused(call: Any, code: str) -> None:
    with pytest.raises(ExecutionError) as caught:
        call()
    assert str(caught.value.code) == code
    assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.parametrize("route", SINGLE_ROUTES)
def test_a_transform_bearing_table_with_distribution_is_refused_before_any_route_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    table = _table()
    cfg, lazy = _config(tmp_path, table, [support.pass_col("x")])
    cfg["tables"][0]["transforms"] = [{"op": "filter", "expression": "x >= 0"}]
    spy = _Dispatch(monkeypatch)
    _refused(lambda: _run(tmp_path, cfg, table, lazy, route), TRANSFORMED)
    assert spy.calls == []
    assert not (tmp_path / f"published-{route}").exists()


def test_a_transform_bearing_parent_with_distribution_is_refused_on_the_sequential_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = "sequential"
    cfg, tables = _fk_job(tmp_path)
    next(t for t in cfg["tables"] if t["name"] == "parent")["transforms"] = [
        {"op": "filter", "expression": "id != 'zzz'"}
    ]
    spy = _Dispatch(monkeypatch)
    _refused(lambda: _fk_run(tmp_path, cfg, tables, route), TRANSFORMED)
    assert spy.calls == []
    assert not (tmp_path / f"out-{route}").exists()


def test_the_same_transform_bearing_config_without_distribution_runs_as_today(
    tmp_path: Path,
) -> None:
    table = _table()
    cfg, lazy = _config(tmp_path, table, [support.pass_col("x")], distribution=False)
    cfg["tables"][0]["transforms"] = [{"op": "filter", "expression": "x >= 0"}]
    result = _run(tmp_path, cfg, table, lazy, "full_frame")
    assert "distribution" not in result.quality_metrics["post_scan_integrity"]


@pytest.mark.parametrize("mode", ["auto", "sequential", "full_frame"])
def test_a_loader_run_with_distribution_is_refused_before_any_route_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    cfg, tables = _fk_job(tmp_path)
    spy = _Dispatch(monkeypatch)
    reads: list[str] = []

    def loader(name: str) -> pa.Table:
        reads.append(name)
        return tables[name]

    _refused(
        lambda: run_pipeline(
            cfg,
            sources={},
            source_loader=loader,
            source_loader_schemas=file_schemas(cfg),
            engine_version=V,
            execution_mode=mode,
        ),
        DEFERRED,
    )
    assert reads == [] and spy.calls == []


def test_a_loader_run_without_distribution_is_not_refused(tmp_path: Path) -> None:
    cfg, tables = _fk_job(tmp_path)
    del cfg["post_scan"]["distribution"]
    result = run_pipeline(
        cfg,
        sources={},
        source_loader=lambda name: tables[name],
        source_loader_schemas=file_schemas(cfg),
        engine_version=V,
        execution_mode="sequential",
    )
    assert "distribution" not in result.quality_metrics.get("post_scan_integrity", {})


def test_a_deferred_gate_with_distribution_is_refused_with_the_deferred_code() -> None:
    from decoy_engine.execution.pipeline._post_scan_distribution import distribution_refusal

    ctx = SimpleNamespace(
        config={"post_scan": {"integrity": True, "distribution": {"tolerance_pct": 5}}},
        has_mask_table=True,
        source_loader=None,
    )
    assert str(distribution_refusal(ctx, deferred=True)) == DEFERRED  # type: ignore[arg-type]
    assert distribution_refusal(ctx, deferred=False) is None  # type: ignore[arg-type]
    plain = SimpleNamespace(
        config={"post_scan": {"integrity": True}}, has_mask_table=True, source_loader=object()
    )
    assert distribution_refusal(plain, deferred=True) is None  # type: ignore[arg-type]


# ----- DI-T6: quarantine ---------------------------------------------------------------------------


def _quarantined_run(tmp_path: Path, mode: str, *, sink: bool) -> Any:
    qpath = tmp_path / "q.jsonl"
    cfg = _fk_bucketize_config(
        tmp_path, {"enabled": True, "output_path": str(qpath), "triggers": ["format_error"]}
    )
    cfg["post_scan"] = {"integrity": True, "distribution": {"tolerance_pct": 5}}
    extra = {"sink": ParquetTransactionalSink(tmp_path / "published")} if sink else {}
    return run_pipeline(
        cfg, sources=_bucketize_sources(cfg), engine_version=V, execution_mode=mode, **extra
    )


@pytest.mark.parametrize(
    ("mode", "sink"),
    [("full_frame", False), ("sequential", False), ("sequential", True)],
    ids=["resident", "streamed", "streamed_staged"],
)
def test_a_d8_quarantined_row_is_subtracted_from_the_expected_row_count(
    tmp_path: Path, mode: str, sink: bool
) -> None:
    result = _quarantined_run(tmp_path, mode, sink=sink)
    rows = {_key(r): r for r in _rows(result)}
    count = rows[("parent", None, "row_count")]
    # 6 source rows, 1 quarantined, 5 out: nothing is missing. Without the subtraction this is 16.7.
    assert count["delta_pct"] == 0.0 and count["severity"] == "info"


def test_the_source_side_facts_keep_the_rows_d8_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []
    real = distribution_module.value_facts

    def spy(table: Any, columns: Any, **kwargs: Any) -> Any:
        facts = real(table, columns, **kwargs)
        seen.extend(f.rows for f in facts.values())
        return facts

    monkeypatch.setattr(distribution_module, "value_facts", spy)
    _quarantined_run(tmp_path, "full_frame", sink=False)
    assert 6 in seen and 5 not in seen


def _gate(columns: list[dict[str, Any]], source: pa.Table, tolerance: float) -> PostScanGate:
    config = {
        "tables": [{"name": "t", "columns": columns}],
        "post_scan": {"integrity": True, "distribution": {"tolerance_pct": tolerance}},
    }
    return PostScanGate(config, sources={"t": source})


class _DroppingCast:
    """A declared cast that quarantines the rows at `drop` (absolute indices)."""

    def __init__(self, drop: set[int]) -> None:
        self._drop = drop

    def tables(self) -> set[str]:
        return {"t"}

    def declared_columns(self, name: str) -> tuple[str, ...]:
        return ()

    def cast_batch(self, name: str, table: Any, *, offset: int = 0, record: bool = True) -> Any:
        keep = [i for i in range(table.num_rows) if offset + i not in self._drop]
        return SimpleNamespace(table=table.take(pa.array(keep, pa.int64())))


def test_declared_cast_quarantine_drops_the_same_rows_on_both_sides() -> None:
    source = pa.table({"x": pa.array([float(i) for i in range(100)])})
    columns = [support.pass_col("x")]
    gate = _gate(columns, source, tolerance=1)
    gate.attach_cast_run(_DroppingCast({10, 20, 30}))
    out = source.take(pa.array([i for i in range(100) if i not in {10, 20, 30}], pa.int64()))
    gate.run_resident({"t": out}, {"t": source}, {"t": "mask"}, raw_sources=True)
    assert gate.report is not None
    rows = {_key(r): r for r in gate.report["distribution"]}
    # 97 rows read, 97 out: no gap. The footer count (100) would read as a 3.1% shortfall.
    assert rows[("t", None, "row_count")]["delta_pct"] == 0.0
    assert {r["severity"] for r in gate.report["distribution"]} == {"info"}


def test_the_d8_count_of_a_gate_is_subtracted_in_the_resident_check() -> None:
    source = pa.table({"x": pa.array([float(i) for i in range(100)])})
    gate = _gate([support.pass_col("x")], source, tolerance=1)
    gate.note_quarantined("t", source, {1, 2, 3})
    out = source.take(pa.array([i for i in range(100) if i not in {1, 2, 3}], pa.int64()))
    gate.run_resident({"t": out}, {"t": source}, {"t": "mask"}, raw_sources=True)
    assert gate.report is not None
    rows = {_key(r): r for r in gate.report["distribution"]}
    assert rows[("t", None, "row_count")]["delta_pct"] == 0.0


def test_without_a_note_the_same_missing_rows_are_a_breach() -> None:
    source = pa.table({"x": pa.array([float(i) for i in range(100)])})
    gate = _gate([support.pass_col("x")], source, tolerance=1)
    out = source.take(pa.array([i for i in range(100) if i not in {1, 2, 3}], pa.int64()))
    gate.run_resident({"t": out}, {"t": source}, {"t": "mask"}, raw_sources=True)
    assert gate.report is not None
    rows = {_key(r): r for r in gate.report["distribution"]}
    assert rows[("t", None, "row_count")]["severity"] == "warning"


# ----- DI-T7: subset ----------------------------------------------------------------------------


def test_the_source_side_of_a_subset_run_is_the_subset(tmp_path: Path) -> None:
    cfg, data, _ = subset_sup.job(tmp_path)
    cfg["post_scan"] = {"integrity": True, "distribution": {"tolerance_pct": 5}}
    result = run_pipeline(cfg, sources=data, engine_version=V, execution_mode="full_frame")
    rows = _rows(result)
    counts = [r for r in rows if r["fact"] == "row_count"]
    assert {r["table"] for r in counts} == {"customers", "orders", "items"}
    # The subset keeps 5 of 30 customers; against the unsubset 30 rows this would be a breach.
    assert {(r["severity"], r["delta_pct"]) for r in counts} == {("info", 0.0)}
