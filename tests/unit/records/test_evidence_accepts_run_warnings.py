"""Every warning a run result can carry must be accepted by the evidence model.

The CLI writes the engine's `QualityWarning` entries into the `cli-local-1` manifest, and
`EvidencePayload` refuses a warning with an empty provider or a non-scalar `detail`. The
out-of-core residency warning did both, so those runs stored no evidence. The fix is at the
producer; this test is the class guard.

Coverage: the residency warning constructor for every shape subset, three real out-of-core runs,
and every warning recorded in the R3 within-route baseline (all execution routes). Warnings that
only validation, profiling or generation paths outside those scenarios raise are not enumerated.
"""

from __future__ import annotations

import json
from copy import deepcopy
from itertools import combinations
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.execution._pipeline import run_pipeline
from decoy_engine.execution._residency_warning import (
    residency_quality_warning,
)
from decoy_engine.generation.pool._events import QualityWarning
from tests._declared_schema import file_schemas
from tests.unit.execution.test_out_of_core_routing import _fk_ooc_config, _sources
from tests.unit.records._helpers import corpus, make

_BASELINE = Path(__file__).parents[1] / "execution" / "r3_within_route_baseline.json"
_ALL_SHAPES = (
    "a resident pa.Table source",
    "no sink (the whole output is held resident)",
    "a source_loader (returns an unbounded resident table)",
)


def _as_manifest_warning(w: QualityWarning) -> dict[str, Any]:
    """The warning as the CLI manifest carries it: its four fields, unchanged."""
    return {"code": w.code, "provider": w.provider, "column": w.column, "detail": dict(w.detail)}


def _accepted(warnings: list[QualityWarning]) -> None:
    manifest = deepcopy(corpus("evidence-cli-local-1.json"))
    manifest["warnings"] = [_as_manifest_warning(w) for w in warnings]
    make("evidence", manifest, labels={})  # raises RecordError when the model refuses


@pytest.mark.parametrize(
    "shapes",
    [c for n in (1, 2, 3) for c in combinations(_ALL_SHAPES, n)],
    ids=lambda s: "+".join(str(len(x)) for x in s),
)
def test_residency_warning_is_accepted_for_every_shape_subset(shapes: tuple[str, ...]) -> None:
    _accepted([residency_quality_warning(shapes)])


def _run(tmp_path: Path, **kw: Any) -> Any:
    config = _fk_ooc_config(tmp_path)
    return run_pipeline(
        config, _sources(config), engine_version="0.1.0", execution_mode="out_of_core", **kw
    )


def test_ooc_fk_hash_redact_run_warnings_are_accepted(tmp_path: Path) -> None:
    # The CLI finding: a resident multi-table FK mask on the out-of-core route.
    result = _run(tmp_path)
    assert result.quality_metrics["execution"]["execution_mode"] == "out_of_core"
    assert result.warnings, "the route must carry the residency warning, or this proves nothing"
    _accepted(list(result.warnings))


def test_ooc_run_with_sink_warnings_are_accepted(tmp_path: Path) -> None:
    from decoy_engine.execution import ParquetTransactionalSink

    sink = ParquetTransactionalSink(tmp_path / "out")
    result = _run(tmp_path, sink=sink)
    assert result.warnings
    _accepted(list(result.warnings))


def test_ooc_loader_run_warnings_are_accepted(tmp_path: Path) -> None:
    import pyarrow.parquet as pq

    config = _fk_ooc_config(tmp_path)
    paths = {name: spec["path"] for name, spec in config["sources"].items()}
    result = run_pipeline(
        config,
        {},
        engine_version="0.1.0",
        execution_mode="out_of_core",
        source_loader=lambda name: pq.read_table(paths[name]),
        source_loader_schemas=file_schemas(config),
    )
    assert result.warnings
    _accepted(list(result.warnings))


def _baseline_warnings() -> list[QualityWarning]:
    found: list[QualityWarning] = []

    def walk(node: Any) -> None:
        if isinstance(node, str) and node.startswith("QualityWarning("):
            # Repo-owned snapshot text; only QualityWarning is resolvable.
            found.append(eval(node, {"__builtins__": {}}, {"QualityWarning": QualityWarning}))  # noqa: S307
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(json.loads(_BASELINE.read_text()))
    return found


def test_every_baseline_route_warning_is_accepted() -> None:
    warnings = _baseline_warnings()
    assert {w.code for w in warnings} >= {"out_of_core_caller_managed_residency", "orphan_fk"}
    for w in warnings:
        _accepted([w])
