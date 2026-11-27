"""NONFK-OOM S4c: the resident-fit checks that run before the route exists.

AT-C6b, AT-C11b, AT-C13, AT-C16, AT-C16b, AT-C19, AT-C20 and AT-C21 of
docs/plans/2026-11-19-nonfk-oom.md. The host ceiling `H` is stubbed so each boundary is hit
exactly, and every byte figure comes from the production lower bound over the same table. Do not
delete a cell, skip one or loosen an equality to pass.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import reasons
from decoy_engine.execution import _pipeline_full_frame as full_frame
from decoy_engine.execution import _pipeline_sources, run_pipeline
from decoy_engine.execution import out_of_core as ooc
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution.pipeline import _lazy_input, lazy_spec, lower_bound_bytes, resident_spec
from decoy_engine.execution.pipeline import _resident_bytes as rb
from decoy_engine.execution.pipeline import _resident_fit as rf
from decoy_engine.profile._readers import LazySource
from tests.acceptance._f06_support import ISO_DATE, column, config, validate
from tests.parity import _f2_mixed_support as mixed
from tests.unit.execution import _auto_chunk_support as support
from tests.unit.execution import _transform_testkit as tk

pytestmark = pytest.mark.filterwarnings("ignore")

CODE_UNVERIFIED = reasons.route.NONFK_FULL_FRAME_UNVERIFIED
CODE_REFUSED = reasons.runtime.NONFK_FULL_FRAME_CAPACITY_EXCEEDED
ROWS = 50
KW = {"engine_version": "s4c-test", "auto_chunk_threshold_rows": 10, "chunk_size_rows": 16}
FULL_FRAME_KW = {**KW, "auto_chunk": False}
KEPT = 40  # rows a transform keeps; enough that no column is near-unique


def _ceiling(monkeypatch: pytest.MonkeyPatch, kill: int) -> None:
    monkeypatch.setattr(ooc, "detect_effective_memory_bytes", lambda: kill)


def _static(monkeypatch: pytest.MonkeyPatch, value: int | None = 1) -> None:
    monkeypatch.setattr(rf, "_static_estimate", lambda ctx, names: value)


def _lb(table: pa.Table) -> int:
    return lower_bound_bytes([resident_spec(table)])


def _clean(err: BaseException) -> None:
    assert err.__cause__ is None
    assert err.__context__ is None


def _footer_bytes(lazy: LazySource, *, pandas: bool) -> int:
    facts = lazy.footer_facts()
    return lower_bound_bytes([lazy_spec(facts.num_rows, facts.schema, charge_pandas=pandas)])


def _declared_job(tmp_path: Path, rows: int = ROWS) -> tuple[dict[str, Any], LazySource]:
    """A lazy Parquet table the run must read whole (a declared-cast column)."""
    path = tmp_path / "t.parquet"
    pq.write_table(pa.table({"start": pa.array(["2020-01-02"] * rows)}), path)
    cols = [column("start", logical_type="date", parse_format=ISO_DATE, error_policy="null")]
    cfg = validate(config(cols, source_path=str(path), table="t"))
    cfg["sources"]["t"]["format"] = "parquet"
    return cfg, LazySource(path)


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every whole read of a lazy source, by each way the engine makes one."""
    seen: list[str] = []
    real_materialize = _pipeline_sources.materialize_source
    real_to_table = LazySource.to_table

    def materialize(value: Any) -> Any:
        seen.append("materialize_source")
        return real_materialize(value)

    def to_table(self: LazySource, *a: Any, **k: Any) -> Any:
        seen.append("to_table")
        return real_to_table(self, *a, **k)

    monkeypatch.setattr(_pipeline_sources, "materialize_source", materialize)
    monkeypatch.setattr(_lazy_input, "materialize_source", materialize)
    monkeypatch.setattr(LazySource, "to_table", to_table)
    return seen


