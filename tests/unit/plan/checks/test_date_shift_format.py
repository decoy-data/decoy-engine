"""S4b: a date_shift column must name its `date_format`; the engine never guesses it.

The requirement sits in the strategy requirements registry. These tests cover the compile refusal
(top-level, nested and the declared-casting exemption), the run-time backstop, the shipped configs
and the starter that writes the detected variant.
"""

from __future__ import annotations

import copy
import importlib.util
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest
import yaml

from decoy_engine import reasons
from decoy_engine.contracts.column_shape import NO_SOURCES
from decoy_engine.contracts.declared_casting import date_shift_owns_declared_format
from decoy_engine.contracts.strategy_requirements import REQUIREMENTS_BY_STRATEGY
from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._pipeline import run_pipeline
from decoy_engine.execution._strategies._date_shift import DateShiftStrategyHandler
from decoy_engine.generation.pool._cache import PoolCache
from decoy_engine.plan import PlanCompileError, compile_plan, run_config_only_checks
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.plan.checks import check_required_strategy_settings
from decoy_engine.profile import Profile
from decoy_engine.profiling import scan_sources, starter_config
from decoy_engine.relationships._graph import RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceRegistry
from tests.acceptance._f06_support import (
    ISO_DATE,
    column,
    config,
    run,
    text_table,
    validate,
    write_csv,
)

REPO = Path(__file__).resolve().parents[4]
CODE = "date_shift_requires_date_format"

_EMPTY = Profile(
    schema_version=1,
    tables=(),
    relationships=(),
    profiled_at=datetime(2026, 1, 1),
    decoy_engine_version="0.1.0",
)


