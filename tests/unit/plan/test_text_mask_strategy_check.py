"""E-F0: detector and strategy pairs a `text_mask` column cannot carry out do not compile.

Before this check, `per_detector_strategy: {ssn: date_shift}` wrote the real SSN to the output
(an unparseable date span came back unchanged), `fpe` on any detector ran a digits cipher, and a
misspelled detector id or strategy name was skipped or fell to the redact token. The check runs at
compile and in `decoy validate`, before route choice.
"""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine import reasons
from decoy_engine.detection.detectors import _SPAN_DETECTORS, Span
from decoy_engine.detection.ner import NER_ENTITY_MAP
from decoy_engine.errors import ConfigError
from decoy_engine.plan import PlanCompileError, compile_plan
from decoy_engine.plan._compile import run_config_only_checks
from decoy_engine.profile import Profile
from decoy_engine.transforms import text_mask as tm

_UNSUPPORTED = str(reasons.config.MASK_TEXT_MASK_STRATEGY_UNSUPPORTED)
_UNKNOWN = str(reasons.config.MASK_TEXT_MASK_DETECTOR_UNKNOWN)
_KEY = b"\x07" * 32


def _config(provider_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "global_settings": {"seed": 42},
        "tables": [
            {
                "name": "customers",
                "columns": [
                    {"name": "name", "strategy": "text_mask", "provider_config": provider_config}
                ],
            }
        ],
    }


def _refusal(provider_config: dict[str, Any]) -> PlanCompileError:
    with pytest.raises(PlanCompileError) as exc:
        run_config_only_checks(_config(provider_config))
    return exc.value


@pytest.mark.parametrize(
    ("detector", "strategy"),
    [("ssn", "date_shift"), ("email", "date_shift"), ("email", "fpe"), ("email", "faker")],
)
def test_a1a_unsupported_pair_refused(detector: str, strategy: str) -> None:
    err = _refusal({"per_detector_strategy": {detector: strategy}})
    assert err.code == _UNSUPPORTED
    assert detector in err.message and strategy in err.message
    assert err.path is not None and "per_detector_strategy" in err.path
    assert err.__cause__ is None and err.__context__ is None


@pytest.mark.parametrize(
    ("detector", "strategy"), [("ssn", "date_shift"), ("email", "faker")]
)
def test_a1a_compile_plan_refuses_the_same_pair(
    simple_profile: Profile, detector: str, strategy: str
) -> None:
    cfg = _config({"per_detector_strategy": {detector: strategy}})
    with pytest.raises(PlanCompileError) as exc:
        compile_plan(cfg, simple_profile, decoy_engine_version="0.1.0")
    assert exc.value.code == _UNSUPPORTED
    with pytest.raises(PlanCompileError) as exc2:
        compile_plan(cfg, simple_profile, decoy_engine_version="0.1.0", no_profile=True)
    assert exc2.value.code == _UNSUPPORTED


def test_a1b_misspelled_strategy_name_refused() -> None:
    assert _refusal({"per_detector_strategy": {"person_name": "fakr"}}).code == _UNSUPPORTED


def test_a1c_unknown_detector_id_refused_in_both_fields() -> None:
    selector = _refusal({"detectors": ["emial"]})
    assert selector.code == _UNKNOWN
    assert selector.path is not None and selector.path.endswith("detectors")
    override = _refusal({"per_detector_strategy": {"emial": "redact"}})
    assert override.code == _UNKNOWN
    assert override.path is not None and "per_detector_strategy" in override.path


@pytest.mark.parametrize("bad", [7, None, ("ssn",)])
def test_non_string_ids_and_strategies_are_refused_not_coerced(bad: Any) -> None:
    with pytest.raises(PlanCompileError):
        run_config_only_checks(_config({"detectors": [bad]}))
    with pytest.raises(PlanCompileError):
        run_config_only_checks(_config({"per_detector_strategy": {"ssn": bad}}))


def test_a1c_compile_plan_refuses_unknown_detector(simple_profile: Profile) -> None:
    cfg = _config({"detectors": ["emial"]})
    with pytest.raises(PlanCompileError) as exc:
        compile_plan(cfg, simple_profile, decoy_engine_version="0.1.0")
    assert exc.value.code == _UNKNOWN


