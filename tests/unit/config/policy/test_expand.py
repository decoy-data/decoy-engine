"""F16-T3, T4 and T5: roles, purity, conflicts, undecided, partial and unmatched."""

from __future__ import annotations

import copy

from decoy_engine.config._tables import ColumnConfig
from decoy_engine.config.policy import ColumnDecision, PrecedenceLevel
from tests.unit.config.policy._helpers import (
    codes,
    col,
    expand,
    raw_config,
    refusal,
    table,
)


def _rel(parent, children):
    return {
        "parent": {"table": parent[0], "columns": parent[1]},
        "children": [{"table": t, "columns": c} for t, c in children],
        "orphan_policy": "fail",
    }


def _decided(fields):
    return {(f.table, f.column): f.decision.strategy for f in fields}


def _roles_run(relationships, tables, role, *, strategy="hash"):
    policy = {
        "default": {"strategy": "redact"},
        "rules": [{"id": "keyed", "select": {"role": role}, "strategy": strategy}],
    }
    _, expansion = expand(raw_config(tables, relationships), policy)
    return {k for k, v in _decided(expansion.fields).items() if v == strategy}


# -- F16-T3 ------------------------------------------------------------------

PEOPLE = [table("p", col("id"), col("name")), table("o", col("id"), col("p_id"), col("note"))]


def test_single_column_roles():
    rels = [_rel(("p", ["id"]), [("o", ["p_id"])])]
    assert _roles_run(rels, PEOPLE, "parent_key") == {("p", "id")}
    assert _roles_run(rels, PEOPLE, "child_key") == {("o", "p_id")}
    assert _roles_run(rels, PEOPLE, ["parent_key", "child_key"]) == {("p", "id"), ("o", "p_id")}


def test_composite_roles_cover_every_member():
    tables = [
        table("p", col("a"), col("b"), col("x")),
        table("o", col("pa"), col("pb"), col("y")),
    ]
    rels = [_rel(("p", ["a", "b"]), [("o", ["pa", "pb"])])]
    assert _roles_run(rels, tables, "parent_key") == {("p", "a"), ("p", "b")}
    assert _roles_run(rels, tables, "child_key") == {("o", "pa"), ("o", "pb")}


def test_self_reference_gives_one_column_both_roles():
    tables = [table("emp", col("id"), col("manager_id"), col("name"))]
    rels = [_rel(("emp", ["id"]), [("emp", ["manager_id"])])]
    assert _roles_run(rels, tables, "parent_key") == {("emp", "id")}
    assert _roles_run(rels, tables, "child_key") == {("emp", "manager_id")}

    both = [_rel(("emp", ["id"]), [("emp", ["id"])])]
    assert _roles_run(both, tables, "parent_key") == {("emp", "id")}
    assert _roles_run(both, tables, "child_key") == {("emp", "id")}


def test_every_child_of_a_relationship_has_the_role():
    tables = [
        table("p", col("id")),
        table("a", col("p_id"), col("n")),
        table("b", col("p_id"), col("m")),
    ]
    rels = [_rel(("p", ["id"]), [("a", ["p_id"]), ("b", ["p_id"])])]
    assert _roles_run(rels, tables, "child_key") == {("a", "p_id"), ("b", "p_id")}


def test_a_column_in_two_relationships_keeps_both_roles():
    tables = [
        table("p", col("id")),
        table("q", col("id"), col("p_id")),
        table("r", col("q_id")),
    ]
    rels = [_rel(("p", ["id"]), [("q", ["p_id"])]), _rel(("q", ["id"]), [("r", ["q_id"])])]
    assert _roles_run(rels, tables, "parent_key") == {("p", "id"), ("q", "id")}
    assert _roles_run(rels, tables, "child_key") == {("q", "p_id"), ("r", "q_id")}


def test_malformed_relationships_are_ignored():
    tables = [table("p", col("id"), col("n"))]
    raw = raw_config(tables, [None, {"parent": 3}, {"parent": {"table": "p"}, "children": "x"}])
    policy = {"default": {"strategy": "redact"}}
    assert len(expand(raw, policy)[1].fields) == 2


# -- F16-T4 ------------------------------------------------------------------


def _pure_raw():
    return raw_config(
        [table("t", col("a", classification="email"), col("b", strategy="hash", namespace="n"))],
        [_rel(("t", ["a"]), [("t", ["b"])])],
    )