@pytest.fixture
def routed(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, dict[str, Any]]]:
    """The decision and keywords each full-frame continuation received."""
    seen: list[tuple[Any, dict[str, Any]]] = []
    real = full_frame.run_full_frame_route

    def spy(ctx: Any, decision: Any, **kwargs: Any) -> Any:
        seen.append((decision, kwargs))
        return real(ctx, decision, **kwargs)

    monkeypatch.setattr(full_frame, "run_full_frame_route", spy)
    return seen


# ---- AT-C16, AT-C16b: the footer bound before a whole read -------------------------------


def test_at_c16_a_footer_bound_beyond_the_kill_ceiling_refuses_before_any_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reads: list[str]
) -> None:
    cfg, lazy = _declared_job(tmp_path)
    needed = _footer_bytes(lazy, pandas=False)
    assert needed > 0
    _ceiling(monkeypatch, needed - 1)
    with pytest.raises(ExecutionError) as caught:
        run_pipeline(cfg, {"t": lazy}, resident_fallback=True, **KW)
    assert caught.value.code == CODE_REFUSED
    _clean(caught.value)
    assert reads == []


@pytest.mark.parametrize(
    "above", [0, 1, 50], ids=["bound-equals-H", "above-the-bound", "far-above"]
)
def test_at_c16_a_bound_at_or_under_the_kill_ceiling_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reads: list[str], above: int
) -> None:
    # The bound sits between A (0.85 H) and H: evidence in that range never refuses.
    cfg, lazy = _declared_job(tmp_path)
    _ceiling(monkeypatch, _footer_bytes(lazy, pandas=False) + above)
    run_pipeline(cfg, {"t": lazy}, resident_fallback=True, **KW)
    assert reads, "the table was never read, so the boundary proved nothing"


def test_at_c16_a_lazy_table_the_executor_reads_whole_is_refused_before_it_is_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route-time half: priced at its full bound in `decide_route`, before the executor's
    `resolve_resident_sources` reads it."""
    cfg, lazy = _declared_job(tmp_path)
    resolved: list[str] = []
    monkeypatch.setattr(
        full_frame._psrc, "resolve_resident_sources", lambda *a, **k: resolved.append("resolve")
    )
    _ceiling(monkeypatch, _footer_bytes(lazy, pandas=True) - 1)
    _static(monkeypatch)
    with pytest.raises(ExecutionError) as caught:
        run_pipeline(cfg, {"t": lazy}, **FULL_FRAME_KW)
    assert caught.value.code == CODE_REFUSED
    _clean(caught.value)
    assert resolved == []


def test_at_c16_a_vault_run_is_priced_at_input_bytes_so_the_chunked_lane_can_take_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A vault run is not forced to full-frame: the auto-chunk lane still bounds it. Footer input
    under H and full bound over H must run chunked, not refuse before the read."""
    from decoy_engine.vault import vault_writer_for_config

    src = pa.table({"h": pa.array([f"u{i}@x.example" for i in range(40)])})
    path = support.write_source(src, tmp_path / "v.parquet")
    cfg = support.make_cfg([{**support.hash_col("h"), "vault": True}], path=path)
    lazy = LazySource(Path(path))
    full = _footer_bytes(lazy, pandas=True)
    assert _footer_bytes(lazy, pandas=False) <= full - 1 < full
    _ceiling(monkeypatch, full - 1)
    got = run_pipeline(
        cfg,
        {"t": lazy},
        vault_writer=vault_writer_for_config(cfg),
        resident_fallback=True,
        **KW,
    )
    assert got.quality_metrics["auto_chunk"]["mode"] == "chunked"
    assert got.outputs["t"].num_rows == 40


@pytest.mark.parametrize("kill_factor", [0.8, 1.05], ids=["lb-above-H", "lb-between-A-and-H"])
def test_at_c16b_a_table_that_routes_chunked_is_not_charged_a_pandas_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kill_factor: float
) -> None:
    """Input bytes under A, full bound (input plus pandas) above A. The chunked lane never
    makes the pandas copy, so the pre-read check must not charge it: it runs today."""
    cfg, lazy = _declared_job(tmp_path)
    full = _footer_bytes(lazy, pandas=True)
    kill = int(full * kill_factor)
    assert _footer_bytes(lazy, pandas=False) < rf.admission_ceiling_bytes(kill) < full
    _ceiling(monkeypatch, kill)
    got = run_pipeline(cfg, {"t": lazy}, resident_fallback=True, **KW)
    assert got.quality_metrics["auto_chunk"]["mode"] == "chunked"


