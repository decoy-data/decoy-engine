"""Intended-column marker on the fidelity policy (DI-CLOSE E2, plan item 3).

A strategy whose class in the distribution-behavior table replaces values by design (hash, faker,
redact, ...) has no default value-identity minimum, so a correct mask does not fail `fail` mode.
The result lists those columns, and joints that name one, as intended.
"""

from __future__ import annotations

import copy

import pytest

from decoy_engine.contracts import distribution_behavior as table
from decoy_engine.quality.policy import apply_quality_policy

_FAIL = {"mode": "fail"}


def _col(name: str, sim: float | None, comparable: bool = True) -> dict:
    return {"column": name, "similarity": sim, "method": "tvd", "comparable": comparable}


def _joint(a: str, b: str, sim: float | None, comparable: bool = True) -> dict:
    return {"columns": [a, b], "similarity": sim, "method": "tvd", "comparable": comparable}


def _report(columns: list[dict], joints: list[dict] | None = None, pairwise: float | None = 0.5):
    return {
        "schema_version": "quality-report/v1",
        "diagnostic": {"passed": True, "checks": []},
        "marginal": {"score": 0.5, "columns": columns},
        "pairwise": {"score": pairwise, "joints": joints or []},
        "overall_score": 0.5,
        "grade": "C",
    }


_HASH_FAKER = {"patient_id": "hash", "full_name": "faker"}


def _hash_faker_report() -> dict:
    return _report([_col("patient_id", 0.0), _col("full_name", 0.0)])


def _pw(minimum: float) -> dict:
    return {"mode": "fail", "thresholds": {"pairwise": {"min": minimum}}}


def test_at_e2_1_hash_and_faker_at_zero_are_intended_not_violations() -> None:
    out = apply_quality_policy(_hash_faker_report(), _FAIL, strategy_map=_HASH_FAKER)
    assert [v for v in out["violations"] if v["check"] == "column"] == []
    assert out["verdict"] == "pass"
    assert out["intended_columns"] == ["full_name", "patient_id"]


def test_at_e2_2_shape_keeping_strategies_still_violate() -> None:
    out = apply_quality_policy(
        _report([_col("a", 0.5), _col("b", 0.2), _col("c", 0.2)]),
        _FAIL,
        strategy_map={"a": "shuffle", "b": "bucketize", "c": "date_shift"},
    )
    assert sorted(v["column"] for v in out["violations"] if v["check"] == "column") == [
        "a",
        "b",
        "c",
    ]
    assert out["intended_columns"] == []


def test_at_e2_3a_non_comparable_intended_column_is_still_listed() -> None:
    out = apply_quality_policy(
        _report([_col("patient_id", None, comparable=False)]),
        _FAIL,
        strategy_map={"patient_id": "hash"},
    )
    assert out["intended_columns"] == ["patient_id"]


def test_at_e2_3b_joint_naming_intended_column_is_intended_and_skips_minimum() -> None:
    report = _report(
        [_col("patient_id", 0.0), _col("diagnosis", 0.9)],
        [_joint("diagnosis", "patient_id", 0.0)],
        pairwise=0.0,
    )
    out = apply_quality_policy(report, _pw(0.8), strategy_map={"patient_id": "hash"})
    assert out["intended_joints"] == [["diagnosis", "patient_id"]]
    assert [v for v in out["violations"] if v["check"] == "pairwise"] == []


def test_at_e2_3c_mixed_joints_recompute_from_non_intended() -> None:
    report = _report(
        [_col("patient_id", 0.0)],
        [_joint("patient_id", "a", 0.0), _joint("b", "c", 0.9)],
        pairwise=0.45,
    )
    out = apply_quality_policy(report, _pw(0.8), strategy_map={"patient_id": "hash"})
    assert out["violations"] == []
    assert "pairwise_skipped" not in out


def test_at_e2_3d_no_intended_joint_compares_the_report_aggregate_as_before() -> None:
    # The aggregate (0.95) differs from what the joint records would recompute (0.4).
    report = _report([], [_joint("a", "b", 0.4)], pairwise=0.95)
    out = apply_quality_policy(report, _pw(0.9), strategy_map={})
    assert out["violations"] == []
    low = _report([], [_joint("a", "b", 0.99)], pairwise=0.1)
    out = apply_quality_policy(low, _pw(0.9), strategy_map={})
    assert [v["actual"] for v in out["violations"]] == [0.1]


def test_at_e2_3e_non_comparable_remainder_gives_a_violation() -> None:
    report = _report(
        [_col("patient_id", 0.0)],
        [_joint("patient_id", "a", 0.0), _joint("b", "c", None, comparable=False)],
        pairwise=0.0,
    )
    out = apply_quality_policy(report, _pw(0.8), strategy_map={"patient_id": "hash"})
    pairwise = [v for v in out["violations"] if v["check"] == "pairwise"]
    assert len(pairwise) == 1
    assert pairwise[0]["actual"] is None


def test_at_e2_3f_all_intended_joints_skip_and_say_so_only_with_a_minimum() -> None:
    report = _report(
        [_col("patient_id", 0.0)],
        [_joint("patient_id", "a", 0.0), _joint("patient_id", "b", 0.0)],
        pairwise=0.0,
    )
    out = apply_quality_policy(report, _pw(0.8), strategy_map={"patient_id": "hash"})
    assert out["violations"] == []
    assert out["pairwise_skipped"] == "all_joints_intended"
    no_min = apply_quality_policy(report, _FAIL, strategy_map={"patient_id": "hash"})
    assert "pairwise_skipped" not in no_min