def test_expansion_is_pure_and_repeatable():
    raw = _pure_raw()
    policy = {
        "rules": [
            {
                "id": "r",
                "select": {"classification": "email"},
                "strategy": "fpe",
                "provider_config": {"charset": "alnum"},
            }
        ]
    }
    before = copy.deepcopy(raw)
    first, expansion = expand(raw, policy)
    second, again = expand(raw, policy)
    assert raw == before
    assert first == second and expansion == again
    column = first["tables"][0]["columns"][0]
    assert column["strategy"] == "fpe" and column["provider_config"] == {"charset": "alnum"}
    assert set(ColumnDecision.model_fields) <= set(column)
    assert "strategy" not in raw["tables"][0]["columns"][0]


def test_output_shares_no_container_with_the_caller_or_the_policy():
    raw = _pure_raw()
    policy = {"default": {"strategy": "redact", "provider_config": {"k": [1]}}}
    out, _ = expand(raw, policy)
    assert out["tables"] is not raw["tables"]
    assert out["tables"][0] is not raw["tables"][0]
    assert out["tables"][0]["columns"][1] is not raw["tables"][0]["columns"][1]
    out["tables"][0]["columns"][0]["provider_config"]["k"].append(2)
    again, _ = expand(raw, policy)
    assert again["tables"][0]["columns"][0]["provider_config"] == {"k": [1]}


def test_a_config_without_tables_or_columns_passes_through():
    out, expansion = expand({"version": 2}, {})
    assert out == {"version": 2} and expansion.fields == ()
    out, expansion = expand({"tables": "nope"}, {})
    assert out == {"tables": "nope"} and expansion.fields == ()


# -- F16-T5 ------------------------------------------------------------------


def test_conflict_at_one_level_names_both_sources_and_the_field():
    raw = raw_config([table("t", col("c"))])
    policy = {
        "rules": [
            {"id": "one", "select": {"table": "t", "column": "c"}, "strategy": "hash"},
            {"id": "two", "select": {"table": "t", "column": "c"}, "strategy": "redact"},
        ]
    }
    exc = refusal(raw, policy)
    assert codes(exc) == ["policy_rule_conflict"]
    msg = exc.errors()[0]["msg"]
    assert "rule one" in msg and "rule two" in msg and "t.c" in msg
    assert exc.errors()[0]["loc"] == ("tables", 0, "columns", 0)
    assert exc.__cause__ is None and exc.__context__ is None


def test_rules_differing_only_in_a_non_strategy_key_conflict():
    raw = raw_config([table("t", col("c"))])
    base = {"select": {"table": "t"}, "strategy": "hash"}
    policy = {"rules": [{"id": "a", **base}, {"id": "b", **base, "namespace": "n"}]}
    assert codes(refusal(raw, policy)) == ["policy_rule_conflict"]


def test_equal_decisions_merge_after_normalizing_to_defaults():
    raw = raw_config([table("t", col("c"))])
    policy = {
        "rules": [
            {"id": "terse", "select": {"table": "t"}, "strategy": "hash", "namespace": "n"},
            {
                "id": "verbose",
                "select": {"table": "t"},
                "strategy": "hash",
                "namespace": "n",
                "provider": None,
                "provider_config": {},
                "deterministic": False,
                "allow_collisions": False,
            },
        ]
    }
    _, expansion = expand(raw, policy)
    (field,) = expansion.fields
    assert [s.id for s in field.sources] == ["terse", "verbose"]
    assert field.level is PrecedenceLevel.EXACT_OBJECT_OR_CLASSIFICATION


def test_column_strategy_against_a_different_level_1_rule_conflicts():
    raw = raw_config([table("t", col("c", strategy="hash"))])
    rule = {"id": "r", "select": {"table": "t", "column": "c"}, "strategy": "redact"}
    exc = refusal(raw, {"rules": [rule]})
    assert codes(exc) == ["policy_rule_conflict"]
    assert "column t.c" in exc.errors()[0]["msg"] and "rule r" in exc.errors()[0]["msg"]


def test_column_strategy_equal_to_a_level_1_rule_merges_and_a_pattern_rule_loses():
    raw = raw_config([table("t", col("c", strategy="hash"))])
    policy = {
        "rules": [
            {"id": "exact", "select": {"table": "t", "column": "c"}, "strategy": "hash"},
            {"id": "broad", "select": {"table": "t*"}, "strategy": "redact"},
        ]
    }
    (field,) = expand(raw, policy)[1].fields
    assert field.level is PrecedenceLevel.EXACT_FIELD
    assert [s.kind for s in field.sources] == ["rule", "column"]
    assert field.overridden == ("broad",)