def test_at_c6b_a_subset_job_refused_before_its_read_leaves_no_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decoy_engine.execution.pipeline import _subset_stage
    from decoy_engine.subset import sample_request

    roots: list[Path] = []
    real = _subset_stage.engine_scratch_root

    def spy(base: Any) -> Any:
        scope = real(base)

        class _Spy:
            def __enter__(self) -> Any:
                root = scope.__enter__()
                roots.append(Path(root))
                return root

            def __exit__(self, *exc: Any) -> Any:
                return scope.__exit__(*exc)

        return _Spy()

    monkeypatch.setattr(_subset_stage, "engine_scratch_root", spy)
    monkeypatch.setenv("SUB_STOP_TEST_SECRET", "ab" * 32)
    cfg, lazy = _declared_job(tmp_path)
    _ceiling(monkeypatch, 1)
    with pytest.raises(ExecutionError) as caught:
        run_pipeline(
            cfg,
            {"t": lazy},
            resident_fallback=True,
            subset_request=sample_request(cfg, rows=20),
            **KW,
        )
    assert caught.value.code == CODE_REFUSED
    assert roots, "the subset stage never opened its scratch root"
    assert not any(root.exists() for root in roots)


# ---- AT-C11b, AT-C13, AT-C19: what step P leaves alone -----------------------------------


def _fk_job(tmp_path: Path, **transforms: Any) -> tuple[dict[str, Any], dict[str, pa.Table]]:
    parent = pa.table({"id": [f"p{i}" for i in range(20)], "note": [f"n{i}" for i in range(20)]})
    child = pa.table(
        {"cid": [f"c{i}" for i in range(20)], "parent_id": [f"p{i}" for i in range(20)]}
    )
    return tk.fk_config(tmp_path, parent, child, **transforms), {"parent": parent, "child": child}


def test_at_c11b_a_foreign_key_job_is_not_priced_before_its_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reads: list[str]
) -> None:
    fk_cfg, _ = _fk_job(tmp_path)
    fk_lazy = {n: LazySource(Path(s["path"])) for n, s in fk_cfg["sources"].items()}
    detected: list[str] = []
    monkeypatch.setattr(rf, "kill_ceiling", lambda: detected.append("asked") or 1)
    # Fidelity rules the bounded route out, so the pre-pass reads both tables whole.
    run_pipeline(fk_cfg, fk_lazy, resident_fallback=True, fidelity_report=True, **KW)
    assert "materialize_source" in reads
    assert detected == []

    # The same kind of read with no foreign key does ask for the ceiling.
    flat, lazy = _declared_job(tmp_path)
    monkeypatch.setattr(rf, "kill_ceiling", lambda: detected.append("asked") or (1 << 40))
    run_pipeline(flat, {"t": lazy}, resident_fallback=True, **KW)
    assert detected == ["asked"]


def _csv_loader_job(tmp_path: Path) -> tuple[dict[str, Any], pa.Table]:
    """A CSV source, which has no footer: only a loader can hand its rows to the engine."""
    table = pa.table({"s": [f"v{i % 5}" for i in range(ROWS)], "n": [i % 7 for i in range(ROWS)]})
    cfg = support.make_cfg(
        [support.redact_col("s"), support.pass_col("n")],
        path=support.write_source(table, tmp_path / "t.parquet"),
    )
    csv = tmp_path / "t.csv"
    table.to_pandas().to_csv(csv, index=False)
    cfg["sources"]["t"] = {"type": "file", "format": "csv", "has_header": True, "path": str(csv)}
    return cfg, table


