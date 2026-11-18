"""F07 E4a: a nested rule's `references` at run time.

A rule that references a parent column masks its leaf under the parent's identity, so equal source
keys give equal masked keys. The key kind is bound at compile; a leaf of another kind fails the row
closed, so `42` and `"42"` never hash to different tokens.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pandas as pd
import pytest

from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._strategies._hash import HashStrategyHandler
from decoy_engine.execution._strategies.nested import NestedStrategyHandler
from decoy_engine.execution.native._capabilities import capabilities_for
from decoy_engine.generation.pool._cache import PoolCache
from decoy_engine.relationships._graph import RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceRegistry
from tests.unit.execution._nested_strategy_support import _seed

JOB = (0x0123456789).to_bytes(8, "big")
MISMATCH = "nested_reference_leaf_type_mismatch"


def _ctx() -> StrategyContext:
    return StrategyContext(
        registry=None,  # type: ignore[arg-type]
        pool_cache=PoolCache(),
        relationship_graph=RelationshipGraph(edges=(), ordering=()),
        namespace_registry=NamespaceRegistry(bindings=()),
        job_seed=JOB,
        current_table="events",
    )


def _rule(kind: str | None = "integer", target: str = "$.customer_id") -> dict[str, Any]:
    references: dict[str, Any] = {"table": "customers", "column": "id"}
    if kind is not None:
        references["key_kind"] = kind
    return {
        "target": target,
        "strategy": "hash",
        "namespace": "customer",
        "references": references,
    }


def _run(cells: list[Any], rule: dict[str, Any]) -> tuple[pd.DataFrame, list, StrategyContext]:
    ctx = _ctx()
    seed = _seed({"rules": [rule]}, "events_payload")
    out, warnings = NestedStrategyHandler().run(
        pd.DataFrame({"payload": cells}), "payload", seed, ctx
    )
    return out, warnings, ctx


def _parent_hash(values: list[Any]) -> list[Any]:
    seed = dataclasses.replace(_seed({}, "customer"), strategy="hash", provider_config=())
    out, _ = HashStrategyHandler().run(pd.DataFrame({"id": values}), "id", seed, _ctx())
    return out["id"].tolist()


def _leaves(out: pd.DataFrame, path: str = "customer_id") -> list[Any]:
    return [json.loads(c).get(path) for c in out["payload"]]


def test_equal_source_keys_give_equal_masked_keys() -> None:
    keys = [3, 1, 3, 2]
    cells = [json.dumps({"customer_id": k, "note": "x"}) for k in keys]
    out, warnings, ctx = _run(cells, _rule())
    assert warnings == [] and ctx.row_errors == []
    assert _leaves(out) == _parent_hash(keys)
    # The join on masked values returns every source match.
    parent = dict(zip(keys, _parent_hash(keys), strict=True))
    assert [parent[k] for k in keys] == _leaves(out)


def test_a_string_key_matches_a_string_parent() -> None:
    cells = [json.dumps({"customer_id": k}) for k in ("c-1", "c-2", "c-1")]
    out, _, _ = _run(cells, _rule("string"))
    assert _leaves(out) == _parent_hash(["c-1", "c-2", "c-1"])


def test_a_null_leaf_stays_null_and_an_integer_beside_it_keeps_the_parent_token() -> None:
    cells = [
        json.dumps({"customer_id": 1}),
        json.dumps({"customer_id": None}),
        json.dumps({"customer_id": 3}),
    ]
    out, warnings, ctx = _run(cells, _rule())
    assert warnings == [] and ctx.row_errors == []
    one, none, three = _leaves(out)
    assert none is None
    assert [one, three] == _parent_hash([1, 3])


def test_the_rule_namespace_is_the_identity_not_the_column_namespace() -> None:
    cells = [json.dumps({"customer_id": 1})]
    out, _, _ = _run(cells, _rule())
    wrong = dataclasses.replace(_seed({}, "events_payload"), strategy="hash", provider_config=())
    flat, _ = HashStrategyHandler().run(pd.DataFrame({"id": [1]}), "id", wrong, _ctx())
    assert _leaves(out) != flat["id"].tolist()


@pytest.mark.parametrize(
    ("kind", "leaf"),
    [
        ("integer", "42"),
        ("integer", {"a": 1}),
        ("integer", [1]),
        ("integer", True),
        ("integer", 4.5),
        ("string", 42),
        ("string", {"a": 1}),
    ],
)
def test_a_leaf_of_another_kind_fails_the_row_closed(kind: str, leaf: Any) -> None:
    good = json.dumps({"customer_id": 1 if kind == "integer" else "c-1"})
    bad = json.dumps({"customer_id": leaf})
    out, warnings, ctx = _run([good, bad], _rule(kind))
    assert [(e.row_index, e.column) for e in ctx.row_errors] == [(1, "payload")]
    assert [(w.code, w.detail) for w in warnings] == [(MISMATCH, {"row_pos": "1"})]
    assert out["payload"].iloc[1] == bad, "the faulty cell keeps its input and the row is failed"
    assert str(leaf) not in ctx.row_errors[0].reason


def test_the_mismatch_code_is_in_the_nested_warning_registries() -> None:
    from decoy_engine.execution._mixed_admission import CHUNK_VARIANT_WARNING_CODES

    assert MISMATCH in capabilities_for("nested").warning_codes
    assert MISMATCH in CHUNK_VARIANT_WARNING_CODES


def test_references_without_a_bound_key_kind_fail_the_column_closed() -> None:
    with pytest.raises(StrategyError) as exc:
        _run([json.dumps({"customer_id": 1})], _rule(None))
    assert exc.value.code == "nested_reference_requires_profile"


def test_references_do_not_change_the_child_seed() -> None:
    handler = NestedStrategyHandler()
    plain = _rule()
    del plain["references"]
    child_seeds = []
    for rule in (_rule(), plain):
        seed = _seed({"rules": [rule]}, "events_payload")
        _, child = handler._resolve_child(seed)
        child_seeds.append(child)
    assert child_seeds[0] == child_seeds[1]


def _pipeline_config(tmp_path: Any, *, reference: bool) -> dict[str, Any]:
    from decoy_engine.config import PipelineConfig

    rule = _rule(None)
    if not reference:
        del rule["references"]
    tables = [
        {
            "name": "customers",
            "columns": [
                {"name": "id", "strategy": "hash", "namespace": "customer"},
                {"name": "name", "strategy": "redact"},
            ],
        },
        {
            "name": "events",
            "columns": [
                {"name": "event_id", "strategy": "passthrough"},
                {
                    "name": "payload",
                    "strategy": "nested",
                    "namespace": "events_payload",
                    "provider_config": {"rules": [rule]},
                },
            ],
        },
    ]
    sources = {
        t["name"]: {
            "type": "file",
            "format": "csv",
            "has_header": True,
            "path": str(tmp_path / f"{t['name']}.csv"),
        }
        for t in tables
    }
    targets = {
        t["name"]: {"type": "file", "format": "csv", "path": str(tmp_path / f"{t['name']}_o.csv")}
        for t in tables
    }
    cfg = {
        "version": 2,
        "global_settings": {"seed": 7},
        "sources": sources,
        "tables": tables,
        "targets": targets,
    }
    return PipelineConfig.model_validate(cfg).model_dump()


def _sources() -> dict[str, Any]:
    import pyarrow as pa

    ids = [1, 2, 3, 4]
    return {
        "customers": pa.table({"id": pa.array(ids, pa.int64()), "name": ["a", "b", "c", "d"]}),
        "events": pa.table(
            {
                "event_id": pa.array([10, 11, 12, 13, 14], pa.int64()),
                "payload": [json.dumps({"customer_id": i, "k": "v"}) for i in (1, 2, 2, 4, 1)],
            }
        ),
    }


def test_a_reference_leaves_relationships_and_non_nested_output_unchanged(tmp_path: Any) -> None:
    from decoy_engine import run_pipeline

    results: dict[tuple[bool, str], Any] = {}
    for reference in (True, False):
        cfg = _pipeline_config(tmp_path, reference=reference)
        for mode in ("full_frame", "sequential"):
            results[(reference, mode)] = run_pipeline(
                cfg, sources=_sources(), engine_version="e4a-test", execution_mode=mode
            )
    for (reference, mode), result in results.items():
        base = results[(False, mode)]
        assert result.plan.relationships == base.plan.relationships
        assert result.outputs["customers"].equals(base.outputs["customers"])
        assert (
            result.outputs["events"].column("event_id").to_pylist()
            == base.outputs["events"].column("event_id").to_pylist()
        )
        if reference:
            parent = dict(
                zip(
                    _sources()["customers"].column("id").to_pylist(),
                    result.outputs["customers"].column("id").to_pylist(),
                    strict=True,
                )
            )
            leaves = [
                json.loads(c)["customer_id"]
                for c in result.outputs["events"].column("payload").to_pylist()
            ]
            assert leaves == [parent[i] for i in (1, 2, 2, 4, 1)]
    for reference in (True, False):
        full, seq = results[(reference, "full_frame")], results[(reference, "sequential")]
        assert full.outputs["events"].equals(seq.outputs["events"])
