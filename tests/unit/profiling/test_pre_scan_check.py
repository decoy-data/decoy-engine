"""The pre-scan coverage verdict (PRE-SCAN-RUN E2-T1 to E2-T10)."""

from __future__ import annotations

import pickle
import warnings
from typing import Any

import pytest

from decoy_engine import reasons
from decoy_engine.profiling import (
    PreScanBlockedError,
    PreScanFailedError,
    PreScanVerdict,
    PreScanWarning,
    evaluate_pre_scan,
)
from decoy_engine.profiling.pre_scan_check import PreScanFinding
from decoy_engine.reason_adapter import reason_from_exception
from decoy_engine.run_result import Check
from decoy_engine.support import StrategyKind

CANARY = "CANARY-pre-scan-8c41"


def _field(
    name: str, *, pii: bool = False, hits: tuple[tuple[str, str | None], ...] = ()
) -> dict[str, Any]:
    return {
        "name": name,
        "dtype": "object",
        "null_count": 0,
        "null_rate": 0.0,
        "distinct_count": 3,
        "pii_score": 0.9 if pii else 0.0,
        "pii_candidate": pii,
        "detector_hits": [],
        "leading_zero_count": None,
        "model_hits": [
            {
                "source": source,
                "detector_id": f"{source}.x",
                "model": {"id": "m", "version": "1"},
                "band": band,
                "rate_bucket": None,
            }
            for source, band in hits
        ],
    }


def _core(**tables: list[dict[str, Any]]) -> dict[str, Any]:
    return {"tables": [{"name": n, "fields": f} for n, f in tables.items()]}


def _config(
    columns: list[dict[str, Any]] | None = None,
    *,
    on_findings: str | None = None,
    detectors: list[str] | None = None,
    extra_tables: list[dict[str, Any]] | None = None,
    table: str = "people",
) -> dict[str, Any]:
    policy: dict[str, Any] = {}
    if on_findings is not None:
        policy["on_findings"] = on_findings
    if detectors is not None:
        policy["detectors"] = detectors
    return {
        "pre_scan": policy,
        "tables": [{"name": table, "columns": columns or []}, *(extra_tables or [])],
    }


def _rule(name: str, strategy: str, **more: Any) -> dict[str, Any]:
    return {"name": name, "strategy": strategy, **more}


def test_e2_t1_unconfigured_flagged_column_is_uncovered() -> None:
    verdict = evaluate_pre_scan(_config([]), _core(people=[_field("email", pii=True)]))
    assert verdict.findings == (PreScanFinding("people", "email", ("regex",), False),)
    assert verdict.status == "warned"


def test_e2_t1_unflagged_column_is_ignored() -> None:
    verdict = evaluate_pre_scan(_config([]), _core(people=[_field("note", pii=False)]))
    assert verdict.status == "passed"
    assert verdict.findings == ()


@pytest.mark.parametrize("strategy", ["hash", "redact", "faker", "from_parent"])
def test_e2_t2_masking_strategies_cover(strategy: str) -> None:
    verdict = evaluate_pre_scan(
        _config([_rule("email", strategy)]), _core(people=[_field("email", pii=True)])
    )
    assert verdict.status == "passed"
    assert verdict.covered == 1


def test_e2_t2_passthrough_is_uncovered() -> None:
    verdict = evaluate_pre_scan(
        _config([_rule("email", "passthrough")]), _core(people=[_field("email", pii=True)])
    )
    assert [(f.column, f.partial) for f in verdict.findings] == [("email", False)]


def test_e2_t2_passthrough_name_is_the_catalog_name() -> None:
    from decoy_engine.profiling import pre_scan_check

    assert StrategyKind.PASSTHROUGH.value == pre_scan_check._PASSTHROUGH


def test_e2_t2b_when_gate_is_partial_coverage() -> None:
    config = _config([_rule("email", "hash", when="country == 'US'")], on_findings="fail")
    verdict = evaluate_pre_scan(config, _core(people=[_field("email", pii=True)]))
    assert verdict.findings == (PreScanFinding("people", "email", ("regex",), True),)
    assert verdict.status == "failed"
    assert verdict.blocking


@pytest.mark.parametrize("when", [None, "", "   "])
def test_e2_t2b_blank_when_is_no_gate(when: str | None) -> None:
    verdict = evaluate_pre_scan(
        _config([_rule("email", "hash", when=when)]), _core(people=[_field("email", pii=True)])
    )
    assert verdict.status == "passed"


