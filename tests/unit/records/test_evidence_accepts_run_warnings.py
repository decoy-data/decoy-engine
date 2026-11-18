"""Every warning a run result can carry must be accepted by the evidence model.

The CLI writes the engine's `QualityWarning` entries into the `cli-local-1` manifest, and
`EvidencePayload` refuses a warning with an empty provider or a non-scalar `detail`. The
out-of-core residency warning did both, so those runs stored no evidence. The rule is enforced
where every warning is built, `QualityWarning.__post_init__`, so the guard is on that choke point:

- a property over arbitrary provider, column and detail inputs: whatever the constructor accepts,
  the evidence model accepts too. This covers every producer, including ones no scenario here runs;
- a recorder on the constructor, so every warning built during the real out-of-core runs is
  checked, whether or not the run result carries it;
- the residency warning for every shape subset and the warnings of the R3 within-route baseline.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from copy import deepcopy
from itertools import combinations
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from decoy_engine.execution._pipeline import run_pipeline
from decoy_engine.execution._residency_warning import (
    _SHAPE_FLAGS,
    residency_quality_warning,
)
from decoy_engine.generation.pool._events import QualityWarning
from tests._declared_schema import file_schemas
from tests.unit.execution.test_out_of_core_routing import _fk_ooc_config, _sources
from tests.unit.records._helpers import corpus, make

_BASELINE = Path(__file__).parents[1] / "execution" / "r3_within_route_baseline.json"
_ALL_SHAPES = tuple(_SHAPE_FLAGS)


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


_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=40),
)
_DETAIL_VALUES = st.one_of(
    _SCALARS,
    st.lists(st.text(max_size=20), max_size=4),
    st.lists(st.integers(), max_size=3),  # refused by the constructor
    st.dictionaries(st.text(max_size=8), st.integers(), max_size=3),  # refused by the constructor
)


@settings(max_examples=150, deadline=None, derandomize=True)
@given(
    provider=st.one_of(st.just(""), st.text(min_size=1, max_size=20)),
    column=st.one_of(st.none(), st.just(""), st.text(min_size=1, max_size=20)),
    detail=st.dictionaries(st.text(min_size=1, max_size=12), _DETAIL_VALUES, max_size=5),
)
def test_whatever_the_constructor_accepts_the_evidence_model_accepts(
    provider: str, column: str | None, detail: dict[str, Any]
) -> None:
    try:
        warning = QualityWarning(code="orphan_fk", provider=provider, column=column, detail=detail)
    except (ValueError, TypeError):
        return  # refused at the choke point: no producer can ship it
    _accepted([warning])


@pytest.fixture
def built_warnings(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[QualityWarning]]:
    """Every QualityWarning constructed while the test runs, recorded after the choke point."""
    built: list[QualityWarning] = []
    original = QualityWarning.__post_init__

    def record(self: QualityWarning) -> None:
        original(self)
        built.append(self)

    monkeypatch.setattr(QualityWarning, "__post_init__", record)
    return built


def _run(tmp_path: Path, **kw: Any) -> Any:
    config = _fk_ooc_config(tmp_path)
    return run_pipeline(
        config, _sources(config), engine_version="0.1.0", execution_mode="out_of_core", **kw
    )


def test_ooc_fk_hash_redact_run_warnings_are_accepted(
    tmp_path: Path, built_warnings: list[QualityWarning]
) -> None:
    # The CLI finding: a resident multi-table FK mask on the out-of-core route.
    result = _run(tmp_path)
    assert result.quality_metrics["execution"]["execution_mode"] == "out_of_core"
    assert result.warnings, "the route must carry the residency warning, or this proves nothing"
    _accepted(list(result.warnings))
    assert built_warnings, "the recorder saw no warning; it is not on the constructor"
    _accepted(built_warnings)


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


def test_residency_warning_refuses_an_unknown_shape() -> None:
    # A new shape must get a flag in `_SHAPE_FLAGS`; dropping it silently would hide the shape.
    with pytest.raises(KeyError):
        residency_quality_warning(("a shape with no flag",))