def test_unmatched_rule_is_refused_naming_its_id():
    raw = raw_config([table("t", col("c", strategy="hash"))])
    policy = {"rules": [{"id": "ghost", "select": {"table": "nope"}, "strategy": "hash"}]}
    exc = refusal(raw, policy)
    assert codes(exc) == ["policy_selector_unmatched"]
    assert "ghost" in exc.errors()[0]["msg"]
    assert exc.errors()[0]["loc"] == ("policy", "rules", 0)


def test_undecided_field_is_refused_never_passed_through():
    raw = raw_config([table("t", col("c"), col("d", strategy="hash"))])
    exc = refusal(raw, {})
    assert codes(exc) == ["policy_field_undecided"]
    assert "t.c" in exc.errors()[0]["msg"]
    assert exc.errors()[0]["loc"] == ("tables", 0, "columns", 0)


def test_partial_column_is_refused():
    raw = raw_config([table("t", col("c", deterministic=True, classification="email"))])
    exc = refusal(raw, {"default": {"strategy": "redact"}})
    assert codes(exc) == ["policy_column_partial"]
    assert "t.c" in exc.errors()[0]["msg"] and "deterministic" in exc.errors()[0]["msg"]


def test_labels_and_declared_casting_keys_are_allowed_without_a_strategy():
    raw = raw_config(
        [
            table(
                "t",
                col(
                    "c", classification="email", tags=["a"], logical_type="date", parse_format=None
                ),
            )
        ]
    )
    out, _ = expand(raw, {"default": {"strategy": "redact"}})
    assert out["tables"][0]["columns"][0]["strategy"] == "redact"
    assert out["tables"][0]["columns"][0]["tags"] == ["a"]


def test_all_problems_come_in_one_error():
    raw = raw_config(
        [table("t", col("undecided"), col("part", provider="x"), col("ok", strategy="hash"))]
    )
    policy = {"rules": [{"id": "ghost", "select": {"column": "zzz"}, "strategy": "hash"}]}
    exc = refusal(raw, policy)
    assert sorted(codes(exc)) == [
        "policy_column_partial",
        "policy_field_undecided",
        "policy_selector_unmatched",
    ]


def test_unknown_strategy_in_a_rule_or_the_default():
    raw = raw_config([table("t", col("c", strategy="hash"))])
    policy = {
        "rules": [{"id": "r", "select": {"table": "t"}, "strategy": "bogus"}],
        "default": {"strategy": "also_bogus"},
    }
    exc = refusal(raw, policy)
    assert codes(exc) == ["policy_unknown_strategy", "policy_unknown_strategy"]
    assert [e["loc"] for e in exc.errors()] == [
        ("policy", "rules", 0, "strategy"),
        ("policy", "default", "strategy"),
    ]
    assert "bogus" not in str(exc.errors())


def test_unknown_column_classification_is_refused_with_its_location():
    raw = raw_config([table("t", col("c", strategy="hash", classification="not_a_detector"))])
    exc = refusal(raw, {})
    assert codes(exc) == ["policy_unknown_classification"]
    assert exc.errors()[0]["loc"] == ("tables", 0, "columns", 0, "classification")
    assert "not_a_detector" not in str(exc.errors())


def test_level_4_uses_the_classification_default():
    raw = raw_config([table("t", col("c", classification="email"), col("d"))])
    stub = {"email": ColumnDecision(strategy="fpe", namespace="mail")}
    exc = refusal(raw, {}, stub)
    assert codes(exc) == ["policy_field_undecided"] and "t.d" in exc.errors()[0]["msg"]
    out, expansion = expand(raw, {"default": {"strategy": "redact"}}, stub)
    assert out["tables"][0]["columns"][0]["namespace"] == "mail"
    assert [(f.column, f.level.label) for f in expansion.fields] == [
        ("c", "classification_default"),
        ("d", "global_default"),
    ]


def test_messages_carry_ids_not_config_values():
    raw = raw_config([table("t", col("c"))])
    policy = {
        "rules": [
            {
                "id": "one",
                "select": {"table": "t"},
                "strategy": "hash",
                "provider_config": {"k": "CANARY_ONE"},
            },
            {
                "id": "two",
                "select": {"table": "t"},
                "strategy": "redact",
                "provider_config": {"k": "CANARY_TWO"},
            },
        ]
    }
    text = str(refusal(raw, policy).errors())
    assert "CANARY" not in text


def test_column_decision_defaults_equal_column_config_defaults():
    for name in ColumnDecision.model_fields:
        if name == "strategy":
            continue
        want = ColumnConfig.model_fields[name].get_default(call_default_factory=True)
        got = ColumnDecision.model_fields[name].get_default(call_default_factory=True)
        assert got == want, name