def test_a1d_selectors_compile_and_override_only_ids_are_refused_there() -> None:
    selectable = tm.SELECTABLE_TEXT_MASK_DETECTORS
    override_only = tm.TEXT_MASK_STRATEGY_DETECTORS - selectable
    assert selectable and override_only
    for det in sorted(selectable):
        run_config_only_checks(_config({"detectors": [det]}))
    for det in sorted(override_only):
        assert _refusal({"detectors": [det]}).code == _UNKNOWN


def test_a1d_every_supported_pair_compiles_as_an_override() -> None:
    supported = 0
    for det in sorted(tm.TEXT_MASK_STRATEGY_DETECTORS):
        for strategy in ("fpe", "faker", "date_shift", "redact", "passthrough"):
            if tm.strategy_supported(det, strategy):
                supported += 1
                run_config_only_checks(_config({"per_detector_strategy": {det: strategy}}))
    assert supported > len(tm.TEXT_MASK_STRATEGY_DETECTORS)


def test_a1d_every_default_strategy_is_supported() -> None:
    for det, strategy in tm.DETECTOR_DEFAULTS.items():
        assert tm.strategy_supported(det, strategy), (det, strategy)


def test_a1g_library_only_ids_are_not_selectors() -> None:
    for det in ("iso_date", "person_name"):
        err = _refusal({"detectors": [det]})
        assert err.code == _UNKNOWN
        assert err.path is not None and err.path.endswith("detectors")
    run_config_only_checks(_config({"per_detector_strategy": {"iso_date": "date_shift"}}))
    run_config_only_checks(_config({"per_detector_strategy": {"person_name": "faker"}}))


def test_inventories_are_derived_not_listed() -> None:
    from decoy_engine.detection.detectors import SPAN_DETECTOR_IDS

    assert SPAN_DETECTOR_IDS == frozenset(_SPAN_DETECTORS)
    assert tm.SELECTABLE_TEXT_MASK_DETECTORS == SPAN_DETECTOR_IDS
    assert tm.TEXT_MASK_STRATEGY_DETECTORS == (
        SPAN_DETECTOR_IDS | frozenset(NER_ENTITY_MAP.values()) | frozenset(tm.DETECTOR_DEFAULTS)
    )
    assert "iso_date" in tm.TEXT_MASK_STRATEGY_DETECTORS - tm.SELECTABLE_TEXT_MASK_DETECTORS


def test_strategy_supported_rules() -> None:
    assert tm.strategy_supported("ssn", "fpe")
    assert not tm.strategy_supported("email", "fpe")
    assert tm.strategy_supported("person_name", "faker")
    assert not tm.strategy_supported("email", "faker")
    assert tm.strategy_supported("iso_date", "date_shift")
    assert not tm.strategy_supported("ssn", "date_shift")
    assert tm.strategy_supported("email", "redact") and tm.strategy_supported("ssn", "passthrough")
    assert not tm.strategy_supported("emial", "redact")
    assert not tm.strategy_supported("ssn", "fakr")
    assert not tm.strategy_supported("ssn", 3)  # type: ignore[arg-type]


def test_check_and_mask_span_agree_on_every_pair() -> None:
    """The check refuses a pair exactly when `_mask_span` raises the tagged error for it."""
    for det in sorted(tm.TEXT_MASK_STRATEGY_DETECTORS):
        for strategy in ("fpe", "faker", "date_shift", "redact", "passthrough", "fakr"):
            try:
                run_config_only_checks(_config({"per_detector_strategy": {det: strategy}}))
                refused = False
            except PlanCompileError:
                refused = True
            try:
                tm._mask_span(
                    Span(det, 0, 10, "2024-01-15"),
                    _KEY,
                    strategy,
                    {"token": "[T]"},
                    sub_floor_span_policy="redact",
                )
                raised = False
            except ConfigError:
                raised = True
            except Exception:
                raised = False
            assert refused == raised, (det, strategy)


def test_checks_passed_lists_the_new_check(simple_profile: Profile) -> None:
    cfg = _config({"per_detector_strategy": {"ssn": "fpe"}})
    plan = compile_plan(cfg, simple_profile, decoy_engine_version="0.1.0")
    assert plan.plan_compile.checks_passed[-1] == "text_mask_strategies"
    assert "text_mask_strategies" in run_config_only_checks(cfg)
