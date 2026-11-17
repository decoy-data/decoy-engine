"""F16-T6 and F16-T12: prohibitions and the policy-expansion/v1 explanation."""

from __future__ import annotations

import copy
import json
import re

import pytest
from pydantic import ValidationError

from decoy_engine import reasons
from decoy_engine.config.policy import (
    POLICY_EXPANSION_SCHEMA,
    ColumnDecision,
    PolicyConfig,
    expansion_to_dict,
)
from tests.unit.config.policy._helpers import (
    codes,
    col,
    expand,
    raw_config,
    refusal,
    table,
)

SSN = ColumnDecision(strategy="hash", deterministic=True)


def _raw():
    return raw_config(
        [
            table(
                "p",
                col("ssn", classification="ssn"),
                col("name"),
                col("note", strategy="passthrough"),
            )
        ]
    )


def _no_clear_ssn(**extra):
    return {
        "default": {"strategy": "redact"},
        "prohibit": [
            {"id": "no-passthrough", "select": {"table": "p"}, "forbid": ["passthrough"], **extra}
        ],
    }


# -- F16-T6 ------------------------------------------------------------------


def test_forbid_hits_an_explicit_level_1_passthrough():
    exc = refusal(_raw(), _no_clear_ssn())
    assert codes(exc) == ["policy_prohibited"]
    text = exc.errors()[0]["msg"]
    assert "no-passthrough" in text and "p.note" in text and "passthrough" in text
    assert exc.errors()[0]["loc"] == ("policy", "prohibit", 0)


def test_forbid_hits_a_decision_expanded_from_a_rule():
    policy = {
        "default": {"strategy": "redact"},
        "rules": [{"id": "clear", "select": {"column": "name"}, "strategy": "passthrough"}],
        "prohibit": [{"id": "no-clear", "select": {"column": "name"}, "forbid": ["passthrough"]}],
    }
    assert codes(refusal(_raw(), policy)) == ["policy_prohibited"]


def test_require_hits_an_expanded_decision():
    policy = {
        "default": {"strategy": "redact"},
        "prohibit": [{"id": "keyed", "select": {"column": "name"}, "require": ["hash", "fpe"]}],
    }
    exc = refusal(_raw(), policy)
    assert codes(exc) == ["policy_prohibited"]
    assert "p.name" in exc.errors()[0]["msg"] and "redact" in exc.errors()[0]["msg"]


def test_require_passes_when_the_strategy_is_listed():
    policy = {
        "default": {"strategy": "hash"},
        "prohibit": [{"id": "keyed", "select": {"column": "name"}, "require": ["hash"]}],
    }
    _, expansion = expand(_raw(), policy)
    assert [(m.id, m.matched) for m in expansion.prohibitions] == [("keyed", 1)]


def test_forbid_passes_when_no_selected_field_uses_the_strategy():
    policy = {
        "default": {"strategy": "redact"},
        "prohibit": [{"id": "p1", "select": {"column": "name"}, "forbid": ["passthrough"]}],
    }
    expand(_raw(), policy)


def test_a_zero_match_prohibition_is_reported_with_matched_0_and_no_error():
    policy = {
        "default": {"strategy": "redact"},
        "prohibit": [{"id": "none", "select": {"table": "nope"}, "forbid": ["redact"]}],
    }
    _, expansion = expand(_raw(), policy)
    assert [(m.id, m.matched) for m in expansion.prohibitions] == [("none", 0)]
    doc = expansion_to_dict(expansion)
    assert doc["prohibitions"] == [{"id": "none", "matched": 0}]


def test_every_violating_field_is_reported_in_one_error():
    policy = {
        "default": {"strategy": "redact"},
        "prohibit": [
            {"id": "a", "select": {"table": "p"}, "forbid": ["redact"]},
            {"id": "b", "select": {"column": "note"}, "require": ["hash"]},
        ],
    }
    exc = refusal(_raw(), policy)
    assert codes(exc) == ["policy_prohibited"] * 3


def test_prohibition_selects_by_classification_and_role():
    rels = [
        {
            "parent": {"table": "p", "columns": ["ssn"]},
            "children": [{"table": "o", "columns": ["p_ssn"]}],
            "orphan_policy": "fail",
        }
    ]
    raw = raw_config(
        [table("p", col("ssn", classification="ssn")), table("o", col("p_ssn"), col("x"))], rels
    )
    policy = {
        "default": {"strategy": "redact"},
        "prohibit": [
            {"id": "keys", "select": {"role": "child_key"}, "require": ["hash"]},
            {"id": "ssn", "select": {"classification": "ssn"}, "forbid": ["redact"]},
        ],
    }
    exc = refusal(raw, policy, level4=None)
    msgs = " ".join(e["msg"] for e in exc.errors())
    assert "o.p_ssn" in msgs and "p.ssn" in msgs and "o.x" not in msgs


def test_unknown_strategy_in_a_prohibition_is_refused():
    for mode in ("forbid", "require"):
        policy = {
            "default": {"strategy": "redact"},
            "prohibit": [{"id": "typo", "select": {"table": "p"}, mode: ["hsah"]}],
        }
        exc = refusal(_raw(), policy)
        assert codes(exc) == ["policy_unknown_strategy"]
        assert exc.errors()[0]["loc"] == ("policy", "prohibit", 0, mode)


def test_prohibited_code_is_registered_unreleased():
    spec = reasons.find("config", "policy_prohibited")
    assert spec is not None and spec.since == reasons.UNRELEASED
    assert not re.search(r"[{}%]", spec.summary)


