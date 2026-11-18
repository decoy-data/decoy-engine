"""F07 E4a: plan checks for a nested rule's `references`, through both compile entry points.

The static checks run in `run_config_only_checks` and `compile_plan`; the parent's profiled dtype
fixes the key kind, which only `compile_plan` binds.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

import pytest

from decoy_engine.plan import PlanCompileError, compile_plan, run_config_only_checks
from decoy_engine.profile import ColumnProfile, Profile, TableProfile

PATH = "tables.events.columns.payload.provider_config.rules[0]"


def _col(name: str, dtype: str) -> ColumnProfile:
    return ColumnProfile(
        name=name,
        dtype=dtype,
        row_count=10,
        null_count=0,
        distinct_count=10,
        sampled=False,
        is_candidate_key_sampled=False,
        declared_pk=False,
        is_fk=False,
        fk_target=None,
        pii_class=None,
    )


def _profile(parent_dtype: str = "int64") -> Profile:
    return Profile(
        schema_version=1,
        tables=(
            TableProfile(
                name="customers",
                row_count=10,
                columns=(_col("id", parent_dtype), _col("name", "object")),
            ),
            TableProfile(name="events", row_count=10, columns=(_col("payload", "object"),)),
        ),
        relationships=(),
        profiled_at=datetime(2026, 11, 18),
        decoy_engine_version="0.1.0",
    )


def _config(parent: dict[str, Any] | None = None, **rule: Any) -> dict[str, Any]:
    parent_col = {"name": "id", "strategy": "hash", "namespace": "customer", **(parent or {})}
    payload_rule = {
        "target": "$.customer_id",
        "strategy": "hash",
        "namespace": "customer",
        "references": {"table": "customers", "column": "id"},
        **rule,
    }
    return {
        "tables": [
            {"name": "customers", "columns": [parent_col]},
            {
                "name": "events",
                "columns": [
                    {
                        "name": "payload",
                        "strategy": "nested",
                        "namespace": "events_payload",
                        "provider_config": {"rules": [payload_rule]},
                    }
                ],
            },
        ]
    }


def _refs(**changes: Any) -> dict[str, Any]:
    return {"references": {"table": "customers", "column": "id", **changes}}


STATIC: list[tuple[str, dict[str, Any], dict[str, Any], str]] = [
    ("unknown table", {}, _refs(table="nope"), "nested_reference_parent_unknown"),
    ("unknown column", {}, _refs(column="nope"), "nested_reference_parent_unknown"),
    ("not a mapping", {}, {"references": "customers.id"}, "nested_reference_parent_unknown"),
    ("fpe", {"strategy": "fpe"}, {}, "nested_reference_strategy_not_join_safe"),
    ("redact", {"strategy": "redact"}, {}, "nested_reference_strategy_not_join_safe"),
    ("strategy", {}, {"strategy": "tokenize"}, "nested_reference_strategy_mismatch"),
    (
        "config",
        {},
        {"strategy_config": {"algorithm": "sha256"}},
        "nested_reference_strategy_mismatch",
    ),
    ("namespace", {}, {"namespace": "events_payload"}, "nested_reference_namespace_mismatch"),
    ("gated parent", {"when": "name == 'x'"}, {}, "nested_reference_parent_conditional"),
    ("wildcard", {}, {"target": "$.items[*].id"}, "nested_reference_path_not_singular"),
    ("descent", {}, {"target": "$..id"}, "nested_reference_path_not_singular"),
    ("user key kind", {}, _refs(key_kind="integer"), "nested_reference_key_kind_reserved"),
]


@pytest.mark.parametrize(
    ("parent", "rule", "code"),
    [pytest.param(p, r, c, id=i) for i, p, r, c in STATIC],
)
def test_static_refusals_at_both_entry_points(
    parent: dict[str, Any], rule: dict[str, Any], code: str
) -> None:
    config = _config(parent, **rule)
    for call in (
        lambda: run_config_only_checks(config),
        lambda: compile_plan(config, _profile(), decoy_engine_version="0.1.0"),
    ):
        with pytest.raises(PlanCompileError) as exc:
            call()
        assert exc.value.code == code
        assert exc.value.path.startswith(PATH)


def test_the_error_text_never_holds_a_config_value() -> None:
    config = _config(_refs(table="SECRET-TABLE-9"))
    with pytest.raises(PlanCompileError) as exc:
        run_config_only_checks(config)
    assert "SECRET-TABLE-9" not in str(exc.value)


def test_a_float_parent_is_refused_at_compile_only() -> None:
    config = _config()
    run_config_only_checks(config)
    with pytest.raises(PlanCompileError) as exc:
        compile_plan(config, _profile("float64"), decoy_engine_version="0.1.0")
    assert exc.value.code == "nested_reference_parent_type_unsupported"
    assert exc.value.path.startswith(PATH)


def test_tokenize_over_an_integer_parent_is_refused_at_compile_only() -> None:
    config = _config({"strategy": "tokenize"}, strategy="tokenize")
    run_config_only_checks(config)
    with pytest.raises(PlanCompileError) as exc:
        compile_plan(config, _profile("int64"), decoy_engine_version="0.1.0")
    assert exc.value.code == "nested_reference_parent_type_unsupported"
    compile_plan(config, _profile("object"), decoy_engine_version="0.1.0")


def test_no_profile_refuses_a_reference() -> None:
    config = _config()
    run_config_only_checks(config)
    with pytest.raises(PlanCompileError) as exc:
        compile_plan(config, _profile(), decoy_engine_version="0.1.0", no_profile=True)
    assert exc.value.code == "nested_reference_requires_profile"
    assert exc.value.path.startswith(PATH)


def _payload_config(plan: Any) -> dict[str, Any]:
    (table,) = [t for name, t in plan.seed_envelope.per_table if name == "events"]
    (seed,) = [s for name, s in table.per_column if name == "payload"]
    return dict(seed.provider_config)


@pytest.mark.parametrize(("dtype", "kind"), [("int64", "integer"), ("object", "string")])
def test_compile_binds_the_key_kind_outside_the_child_config(dtype: str, kind: str) -> None:
    config = _config()
    before = copy.deepcopy(config)
    plan = compile_plan(config, _profile(dtype), decoy_engine_version="0.1.0")
    (rule,) = _payload_config(plan)["rules"]
    assert rule["references"] == {"table": "customers", "column": "id", "key_kind": kind}
    assert "key_kind" not in str(rule["strategy_config"])
    assert config == before, "compile_plan must not edit the caller's config"
    plain = _config()
    del plain["tables"][1]["columns"][0]["provider_config"]["rules"][0]["references"]
    (plain_rule,) = _payload_config(
        compile_plan(plain, _profile(dtype), decoy_engine_version="0.1.0")
    )["rules"]
    assert rule["strategy_config"] == plain_rule["strategy_config"]
