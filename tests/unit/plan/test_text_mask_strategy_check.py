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


@pytest.mark.parametrize(("detector", "strategy"), [("ssn", "date_shift"), ("email", "faker")])
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
    assert _refusal({"detectors": ["no_such_detector"]}).code == _UNKNOWN
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

    assert frozenset(_SPAN_DETECTORS) == SPAN_DETECTOR_IDS
    assert tm.SELECTABLE_TEXT_MASK_DETECTORS == SPAN_DETECTOR_IDS
    assert (
        SPAN_DETECTOR_IDS | frozenset(NER_ENTITY_MAP.values()) | frozenset(tm.DETECTOR_DEFAULTS)
    ) == tm.TEXT_MASK_STRATEGY_DETECTORS
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


def test_checks_passed_lists_the_new_check(simple_config: dict, simple_profile: Profile) -> None:
    simple_config["tables"][0]["columns"] = [
        {
            "name": "name",
            "strategy": "text_mask",
            "provider_config": {"per_detector_strategy": {"ssn": "fpe"}},
        }
    ]
    plan = compile_plan(simple_config, simple_profile, decoy_engine_version="0.1.0")
    assert plan.plan_compile.checks_passed[-1] == "text_mask_strategies"
    assert run_config_only_checks(simple_config)[-1] == "text_mask_strategies"


# AT-A1d direct kernel cells. After E-F0 no config can send a person_name or date span to the
# native chunked, out-of-core native or SEQ routes, so these cells are the only place the faker
# and date_shift branches of `_mask_span` run on the library `extra_spans` path.

_TEXT = "ssn 123-45-6789, Alice Jones, 2024-02-20, 2024-02-30"


def _spans() -> list[Span]:
    def at(det: str, real: str) -> Span:
        start = _TEXT.index(real)
        return Span(det, start, start + len(real), real)

    return [
        at("ssn", "123-45-6789"),
        at("person_name", "Alice Jones"),
        at("iso_date", "2024-02-20"),
        Span("iso_date", _TEXT.rindex("2024-02-30"), len(_TEXT), "2024-02-30"),
    ]


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    seen = {"fpe": 0, "faker": 0, "date_shift": 0}
    for name, attr in (
        ("fpe", "_mask_fpe"),
        ("faker", "_mask_faker"),
        ("date_shift", "_mask_date_shift"),
    ):
        real = getattr(tm, attr)

        def counted(*a: Any, _real: Any = real, _name: str = name, **k: Any) -> str:
            seen[_name] += 1
            return str(_real(*a, **k))

        monkeypatch.setattr(tm, attr, counted)
    return seen


def _assert_masked(out: str) -> None:
    for real in ("123-45-6789", "Alice Jones", "2024-02-20", "2024-02-30"):
        assert real not in out
    assert out.endswith("[REDACTED]")  # the unparseable date span


def test_a1d_mask_cell_with_spans_runs_every_strategy(calls: dict[str, int]) -> None:
    out = tm.mask_cell_with_spans(
        _TEXT, _spans(), _KEY, unmatched_span_policy="passthrough", sub_floor_span_policy="redact"
    )
    _assert_masked(out)
    assert calls["fpe"] > 0 and calls["faker"] > 0 and calls["date_shift"] > 0


def test_a1d_mask_cell_hybrid_runs_every_strategy(calls: dict[str, int]) -> None:
    from decoy_engine.execution.native._text_mask_native_fpe import mask_cell_hybrid

    out = mask_cell_hybrid(
        _TEXT,
        _spans(),
        {},
        _KEY,
        strategy_map=None,
        unmatched_span_policy="passthrough",
        token="[REDACTED]",
        cfg=None,
        sub_floor_span_policy="redact",
        sub_floor_notices=None,
    )
    _assert_masked(out)
    assert calls["fpe"] > 0 and calls["faker"] > 0 and calls["date_shift"] > 0


def test_a1d_faker_is_keyed_on_the_value_not_the_position() -> None:
    repeated = "Alice Jones and Alice Jones"
    spans = [Span("person_name", 0, 11, "Alice Jones"), Span("person_name", 16, 27, "Alice Jones")]
    out = tm.mask_cell_with_spans(repeated, spans, _KEY, unmatched_span_policy="passthrough")
    first, _, second = out.partition(" and ")
    assert first == second and first != "Alice Jones"