def test_e2_t3_high_band_flags_and_review_does_not() -> None:
    config = _config([], detectors=["regex", "ner"])
    high = evaluate_pre_scan(config, _core(people=[_field("bio", hits=(("ner", "high"),))]))
    review = evaluate_pre_scan(config, _core(people=[_field("bio", hits=(("ner", "review"),))]))
    assert [(f.column, f.sources) for f in high.findings] == [("bio", ("ner",))]
    assert review.findings == ()


def test_e2_t3_sources_name_every_flagging_detector_sorted() -> None:
    config = _config([], detectors=["regex", "ner", "classifier"])
    field = _field("bio", pii=True, hits=(("ner", "high"), ("classifier", "high")))
    verdict = evaluate_pre_scan(config, _core(people=[field]))
    assert verdict.findings[0].sources == ("classifier", "ner", "regex")


def test_e2_t4_hit_from_unlisted_detector_does_not_flag() -> None:
    field = _field("bio", hits=(("ner", "high"),))
    unlisted = evaluate_pre_scan(_config([], detectors=["regex"]), _core(people=[field]))
    listed = evaluate_pre_scan(_config([], detectors=["regex", "ner"]), _core(people=[field]))
    assert unlisted.findings == ()
    assert len(listed.findings) == 1


def test_e2_t5_policy_branch() -> None:
    core = _core(people=[_field("email", pii=True)])
    warned = evaluate_pre_scan(_config([], on_findings="warn"), core)
    default = evaluate_pre_scan(_config([]), core)
    failed = evaluate_pre_scan(_config([], on_findings="fail"), core)
    passed = evaluate_pre_scan(_config([_rule("email", "hash")], on_findings="fail"), core)
    assert (warned.status, warned.blocking) == ("warned", False)
    assert default.status == "warned"
    assert (failed.status, failed.blocking) == ("failed", True)
    assert (passed.status, passed.blocking, passed.code) == ("passed", False, None)
    assert warned.code == str(reasons.pre_scan.UNCOVERED_PII)
    assert failed.code == str(reasons.pre_scan.UNCOVERED_PII_BLOCKED)


def test_e2_t5_check_and_counts() -> None:
    core = _core(people=[_field("email", pii=True), _field("ssn", pii=True)])
    config = _config([_rule("ssn", "hash")], on_findings="fail")
    check = evaluate_pre_scan(config, core).to_check()
    assert isinstance(check, Check)
    assert (check.id, check.status, check.blocking) == ("pre_scan", "failed", True)
    assert (check.counts.passed, check.counts.warning, check.counts.fail) == (1, 0, 1)
    assert check.codes == (str(reasons.pre_scan.UNCOVERED_PII_BLOCKED),)
    warned = evaluate_pre_scan(_config([_rule("ssn", "hash")]), core).to_check()
    assert (warned.status, warned.blocking) == ("warned", False)
    assert (warned.counts.warning, warned.counts.fail) == (1, 0)


@pytest.mark.parametrize(("policy", "status"), [("warn", "warned"), ("fail", "failed")])
def test_e2_t6_missing_mask_table_is_not_scanned(policy: str, status: str) -> None:
    config = _config([], on_findings=policy, extra_tables=[{"name": "orders", "columns": []}])
    verdict = evaluate_pre_scan(config, _core(people=[_field("note")]))
    assert verdict.findings == (PreScanFinding("orders", "", ("not_scanned",), False),)
    assert verdict.status == status
    assert verdict.tables_scanned == ("people",)


def test_e2_t6_generate_tables_are_skipped() -> None:
    generate = {"name": "synth", "row_count": 10, "generate_columns": [{"name": "a"}]}
    verdict = evaluate_pre_scan(
        _config([], extra_tables=[generate]), _core(people=[_field("note")])
    )
    assert verdict.status == "passed"
    assert verdict.tables_scanned == ("people",)


def test_e2_t7_nothing_from_a_canary_core_reaches_the_verdict() -> None:
    field = _field("email", pii=True)
    field.update(sample=[CANARY], top_values=[{"value": CANARY, "count": 3}], dtype=CANARY)
    verdict = evaluate_pre_scan(_config([], on_findings="fail"), _core(people=[field]))
    rendered = " ".join(
        (repr(verdict), repr(verdict.to_check()), repr(verdict.findings), str(verdict.code))
    )
    assert CANARY not in rendered
    for error in (PreScanBlockedError(verdict), PreScanFailedError()):
        assert CANARY not in repr(error) + str(error)