def test_at_c13_a_csv_source_has_no_footer_and_runs_unverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    routed: list[tuple[Any, dict[str, Any]]],
) -> None:
    cfg, table = _csv_loader_job(tmp_path)
    _ceiling(monkeypatch, 1 << 40)
    _static(monkeypatch)
    with caplog.at_level(logging.INFO, logger=rf.__name__):
        got = run_pipeline(
            cfg,
            {},
            source_loader=lambda name: table,
            source_loader_schemas={"t": table.schema},
            **FULL_FRAME_KW,
        )
    assert got.outputs["t"].num_rows == ROWS
    fit = routed[-1][0].resident_fit
    assert (fit.verdict, fit.code) == ("UNKNOWN", CODE_UNVERIFIED)
    lines = [r.getMessage() for r in caplog.records if r.name == rf.__name__]
    assert lines == [f"resident fit unverified: {CODE_UNVERIFIED}"]


def test_at_c13_a_source_with_no_readable_footer_is_not_priced_before_its_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reads: list[str]
) -> None:
    cfg, lazy = _declared_job(tmp_path)

    def no_footer(self: LazySource) -> Any:
        raise OSError("no footer")

    # `LazySource` reads Parquet only, so a footer that cannot be read stands in for CSV.
    monkeypatch.setattr(LazySource, "footer_facts", no_footer)
    _ceiling(monkeypatch, 1)  # a priced table would be refused
    run_pipeline(cfg, {"t": lazy}, resident_fallback=True, **KW)
    assert "materialize_source" in reads


def test_at_c19_a_loader_job_has_a_schema_and_no_row_count_so_it_runs_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, routed: list[tuple[Any, dict[str, Any]]]
) -> None:
    table = pa.table({"s": [f"v{i % 5}" for i in range(ROWS)], "n": list(range(ROWS))})
    path = support.write_source(table, tmp_path / "t.parquet")
    cfg = support.make_cfg([support.redact_col("s"), support.pass_col("n")], path=path)
    loaded: list[str] = []

    def loader(name: str) -> pa.Table:
        loaded.append(name)
        return table

    _ceiling(monkeypatch, 1 << 40)
    _static(monkeypatch)
    got = run_pipeline(
        cfg, {}, source_loader=loader, source_loader_schemas={"t": table.schema}, **FULL_FRAME_KW
    )
    assert got.outputs["t"].num_rows == ROWS
    fit = routed[-1][0].resident_fit
    assert (fit.verdict, fit.code) == ("UNKNOWN", CODE_UNVERIFIED)
    assert loaded == ["t"]


# ---- AT-C20: the transform copy ----------------------------------------------------------


def _transform_job(tmp_path: Path) -> tuple[dict[str, Any], pa.Table]:
    # Low cardinality: a near-unique column is a risk column, and a risk column never proves a fit.
    table = pa.table(
        {"s": [f"value-{i % 9}" for i in range(ROWS)], "n": [i % 7 for i in range(ROWS)]}
    )
    cfg = tk.single_table_config(
        tmp_path,
        table,
        transforms=[{"op": "limit", "n": KEPT}],
        columns=[{"name": "s", "strategy": "redact"}],
    )
    return cfg, table


