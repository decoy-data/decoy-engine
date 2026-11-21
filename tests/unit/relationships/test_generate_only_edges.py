"""Generate-only relationship edges take a derived namespace (CLI-QA1 DI-close E1).

A relationship whose parent and child tables are both generate tables masks nothing, so it needs no
`namespace`. A mask or mixed edge keeps the rule. The derived name stays inside `for_relationship`.
"""

from __future__ import annotations

import contextlib
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine import route_summary, run_pipeline
from decoy_engine.config import PipelineConfig
from decoy_engine.contracts.column_shape import NO_SOURCES
from decoy_engine.execution.capacity import estimate_job_capacity
from decoy_engine.plan import compile_plan
from decoy_engine.profile import Profile, Relationship
from decoy_engine.relationships import NamespaceConfigError, build_namespace_registry

ENGINE = "test"


def _gen_table(name: str, rows: int, cols: list[dict[str, Any]]) -> dict[str, Any]:
    return {"name": name, "row_count": rows, "generate_columns": cols}


def _mask_table(name: str, col: str) -> dict[str, Any]:
    return {"name": name, "columns": [{"name": col, "strategy": "hash"}]}


def _rel(parent: str, child: str, *, col: str = "patient_id", namespace: str | None = None):
    rel: dict[str, Any] = {
        "parent": {"table": parent, "columns": [col]},
        "children": [{"table": child, "columns": [col]}],
        "orphan_policy": "preserve",
    }
    if namespace is not None:
        rel["namespace"] = namespace
    return rel


def _gen_config(relationships: list[dict[str, Any]] | None) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "version": 2,
        "global_settings": {"seed": 7},
        "sources": {},
        "tables": [
            _gen_table("patients", 20, [{"name": "patient_id", "type": "sequence", "start": 1}]),
            _gen_table(
                "visits",
                40,
                [
                    {
                        "name": "patient_id",
                        "type": "reference",
                        "reference_table": "patients",
                        "reference_column": "patient_id",
                    }
                ],
            ),
        ],
    }
    cfg["targets"] = {
        t["name"]: {"type": "file", "format": "csv", "path": f"./{t['name']}.csv"}
        for t in cfg["tables"]
    }
    if relationships is not None:
        cfg["relationships"] = relationships
    return cfg


def _profile(config: dict[str, Any]) -> Profile:
    rels = tuple(
        Relationship(
            parent_table=r["parent"]["table"],
            parent_columns=tuple(r["parent"]["columns"]),
            child_table=c["table"],
            child_columns=tuple(c["columns"]),
            namespace=r.get("namespace"),
        )
        for r in config.get("relationships", [])
        for c in r["children"]
    )
    return Profile(
        schema_version=1,
        tables=(),
        relationships=rels,
        profiled_at=datetime.now(timezone.utc),
        decoy_engine_version=ENGINE,
    )


def _normalized(config: dict[str, Any]) -> dict[str, Any]:
    return PipelineConfig.model_validate(copy.deepcopy(config)).model_dump()


def _registry(config: dict[str, Any]):
    return build_namespace_registry(config, _profile(config))


def test_at_e1_1_compile_plan_accepts_a_generate_only_edge() -> None:
    config = _gen_config([_rel("patients", "visits")])
    plan = compile_plan(
        _normalized(config), _profile(config), decoy_engine_version=ENGINE, sources=NO_SOURCES
    )
    assert len(plan.relationships) == 1


def test_at_e1_2_run_writes_the_same_bytes_as_without_the_block_on_full_frame() -> None:
    with_block = run_pipeline(
        _normalized(_gen_config([_rel("patients", "visits")])), None, engine_version=ENGINE
    )
    without = run_pipeline(_normalized(_gen_config(None)), None, engine_version=ENGINE)
    for name in ("patients", "visits"):
        pd.testing.assert_frame_equal(
            with_block.outputs[name].to_pandas(), without.outputs[name].to_pandas()
        )
    summary = route_summary(with_block.quality_metrics)
    assert summary.route == "full_frame"
    assert summary.route not in {"chunked", "shadow_generation"}


MIXED_PARENT_MASK = {
    "mask_only": lambda: _mask_config("patients", "visits", _mask_table, _mask_table),
    "mask_parent_gen_child": lambda: _mask_config("patients", "visits", _mask_table, None),
    "gen_parent_mask_child": lambda: _mask_config("patients", "visits", None, _mask_table),
}


def _mask_config(parent: str, child: str, parent_mask: Any, child_mask: Any) -> dict[str, Any]:
    gen_cols = [{"name": "patient_id", "type": "sequence", "start": 1}]
    tables = [
        parent_mask(parent, "patient_id") if parent_mask else _gen_table(parent, 5, gen_cols),
        child_mask(child, "patient_id") if child_mask else _gen_table(child, 5, gen_cols),
    ]
    return {
        "tables": tables,
        "relationships": [_rel(parent, child)],
    }