def test_e2_t8_findings_sorted_by_table_then_column() -> None:
    config = {
        "pre_scan": {},
        "tables": [
            {"name": "b", "columns": []},
            {"name": "a", "columns": []},
        ],
    }
    core = _core(
        b=[_field("z", pii=True), _field("m", pii=True)],
        a=[_field("y", pii=True), _field("c", pii=True)],
    )
    verdict = evaluate_pre_scan(config, core)
    assert [(f.table, f.column) for f in verdict.findings] == [
        ("a", "c"),
        ("a", "y"),
        ("b", "m"),
        ("b", "z"),
    ]


def test_e2_t10_passed_verdict_carries_detectors_and_tables() -> None:
    config = _config([], detectors=["ner", "regex"])
    verdict = evaluate_pre_scan(config, _core(people=[_field("note")]))
    assert verdict.status == "passed"
    assert verdict.findings == ()
    assert verdict.detectors == ("ner", "regex")
    assert verdict.tables_scanned == ("people",)


def test_e2_t10_detectors_default_to_regex() -> None:
    verdict = evaluate_pre_scan(_config([]), _core(people=[_field("note")]))
    assert verdict.detectors == ("regex",)


def test_e2_t10_pure_generate_config_passes_with_no_tables() -> None:
    generate = {"name": "synth", "row_count": 5, "generate_columns": [{"name": "a"}]}
    config = {"pre_scan": {}, "tables": [generate]}
    verdict = evaluate_pre_scan(config, {"tables": []})
    assert verdict.status == "passed"
    assert verdict.tables_scanned == ()


def test_dropped_flagged_column_is_not_a_finding() -> None:
    config = _config([], on_findings="fail")
    config["tables"][0]["transforms"] = [{"op": "drop_column", "columns": ["ssn"]}]
    core = _core(people=[_field("ssn", pii=True)])
    passed = evaluate_pre_scan(config, core)
    assert (passed.status, passed.findings, passed.covered) == ("passed", (), 0)
    other = evaluate_pre_scan(
        config, _core(people=[_field("ssn", pii=True), _field("email", pii=True)])
    )
    assert [f.column for f in other.findings] == ["email"]
    assert other.status == "failed"


def test_non_mapping_pre_scan_is_refused_not_read_as_warn() -> None:
    config = {"pre_scan": "fail", "tables": [{"name": "people", "columns": []}]}
    with pytest.raises(TypeError):
        evaluate_pre_scan(config, _core(people=[_field("e", pii=True)]))


def test_e2_t9_adapter_rows_give_pre_scan_codes() -> None:
    verdict = evaluate_pre_scan(
        _config([], on_findings="fail"), _core(people=[_field("e", pii=True)])
    )
    blocked = reason_from_exception(PreScanBlockedError(verdict))
    failed = reason_from_exception(PreScanFailedError())
    assert (blocked.namespace, blocked.code) == ("pre_scan", "uncovered_pii_blocked")
    assert (failed.namespace, failed.code) == ("pre_scan", "profile_failed")
    warned = reason_from_exception(PreScanWarning())
    assert (warned.namespace, warned.code) == ("pre_scan", "uncovered_pii")


def test_errors_pickle_and_keep_fixed_text() -> None:
    verdict = evaluate_pre_scan(
        _config([], on_findings="fail"), _core(people=[_field("e", pii=True)])
    )
    blocked = pickle.loads(pickle.dumps(PreScanBlockedError(verdict)))  # noqa: S301
    failed = pickle.loads(pickle.dumps(PreScanFailedError()))  # noqa: S301
    assert blocked.verdict == verdict
    assert blocked.code == str(reasons.pre_scan.UNCOVERED_PII_BLOCKED)
    assert failed.code == str(reasons.pre_scan.PROFILE_FAILED)


def test_warning_class_is_a_user_warning() -> None:
    assert issubclass(PreScanWarning, UserWarning)
    assert PreScanWarning().code == str(reasons.pre_scan.UNCOVERED_PII)
    with pytest.warns(PreScanWarning):
        warnings.warn(PreScanWarning("x"), stacklevel=1)
    assert isinstance(evaluate_pre_scan(_config([]), _core(people=[_field("n")])), PreScanVerdict)