@pytest.fixture
def copies(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each stage a refusal must come before: the transform copy and the route decision."""
    from decoy_engine.execution import _pipeline, _transforms_prepare, _transforms_table

    seen: list[str] = []

    def spy(owner: Any, name: str) -> None:
        real = getattr(owner, name)

        def wrapped(*a: Any, **k: Any) -> Any:
            seen.append(name)
            return real(*a, **k)

        monkeypatch.setattr(owner, name, wrapped)

    spy(_transforms_prepare, "apply_resident_table")
    spy(_transforms_table, "to_transform_frame")
    spy(_pipeline._ctx, "decide_route")
    return seen


def test_at_c20_a_resident_table_whose_transform_copy_cannot_fit_is_refused_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, copies: list[str]
) -> None:
    cfg, table = _transform_job(tmp_path)
    needed_bytes = _lb(table)
    assert resident_spec(table).resident_input_bytes < rf.admission_ceiling_bytes(needed_bytes - 1)
    _ceiling(monkeypatch, needed_bytes - 1)
    with pytest.raises(ExecutionError) as caught:
        run_pipeline(cfg, {"t": table}, **KW)
    assert caught.value.code == CODE_REFUSED
    _clean(caught.value)
    assert copies == []


def _arrow_backed_job(tmp_path: Path, *, shared_strings: bool) -> tuple[dict[str, Any], pa.Table]:
    """An int64[pyarrow] column plus a low-cardinality string column to redact.

    The transform frame hands an Arrow-backed pandas column the same buffers, so it adds no bytes;
    a plain `object` string column is a real copy.
    """
    strings = [f"value-{i % 9}" for i in range(ROWS)]
    frame = pd.DataFrame(
        {
            "n": pd.array(list(range(ROWS)), dtype="int64[pyarrow]"),
            "s": pd.array(strings, dtype="large_string[pyarrow]" if shared_strings else "object"),
        }
    )
    table = pa.Table.from_pandas(frame, preserve_index=False)
    cfg = tk.single_table_config(
        tmp_path,
        table,
        transforms=[{"op": "limit", "n": 1}],
        columns=[{"name": "s", "strategy": "redact"}],
    )
    return cfg, table


def test_at_c20c_a_pandas_copy_that_shares_the_input_buffers_is_not_charged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutation M-A2: charge the pandas frame in full; the refusal below then fires."""
    cfg, table = _arrow_backed_job(tmp_path, shared_strings=True)
    need = rb.input_bytes([resident_spec(table, charge_pandas=False)])
    assert _lb(table) == need  # every pandas column shares: the bound is the input alone
    assert 2 * need > need  # the old double charge would exceed the ceiling set next
    _ceiling(monkeypatch, need)
    _static(monkeypatch)
    got = run_pipeline(cfg, {"t": table}, **FULL_FRAME_KW)
    assert got.outputs["t"].num_rows == 1


def test_at_c20c_a_column_that_does_not_share_is_still_charged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, copies: list[str]
) -> None:
    cfg, table = _arrow_backed_job(tmp_path, shared_strings=False)
    need = rb.input_bytes([resident_spec(table, charge_pandas=False)])
    assert _lb(table) == need + ROWS * 8  # the object column's pointers; `n` shares
    _ceiling(monkeypatch, need)
    with pytest.raises(ExecutionError) as caught:
        run_pipeline(cfg, {"t": table}, **KW)
    assert caught.value.code == CODE_REFUSED
    assert copies == []


def test_at_c20c_a_32_bit_offset_string_column_is_charged_its_widened_offsets(
    tmp_path: Path,
) -> None:
    """The frame shares the string payload but allocates new 64-bit offsets; refuse at the ceiling.

    4,096 one-char `ArrowDtype(string)` values: 20,484 input bytes, 32,776 bytes of new offsets.
    """
    from types import SimpleNamespace

    rows = 4096
    frame = pd.DataFrame({"s": pd.array(["x"] * rows, dtype=pd.ArrowDtype(pa.string()))})
    table = pa.Table.from_pandas(frame, preserve_index=False)
    cfg = tk.single_table_config(
        tmp_path,
        table,
        transforms=[{"op": "limit", "n": 1}],
        columns=[{"name": "s", "strategy": "redact"}],
    )
    ceiling = 30_000
    assert rb.input_bytes([resident_spec(table, charge_pandas=False)]) < ceiling
    assert _lb(table) == 53_260  # measured: 20,484 input + 8 * (rows + 1 terminal offset)
    with pytest.raises(ExecutionError) as caught:
        rf.check_pre_transform(
            cfg, {"t": table}, SimpleNamespace(edges=[]), "auto", kill_ceiling_bytes=ceiling
        )
    assert caught.value.code == CODE_REFUSED