def test_at_e2_3g_zero_joints_is_not_an_all_intended_skip() -> None:
    report = _report([_col("patient_id", 0.0)], [], pairwise=None)
    out = apply_quality_policy(report, _pw(0.8), strategy_map={"patient_id": "hash"})
    assert [v["check"] for v in out["violations"]] == ["pairwise"]
    assert "pairwise_skipped" not in out


def test_at_e2_3_report_dict_is_not_mutated() -> None:
    report = _report(
        [_col("patient_id", 0.0)],
        [_joint("patient_id", "a", 0.0), _joint("b", "c", 0.9)],
    )
    before = copy.deepcopy(report)
    apply_quality_policy(report, _pw(0.8), strategy_map={"patient_id": "hash"})
    assert report == before


def test_at_e2_4_shape_check_for_hash_still_applies_its_minimum() -> None:
    report = _report([_col("patient_id", 0.0)])
    report["shape_fidelity"] = {
        "marginal": {
            "columns": [
                {"column": "patient_id", "shape_similarity": 0.5, "comparable": True},
            ]
        }
    }
    out = apply_quality_policy(report, _FAIL, strategy_map={"patient_id": "hash"})
    shape = [v for v in out["violations"] if v["check"] == "shape_column"]
    assert [v["expected"] for v in shape] == [0.95]


@pytest.mark.parametrize(
    "config",
    [
        {"mode": "fail", "strategy_expectations": {"hash": 0.5}},
        {"mode": "fail", "thresholds": {"columns": [{"column": "patient_id", "min": 0.5}]}},
    ],
    ids=["strategy_override", "column_override"],
)
def test_at_e2_7_explicit_minimum_wins_over_the_intended_class(config: dict) -> None:
    out = apply_quality_policy(
        _report([_col("patient_id", 0.0)]), config, strategy_map={"patient_id": "hash"}
    )
    assert [v["column"] for v in out["violations"] if v["check"] == "column"] == ["patient_id"]
    assert out["intended_columns"] == []


def test_at_e2_8_aggregates_still_count_intended_columns() -> None:
    report = _hash_faker_report()
    before = copy.deepcopy(report)
    config = {"mode": "fail", "thresholds": {"overall": {"min": 0.9}}}
    out = apply_quality_policy(report, config, strategy_map=_HASH_FAKER)
    assert report == before
    assert report["marginal"]["score"] == 0.5
    assert report["overall_score"] == 0.5
    assert report["grade"] == "C"
    assert [v["check"] for v in out["violations"]] == ["overall"]


def test_at_e2_9_intended_set_is_derived_from_the_behavior_table() -> None:
    replacing = {"preserves_cardinality_only", "destroys_frequency", "collapses"}
    expected = {
        name
        for name in table.static_strategy_names()
        if name != "categorical" and table.distribution_behavior_for(name) in replacing
    }
    assert {"hash", "fpe", "tokenize", "group_key", "faker", "grouped_series", "redact"} <= expected
    assert "text_redact" in expected
    assert not expected & {"shuffle", "bucketize", "date_shift", "categorical", "passthrough"}
    reports = {
        name: apply_quality_policy(_report([_col("c", 0.0)]), _FAIL, strategy_map={"c": name})[
            "intended_columns"
        ]
        for name in table.static_strategy_names()
    }
    assert {n for n, cols in reports.items() if cols} == expected


def test_at_e2_9_a_new_replacing_strategy_is_intended_without_editing_policy(monkeypatch) -> None:
    import importlib

    from decoy_engine.quality import policy

    patched = {**table._STATIC_BEHAVIOR, "brand_new": "destroys_frequency"}
    monkeypatch.setattr(table, "_STATIC_BEHAVIOR", patched)
    reloaded = importlib.reload(policy)
    try:
        out = reloaded.apply_quality_policy(
            _report([_col("c", 0.0)]), _FAIL, strategy_map={"c": "brand_new"}
        )
        assert out["intended_columns"] == ["c"]
    finally:
        monkeypatch.undo()
        importlib.reload(policy)


def test_mean_comparable_similarity_formula() -> None:
    from decoy_engine.quality.fidelity import mean_comparable_similarity

    assert mean_comparable_similarity([]) is None
    assert mean_comparable_similarity([{"comparable": False, "similarity": None}]) is None
    records = [
        {"comparable": True, "similarity": 0.1},
        {"comparable": True, "similarity": 0.2},
        {"comparable": True, "similarity": 0.2},
        {"comparable": False, "similarity": 0.9},
    ]
    assert mean_comparable_similarity(records) == round(0.5 / 3, 6)


def test_at_e2_8_report_aggregate_counts_a_hashed_column() -> None:
    """The marginal mean in V1 includes the intended (hashed) column, so no frozen number moves."""
    import hashlib

    import pandas as pd

    from decoy_engine.quality.fidelity import compute_fidelity
    from decoy_engine.quality.snapshot import compute_distribution_snapshot

    ids = [f"p{i % 20}" for i in range(200)]
    source = pd.DataFrame({"patient_id": ids, "tier": ["a", "b"] * 100})
    masked = source.assign(
        patient_id=[hashlib.sha256(v.encode()).hexdigest()[:10] for v in ids],
    )
    result = compute_fidelity(
        compute_distribution_snapshot(source), compute_distribution_snapshot(masked)
    )
    by_col = {c["column"]: c["similarity"] for c in result["marginal"]["columns"]}
    assert by_col["patient_id"] < 0.05
    assert result["marginal"]["score"] == round(sum(by_col.values()) / len(by_col), 6)
    assert result["marginal"]["score"] < by_col["tier"]