@pytest.mark.parametrize("case", sorted(MIXED_PARENT_MASK))
def test_at_e1_3_mask_and_mixed_edges_still_need_a_namespace(case: str) -> None:
    gen = _gen_config([_rel("patients", "visits")])
    # Same process, right after a generate-only edge: the exemption must not be cached.
    with contextlib.suppress(NamespaceConfigError):
        _registry(gen).for_relationship(_profile(gen).relationships[0])
    config = MIXED_PARENT_MASK[case]()
    registry = _registry(config)
    rel = _profile(config).relationships[0]
    with pytest.raises(NamespaceConfigError) as err:
        registry.for_relationship(rel)
    assert err.value.code == "namespace_missing"


def test_at_e1_3_an_edge_to_a_table_not_in_tables_is_still_refused() -> None:
    config = _gen_config([_rel("patients", "ghost")])
    registry = _registry(config)
    with pytest.raises(NamespaceConfigError) as err:
        registry.for_relationship(_profile(config).relationships[0])
    assert err.value.code == "namespace_missing"


def test_at_e1_4_capacity_estimate_accepts_the_config_on_the_full_frame_route(
    tmp_path: Path,
) -> None:
    config = _normalized(_gen_config([_rel("patients", "visits")]))
    estimate = estimate_job_capacity(config, tmp_path)
    assert estimate.route != "out_of_core"
    run = run_pipeline(config, None, engine_version=ENGINE)
    assert route_summary(run.quality_metrics).route == "full_frame"


def test_at_e1_5_derived_name_is_private_and_keyed_by_parent_key() -> None:
    config = _gen_config([_rel("patients", "visits")])
    registry = _registry(config)
    rel = _profile(config).relationships[0]
    derived = registry.for_relationship(rel)
    assert derived not in registry.declared()
    assert registry.for_column("patients", ("patient_id",)) is None
    assert registry.for_column("visits", ("patient_id",)) is None
    plan = compile_plan(
        _normalized(config), _profile(config), decoy_engine_version=ENGINE, sources=NO_SOURCES
    )
    assert derived not in {b.namespace for b in plan.namespaces}
    assert derived not in repr(plan)

    # Fan-out: two child edges to one parent key share a name; another parent key differs.
    other = Relationship(
        parent_table="patients",
        parent_columns=("region",),
        child_table="visits",
        child_columns=("region",),
        namespace=None,
    )
    sibling = Relationship(
        parent_table="patients",
        parent_columns=("patient_id",),
        child_table="visits",
        child_columns=("patient_id",),
        namespace=None,
    )
    assert registry.for_relationship(sibling) == derived
    assert registry.for_relationship(other) != derived


def test_at_e1_5_a_user_namespace_with_the_derived_text_masks_the_same_bytes(
    tmp_path: Path,
) -> None:
    gen = _gen_config([_rel("patients", "visits")])
    derived = _registry(gen).for_relationship(_profile(gen).relationships[0])
    frames = {
        "parents": pd.DataFrame({"patient_id": [f"p{i}" for i in range(6)]}),
        "kids": pd.DataFrame({"patient_id": [f"p{i % 6}" for i in range(12)]}),
    }
    sources: dict[str, Any] = {}
    for name, frame in frames.items():
        path = tmp_path / f"{name}.csv"
        frame.to_csv(path, index=False)
        sources[name] = {"type": "file", "format": "csv", "has_header": True, "path": str(path)}
    tables = {n: pa.Table.from_pandas(f, preserve_index=False) for n, f in frames.items()}

    def config(extra_gen_edge: bool) -> dict[str, Any]:
        cfg: dict[str, Any] = {
            "version": 2,
            "global_settings": {"seed": 3},
            "sources": sources,
            "tables": [_mask_table("parents", "patient_id"), _mask_table("kids", "patient_id")],
            "relationships": [_rel("parents", "kids", namespace=derived)],
        }
        for t in cfg["tables"]:
            t["columns"][0]["namespace"] = derived
        if extra_gen_edge:
            cfg["tables"] += _gen_config(None)["tables"]
            cfg["relationships"].append(_rel("patients", "visits"))
        cfg["targets"] = {
            t["name"]: {"type": "file", "format": "csv", "path": str(tmp_path / f"{t['name']}_o")}
            for t in cfg["tables"]
        }
        return cfg

    def masked(extra_gen_edge: bool) -> dict[str, Any]:
        result = run_pipeline(
            _normalized(config(extra_gen_edge)), sources=tables, engine_version=ENGINE
        )
        return {n: result.outputs[n].to_pylist() for n in ("parents", "kids")}

    assert masked(False) == masked(True)