def test_at_c20c_each_chunk_of_a_widened_string_column_adds_a_terminal_offset() -> None:
    frame = pd.DataFrame({"s": pd.array(["x"] * 10, dtype=pd.ArrowDtype(pa.string()))})
    one = pa.Table.from_pandas(frame, preserve_index=False)
    table = pa.concat_tables([one, one, one])
    assert table.column("s").num_chunks == 3
    spec = resident_spec(table)
    assert spec.pandas_widened == frozenset({"s"})
    assert rb.pandas_bytes([spec]) == (30 + 3) * 8


def test_at_c20c_a_binary_column_the_frame_reuses_is_not_charged(tmp_path: Path) -> None:
    """The frame reuses binary offsets and payload, so 4,096 one-byte values fit a 30,000 ceiling."""
    from types import SimpleNamespace

    rows = 4096
    frame = pd.DataFrame({"b": pd.array([b"x"] * rows, dtype=pd.ArrowDtype(pa.binary()))})
    table = pa.Table.from_pandas(frame, preserve_index=False)
    cfg = tk.single_table_config(
        tmp_path,
        table,
        transforms=[{"op": "limit", "n": 1}],
        columns=[{"name": "b", "strategy": "redact"}],
    )
    assert _lb(table) == rb.input_bytes([resident_spec(table, charge_pandas=False)]) < 30_000
    rf.check_pre_transform(
        cfg, {"t": table}, SimpleNamespace(edges=[]), "auto", kill_ceiling_bytes=30_000
    )


def test_at_c20_a_lazy_fallback_source_is_read_once_then_refused_before_its_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, copies: list[str], reads: list[str]
) -> None:
    cfg, table = _transform_job(tmp_path)
    cfg["post_scan"] = {"integrity": True}
    lazy = LazySource(Path(cfg["sources"]["t"]["path"]))
    _ceiling(monkeypatch, _lb(table) - 1)
    with pytest.raises(ExecutionError) as caught:
        run_pipeline(cfg, {"t": lazy}, resident_fallback=True, **KW)
    assert caught.value.code == CODE_REFUSED
    _clean(caught.value)
    assert reads.count("materialize_source") == 1
    assert copies == []


@pytest.mark.parametrize("edge", ["bound-equals-H", "bound-equals-A"])
def test_at_c20_a_bound_in_the_gap_runs_and_caps_the_verdict_at_unverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    routed: list[tuple[Any, dict[str, Any]]],
    edge: str,
) -> None:
    cfg, table = _transform_job(tmp_path)
    needed_bytes = _lb(table)
    kill = needed_bytes
    if edge == "bound-equals-A":
        kill = int(needed_bytes / rf.RESIDENT_ADMISSION_FRACTION)
        while rf.admission_ceiling_bytes(kill) > needed_bytes:
            kill -= 1
        while rf.admission_ceiling_bytes(kill) < needed_bytes:
            kill += 1
    assert rf.admission_ceiling_bytes(kill) <= needed_bytes <= kill
    _ceiling(monkeypatch, kill)
    _static(monkeypatch)
    got = run_pipeline(cfg, {"t": table}, **FULL_FRAME_KW)
    assert got.outputs["t"].num_rows == KEPT
    # The rows left after the transform would fit alone; the copy before it might not.
    fit = routed[-1][0].resident_fit
    assert (fit.verdict, fit.code) == ("UNKNOWN", CODE_UNVERIFIED)


def test_at_c20_a_bound_under_the_admission_ceiling_leaves_the_verdict_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, routed: list[tuple[Any, dict[str, Any]]]
) -> None:
    cfg, table = _transform_job(tmp_path)
    _ceiling(monkeypatch, _lb(table) * 20)
    _static(monkeypatch)
    run_pipeline(cfg, {"t": table}, **FULL_FRAME_KW)
    assert routed[-1][0].resident_fit.verdict == "FIT"


def test_at_c20_a_forced_mode_or_a_foreign_key_job_is_not_priced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, table = _transform_job(tmp_path)
    asked: list[str] = []
    monkeypatch.setattr(rf, "kill_ceiling", lambda: asked.append("asked") or 1)
    run_pipeline(cfg, {"t": table}, execution_mode="full_frame", **KW)
    fk_cfg, tables = _fk_job(
        tmp_path, parent_transforms=[{"op": "filter", "expression": "id != ''"}]
    )
    run_pipeline(fk_cfg, tables, **KW)
    assert asked == []

    # The same transform job under `auto` does ask for the ceiling (here it refuses).
    with pytest.raises(ExecutionError):
        run_pipeline(cfg, {"t": table}, **KW)
    assert asked == ["asked"]