def _cfg(**provider_config: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": "dob", "strategy": "date_shift", "namespace": "ns"}
    if provider_config:
        entry["provider_config"] = provider_config
    return {"tables": [{"name": "t", "columns": [entry]}]}


def _nested_cfg(child: str, **strategy_config: Any) -> dict[str, Any]:
    pc: dict[str, Any] = {"strategy": child, "target": "$.a"}
    if strategy_config:
        pc["strategy_config"] = strategy_config
    entry = {"name": "doc", "strategy": "nested", "namespace": "ns", "provider_config": pc}
    return {"tables": [{"name": "t", "columns": [entry]}]}


def _refused_by_both(cfg: dict[str, Any]) -> list[PlanCompileError]:
    errors = []
    for call in (
        lambda: run_config_only_checks(cfg),
        lambda: compile_plan(cfg, _EMPTY, decoy_engine_version="0.1.0", sources=NO_SOURCES),
    ):
        with pytest.raises(PlanCompileError) as exc:
            call()
        errors.append(exc.value)
    return errors


# 1 ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["__absent__", None, "", "   ", 5, True])
def test_missing_format_refused(bad: Any) -> None:
    cfg = _cfg() if bad == "__absent__" else _cfg(date_format=bad)
    for err in _refused_by_both(cfg):
        assert err.code == CODE
        assert err.path == "tables.t.columns.dob.provider_config.date_format"


def test_a_real_format_passes() -> None:
    check_required_strategy_settings(_cfg(date_format="%Y-%m-%d"), sources=NO_SOURCES)


# 2 ---------------------------------------------------------------------------------------------


def test_refused_before_read(tmp_path: Path) -> None:
    src = write_csv(tmp_path / "s.csv", ["dob"], [["2026-01-01"]])
    raw = config([column("dob", "date_shift", namespace="dob")], source_path=src)
    calls: list[str] = []

    def loader(name: str) -> pa.Table:
        calls.append(name)
        return text_table(dob=["2026-01-01"])

    with pytest.raises(PlanCompileError) as exc:
        run_pipeline(
            validate(raw),
            engine_version="s4b-test",
            source_loader=loader,
            source_loader_schemas={"people": pa.schema([("dob", pa.string())])},
        )
    assert exc.value.code == CODE
    assert calls == []
    assert not list(tmp_path.glob("*.out"))


# 3 and 3b --------------------------------------------------------------------------------------


def test_nested_child_refused() -> None:
    for err in _refused_by_both(_nested_cfg("date_shift")):
        assert err.code == CODE
        assert err.path == "tables.t.columns.doc.provider_config.strategy_config.date_format"
    check_required_strategy_settings(
        _nested_cfg("date_shift", date_format="%Y-%m-%d"), sources=NO_SOURCES
    )


def test_nested_hash_child_without_namespace_compiles() -> None:
    cfg = _nested_cfg("hash")
    del cfg["tables"][0]["columns"][0]["namespace"]
    check_required_strategy_settings(
        cfg, sources=NO_SOURCES
    )  # a child takes its parent's namespace


# 4 ---------------------------------------------------------------------------------------------


def _declared(name: str = "d") -> dict[str, Any]:
    return column(
        name,
        "date_shift",
        namespace=name,
        logical_type="date",
        parse_format=ISO_DATE,
        error_policy="fail",
    )


def test_declared_casting_column_exempt(tmp_path: Path) -> None:
    src = write_csv(tmp_path / "p.csv", ["d"], [["2026-01-01"], ["2026-03-04"]])
    cfg = config([_declared()], source_path=src)
    result = run(cfg, {"people": text_table(d=["2026-01-01", "2026-03-04"])})
    assert result.outputs["people"].num_rows == 2


def test_nested_child_does_not_inherit_the_declared_exemption() -> None:
    nested = {
        "name": "doc",
        "strategy": "nested",
        "namespace": "ns",
        "provider_config": {"strategy": "date_shift", "target": "$.a"},
        # The parent itself declares a date parse format; its child must still name a format.
        "logical_type": "date",
        "parse_format": ISO_DATE,
    }
    cfg = {"tables": [{"name": "t", "columns": [_declared(), nested]}]}
    with pytest.raises(PlanCompileError) as exc:
        check_required_strategy_settings(cfg, sources=NO_SOURCES)
    assert exc.value.code == CODE
    assert exc.value.path == "tables.t.columns.doc.provider_config.strategy_config.date_format"


def test_exemption_predicate_is_top_level_only() -> None:
    own = {"logical_type": "date", "has_parse_format": True}
    assert date_shift_owns_declared_format(nested=False, **own)
    assert not date_shift_owns_declared_format(nested=True, **own)
    assert not date_shift_owns_declared_format(
        nested=False, logical_type="string", has_parse_format=True
    )
    assert not date_shift_owns_declared_format(
        nested=False, logical_type="date", has_parse_format=False
    )


# 5 ---------------------------------------------------------------------------------------------


def test_message_value_free() -> None:
    cfg = _cfg(date_format="  ")
    cfg["tables"][0]["columns"][0]["note"] = "CELL-VALUE-CANARY"
    for err in _refused_by_both(cfg):
        assert "CELL-VALUE-CANARY" not in str(err)
        assert "dob" in str(err) and "'t'" in str(err)
        assert err.__cause__ is None and err.__context__ is None


# 6 ---------------------------------------------------------------------------------------------


def test_reason_registered() -> None:
    assert reasons.plan.DATE_SHIFT_REQUIRES_DATE_FORMAT == CODE
    assert reasons.runtime.DATE_SHIFT_REQUIRES_DATE_FORMAT == CODE
    descriptors = REQUIREMENTS_BY_STRATEGY["date_shift"]
    match = [d for d in descriptors if d.path == ("provider_config", "date_format")]
    assert len(match) == 1 and match[0].code == reasons.plan.DATE_SHIFT_REQUIRES_DATE_FORMAT


# 7 ---------------------------------------------------------------------------------------------


def _manifest_tables(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        tables = node.get("tables")
        if isinstance(tables, list) and any(isinstance(t, dict) and "columns" in t for t in tables):
            found.extend(t for t in tables if isinstance(t, dict) and "columns" in t)
        for value in node.values():
            found.extend(_manifest_tables(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_manifest_tables(value))
    return found


@pytest.mark.parametrize("job", ["a_healthcare_claims", "b_retail_m2m"])
def test_shipped_testflight_configs_compile(job: str) -> None:
    spec = yaml.safe_load((REPO / "testflight" / "jobs" / job / "manifest.yaml").read_text())
    tables = _manifest_tables(spec)
    dated = [
        c
        for t in tables
        for c in t["columns"]
        if isinstance(c, dict) and c.get("strategy") == "date_shift"
    ]
    assert dated, job
    check_required_strategy_settings({"tables": tables}, sources=NO_SOURCES)


def test_shipped_proof_manifest_date_shift_compiles() -> None:
    path = REPO / "scripts" / "gen_proof_manifest.py"
    spec = importlib.util.spec_from_file_location("gen_proof_manifest", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    proofs = [p for p in mod.CAPABILITY_PROOFS if p.id == "mask.date_shift"]
    assert len(proofs) == 1
    check_required_strategy_settings(copy.deepcopy(proofs[0].config), sources=NO_SOURCES)


# 8 ---------------------------------------------------------------------------------------------

_VARIANTS = {
    "%Y-%m-%dT%H:%M:%S": ["2024-01-05T10:00:00", "2024-02-06T11:30:00"],
    "%Y-%m-%d %H:%M:%S": ["2024-01-05 10:00:00", "2024-02-06 11:30:00"],
    "%Y-%m-%d": ["2024-01-05", "2024-02-06", "2024-03-07"],
    "%Y%m%d": ["20240105", "20240206", "20240307"],
    "%m/%d/%Y": ["01/05/2024", "02/06/2024", "03/07/2024"],
    "%m/%d/%y": ["01/05/24", "02/06/24", "03/07/24"],
    "%d.%m.%Y": ["15.01.2024", "16.02.2024", "17.03.2024"],
    "%d-%m-%Y": ["15-01-2024", "16-02-2024", "17-03-2024"],
}
_NOT_COMPLETE = {
    "mixed variants": ["2024-01-05", "20240206", "2024-03-07", "20240408"],
    "T..HH:MMZ": ["2024-01-05T10:00Z", "2024-02-06T11:30Z", "2024-03-07T09:15Z"],
    "ShapeValid31.02": ["31.02.2024", "16.02.2024", "17.03.2024"],
    "padded": [" 2024-01-05", "2024-02-06 ", " 2024-03-07 "],
    "90 percent iso": [f"2024-01-{d:02d}" for d in range(1, 10)] + ["unknown"],
}


def _starter(tmp_path: Path, values: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    path = tmp_path / "t.csv"
    pd.DataFrame({"when": values}).to_csv(path, index=False)
    scan = scan_sources(
        {"t": {"type": "file", "format": "csv", "path": str(path), "has_header": True}}
    )
    result = starter_config(scan)
    return result.config["tables"][0]["columns"][0], result.config


def _compiles(config_: dict[str, Any]) -> None:
    from decoy_engine.config import PipelineConfig
    from decoy_engine.profile import profile_source

    dumped = PipelineConfig.model_validate(config_).model_dump()
    compile_plan(
        dumped, profile_source(dumped, seed=1), decoy_engine_version="test", sources=NO_SOURCES
    )


@pytest.mark.parametrize(("fmt", "values"), list(_VARIANTS.items()))
def test_starter_writes_detected_variant(tmp_path: Path, fmt: str, values: list[str]) -> None:
    entry, cfg = _starter(tmp_path, values)
    assert entry["strategy"] == "date_shift", fmt
    assert entry["provider_config"]["date_format"] == fmt
    parsed = pd.to_datetime(pd.Series(values), format=entry["provider_config"]["date_format"])
    assert not parsed.isna().any()
    _compiles(cfg)


@pytest.mark.parametrize("name", list(_NOT_COMPLETE))
def test_starter_redacts_when_no_complete_variant(tmp_path: Path, name: str) -> None:
    entry, cfg = _starter(tmp_path, _NOT_COMPLETE[name])
    assert entry["strategy"] == "redact", name
    _compiles(cfg)


# 9 ---------------------------------------------------------------------------------------------


def _ctx(**kw: Any) -> StrategyContext:
    ctx = StrategyContext(
        registry=None,  # type: ignore[arg-type]
        pool_cache=PoolCache(),
        relationship_graph=RelationshipGraph(edges=(), ordering=()),
        namespace_registry=NamespaceRegistry(bindings=()),
        job_seed=(0x1).to_bytes(8, "big"),
        mask_key=b"k" * 32,
        **kw,
    )
    object.__setattr__(ctx, "current_table", "t")
    return ctx


def _seed(**pc: Any) -> ColumnSeed:
    return ColumnSeed(
        namespace="ns",
        strategy="date_shift",
        provider="date_shift",
        backend_type="faker",
        backend_version="v",
        cardinality_mode="reuse",
        provider_config=tuple(sorted(pc.items())),
    )


def test_handler_backstop() -> None:
    df = pd.DataFrame({"d": ["2024-01-05", "2024-02-06"]})
    handler = DateShiftStrategyHandler()
    with pytest.raises(StrategyError) as exc:
        handler.run(df, "d", _seed(), _ctx())
    assert exc.value.code == CODE
    # The same top-level column with its own declared contract does not raise.
    declared = _ctx(declared_date_columns=frozenset({("t", "d")}))
    out, _ = handler.run(pd.DataFrame({"d": ["2024-01-05"]}), "d", _seed(), declared)
    assert len(out) == 1
    # A nested child of that declared column still raises.
    nested = _ctx(declared_date_columns=frozenset({("t", "d")}))
    object.__setattr__(nested, "nested_outer_column", "d")
    with pytest.raises(StrategyError) as exc2:
        handler.run(df.rename(columns={"d": "_nested_leaves"}), "_nested_leaves", _seed(), nested)
    assert exc2.value.code == CODE
    # Date objects (a declared date32 cell) in a column the plan does not declare still raise.
    objects = pd.DataFrame({"d": pd.Series([pd.Timestamp("2024-01-05").date()], dtype=object)})
    with pytest.raises(StrategyError):
        handler.run(objects, "d", _seed(), _ctx())