# -- F16-T12 -----------------------------------------------------------------

CANARY = "CANARY_PC_8c1f"


def _canary_policy():
    return {
        "disguise": None,
        "rules": [
            {
                "id": "r1",
                "select": {"table": "p", "column": "name"},
                "strategy": "hash",
                "provider_config": {"k": CANARY},
                "why": f"why {CANARY}",
            }
        ],
        "default": {"strategy": "redact", "provider_config": {"k": CANARY}},
        "prohibit": [
            {
                "id": "no-redact",
                "select": {"table": "p"},
                "forbid": ["redact"],
                "why": f"why {CANARY}",
            }
        ],
    }


def test_canary_literals_never_reach_a_refusal():
    exc = refusal(_raw(), _canary_policy())
    assert "policy_prohibited" in codes(exc)
    assert CANARY not in str(exc.errors()) and CANARY not in str(exc)


def test_canary_literals_never_reach_the_explanation():
    policy = _canary_policy()
    policy["prohibit"] = []
    _, expansion = expand(_raw(), policy)
    assert CANARY not in json.dumps(expansion_to_dict(expansion))


def test_refusal_messages_for_every_policy_code_carry_no_canary():
    raw = raw_config([table("t", col("c", provider_config={"k": CANARY}, strategy="hash"))])
    policy = {
        "rules": [
            {
                "id": "a",
                "select": {"table": "t"},
                "strategy": "hash",
                "provider_config": {"k": CANARY},
            },
            {
                "id": "b",
                "select": {"table": "t"},
                "strategy": "redact",
                "provider_config": {"k": CANARY},
            },
            {"id": "z", "select": {"table": "zz"}, "strategy": "nope", "why": CANARY},
        ],
        "prohibit": [{"id": "q", "select": {"table": "t"}, "forbid": ["hash", "nope2"]}],
    }
    exc = refusal(raw, policy)
    assert CANARY not in str(exc.errors())


def _doc(raw=None, policy=None, level4=None):
    return expansion_to_dict(expand(raw or _raw(), policy or _prohibition_free(), level4)[1])


def _prohibition_free():
    return {"default": {"strategy": "redact"}}


def test_explanation_shape_and_tag():
    doc = _doc(level4={"ssn": SSN})
    assert doc["schema"] == POLICY_EXPANSION_SCHEMA == "policy-expansion/v1"
    assert list(doc) == ["schema", "disguise", "fingerprint", "fields", "rules", "prohibitions"]
    assert re.fullmatch(r"[0-9a-f]{64}", doc["fingerprint"])
    by = {(f["table"], f["column"]): f for f in doc["fields"]}
    ssn = by[("p", "ssn")]
    assert ssn["level"] == 4 and ssn["level_name"] == "classification_default"
    assert ssn["strategy"] == "hash" and ssn["deterministic"] is True
    assert ssn["source"]["kind"] == "disguise" and ssn["classification"] == "ssn"
    assert by[("p", "note")]["level"] == 1 and by[("p", "note")]["source"]["kind"] == "column"
    assert by[("p", "name")]["source"] == {"kind": "default", "id": "default"}
    assert "provider_config" not in ssn
    assert re.fullmatch(r"[0-9a-f]{64}", ssn["decision_digest"])


def test_overridden_lists_the_rules_that_lost():
    policy = {
        "default": {"strategy": "redact"},
        "rules": [
            {"id": "wide", "select": {"table": "p"}, "strategy": "hash"},
            {"id": "exact", "select": {"table": "p", "column": "name"}, "strategy": "fpe"},
        ],
    }
    by = {f["column"]: f for f in _doc(policy=policy)["fields"]}
    assert by["name"]["overridden"] == ["wide"] and by["name"]["strategy"] == "fpe"
    assert [(r["id"], r["level"], r["matched"]) for r in _doc(policy=policy)["rules"]] == [
        ("wide", 2, 3),
        ("exact", 1, 1),
    ]


def test_fingerprint_is_stable_across_runs_and_dict_orders():
    first = _doc()["fingerprint"]
    assert first == _doc()["fingerprint"]
    raw = _raw()
    raw["tables"][0]["columns"].reverse()
    assert _doc(raw)["fingerprint"] == first


def test_fingerprint_changes_with_a_decision_and_with_the_pin():
    base = _doc()["fingerprint"]
    changed = _doc(policy={"default": {"strategy": "hash"}})["fingerprint"]
    pinned = _doc(
        policy={
            "disguise": {"id": "hipaa", "version": "2026-11-20"},
            "default": {"strategy": "redact"},
        }
    )["fingerprint"]
    assert len({base, changed, pinned}) == 3


def test_round_trip_reads_level_1_with_the_same_fingerprint():
    raw, policy = _raw(), _prohibition_free()
    out, expansion = expand(raw, policy, {"ssn": SSN})
    again = expand(out, policy, {"ssn": SSN})[1]
    assert {f.level for f in again.fields} == {1}
    assert expansion_to_dict(again)["fingerprint"] == expansion_to_dict(expansion)["fingerprint"]


def test_explanation_is_json_safe_and_unchanged_by_the_caller():
    raw = _raw()
    before = copy.deepcopy(raw)
    doc = _doc(raw)
    json.dumps(doc)
    assert raw == before


def test_policy_model_still_rejects_a_bad_prohibition():
    with pytest.raises(ValidationError):
        PolicyConfig.model_validate({"prohibit": [{"id": "x", "select": {"table": "t"}}]})