# ---- AT-C21: a mixed job that declines after generation ----------------------------------


def _mixed_job(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any], int]:
    child = mixed.child_table(pa.array(list(range(40)), pa.int64()))
    cfg = mixed.mixed_config(tmp_path, child, coupled=False)
    lazy = LazySource(Path(cfg["sources"][mixed.CHILD]["path"]))
    return cfg, {mixed.CHILD: lazy}, child.num_rows


def _run_mixed(cfg: dict[str, Any], sources: dict[str, Any]) -> Any:
    return run_pipeline(
        cfg,
        sources,
        engine_version=mixed.ENGINE_VERSION,
        key_provider=mixed.key_provider(),
        **mixed.LANE_KW,
    )


@pytest.fixture
def declined(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Force every mixed run to decline at runtime; record each resolve of the sources."""
    from decoy_engine.execution import _pipeline_mixed_route as mixed_route

    monkeypatch.setattr(mixed_route, "_runtime_decline", lambda *a, **k: "forced_for_test")
    resolved: list[str] = []
    real = full_frame._psrc.resolve_resident_sources

    def resolve(*a: Any, **k: Any) -> Any:
        resolved.append("resolve")
        return real(*a, **k)

    monkeypatch.setattr(full_frame._psrc, "resolve_resident_sources", resolve)
    return resolved


def test_at_c21_a_mixed_decline_that_cannot_fit_is_refused_before_the_sources_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, declined: list[str], reads: list[str]
) -> None:
    cfg, sources, _rows = _mixed_job(tmp_path)
    _static(monkeypatch)
    _ceiling(monkeypatch, _footer_bytes(sources[mixed.CHILD], pandas=True) - 1)
    with pytest.raises(ExecutionError) as caught:
        _run_mixed(cfg, sources)
    assert caught.value.code == CODE_REFUSED
    _clean(caught.value)
    assert declined == []
    assert reads == []


def test_at_c21_the_generated_tables_count_at_input_bytes_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    declined: list[str],
    routed: list[tuple[Any, dict[str, Any]]],
) -> None:
    cfg, sources, _rows = _mixed_job(tmp_path)
    lazy_full = _footer_bytes(sources[mixed.CHILD], pandas=True)
    _static(monkeypatch)
    _ceiling(monkeypatch, lazy_full * 50)
    _run_mixed(cfg, sources)
    decision, kwargs = routed[-1]
    generated = rb.input_bytes(
        resident_spec(t, charge_pandas=False) for t in kwargs["pregenerated"].values()
    )
    assert generated > 0
    assert decision.resident_fit.lower_bound_bytes == lazy_full + generated
    assert decision.resident_fit.table_count == 1


def test_at_c21_a_total_in_the_gap_is_unverified_and_runs_and_one_byte_less_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    declined: list[str],
    routed: list[tuple[Any, dict[str, Any]]],
) -> None:
    cfg, sources, rows = _mixed_job(tmp_path)
    _static(monkeypatch)
    _ceiling(monkeypatch, 1 << 40)
    _run_mixed(cfg, sources)
    total = routed[-1][0].resident_fit.lower_bound_bytes
    routed.clear()

    _ceiling(monkeypatch, total)
    got = _run_mixed(cfg, sources)
    assert got.outputs[mixed.CHILD].num_rows == rows
    fit = routed[-1][0].resident_fit
    assert fit.lower_bound_bytes == total
    assert (fit.verdict, fit.code) == ("UNKNOWN", CODE_UNVERIFIED)

    _ceiling(monkeypatch, total - 1)
    with pytest.raises(ExecutionError) as caught:
        _run_mixed(cfg, sources)
    assert caught.value.code == CODE_REFUSED
