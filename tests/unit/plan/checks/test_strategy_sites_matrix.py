"""Each consumer of the strategy-site walker, on each form a strategy can sit in.

The forms are a top-level column, the single nested form, and a `rules` nested child. The
consumers are the text_mask strategy check, NER availability, the NER fingerprint, the NER version
stamp on the seed envelope, and the two provider checks. A nested child must be held to the same
checks and stamps as a top-level column; each cell here fails when its consumer skips a form.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from decoy_engine.detection import ner
from decoy_engine.plan import PlanCompileError, compile_plan, run_config_only_checks
from decoy_engine.plan.checks._ner_models import run_ner_models
from decoy_engine.plan.checks._strategy_sites import provider_sites, strategy_sites
from decoy_engine.profile import Profile

FORMS = ("top", "single", "rules")


def _config(form: str, strategy: str, strategy_config: dict[str, Any], **column: Any) -> dict:
    entry: dict[str, Any] = {"name": "name", "namespace": "ns", **column}
    if form == "top":
        entry |= {"strategy": strategy, "provider_config": strategy_config}
    else:
        child = {"target": "$.note", "strategy": strategy, "strategy_config": strategy_config}
        entry |= {
            "strategy": "nested",
            "provider_config": child if form == "single" else {"rules": [child]},
        }
    return {"tables": [{"name": "customers", "columns": [entry]}]}


def _on(base: dict, config: dict) -> dict:
    """`config`'s columns on the shared fixture config, so a compile has its relationships."""
    base = copy.deepcopy(base)
    base["tables"][0]["columns"] = config["tables"][0]["columns"]
    return base


def _path_of(form: str) -> str:
    base = "tables.customers.columns.name.provider_config"
    return {
        "top": base,
        "single": f"{base}.strategy_config",
        "rules": f"{base}.rules[0].strategy_config",
    }[form]


@pytest.fixture
def ner_ready(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """NER reads as installed, so a compile reaches the seed envelope."""
    monkeypatch.setattr(ner, "ensure_ner_available", lambda model=None, surface=None: None)
    return monkeypatch


def _entry_points(config: dict, profile: Profile):
    return (
        lambda: run_config_only_checks(config),
        lambda: compile_plan(config, profile, decoy_engine_version="0.1.0"),
    )


@pytest.mark.parametrize("form", FORMS)
def test_the_walker_yields_one_strategy_site_per_form(form: str) -> None:
    sites = [s for s in strategy_sites(_config(form, "redact", {})) if s.strategy == "redact"]
    assert len(sites) == 1
    assert sites[0].nested is (form != "top")
    assert sites[0].rule == (0 if form == "rules" else None)


@pytest.mark.parametrize("form", FORMS)
def test_text_mask_strategy_check_reaches_every_form(form: str, simple_profile: Profile) -> None:
    config = _config(form, "text_mask", {"detectors": ["emial"]})
    for call in _entry_points(config, simple_profile):
        with pytest.raises(PlanCompileError) as err:
            call()
        assert err.value.code == "mask.text_mask_detector_unknown"
        assert err.value.path == f"{_path_of(form)}.detectors"


@pytest.mark.parametrize("surface", ["text_mask", "text_redact"])
@pytest.mark.parametrize("form", FORMS)
def test_ner_availability_reaches_every_form(
    form: str, surface: str, monkeypatch: pytest.MonkeyPatch, simple_profile: Profile
) -> None:
    def missing(model: Any = None, surface: Any = None) -> None:
        raise ner.NerUnavailableError(code="ner_model_missing", message="model is not installed")

    monkeypatch.setattr(ner, "ensure_ner_available", missing)
    config = _config(form, surface, {"ner": True})
    for call in _entry_points(config, simple_profile):
        with pytest.raises(PlanCompileError) as err:
            call()
        assert err.value.code == "ner_model_missing"
        assert err.value.path == f"{_path_of(form)}.ner"


@pytest.mark.parametrize("form", FORMS)
def test_the_ner_fingerprint_reaches_every_form(form: str) -> None:
    config = _config(form, "text_mask", {"ner": {"model": "en_core_web_md"}})
    assert run_ner_models(config) == (("text_mask", "en_core_web_md"),)
    assert run_ner_models(_config(form, "text_mask", {})) == ()


@pytest.mark.parametrize("form", FORMS)
def test_the_seed_envelope_stamps_the_ner_version_on_every_form(
    form: str, ner_ready: pytest.MonkeyPatch, simple_profile: Profile, simple_config: dict
) -> None:
    ner_ready.setattr(ner, "installed_model_version", lambda model="x": "9.9.9")
    plan = compile_plan(
        _on(simple_config, _config(form, "text_mask", {"ner": True})),
        simple_profile,
        decoy_engine_version="0.1.0",
    )
    seeds = dict(dict(plan.seed_envelope.per_table)["customers"].per_column)
    assert seeds["name"].ner_model_version == "9.9.9"


def test_two_ner_models_in_one_nested_column_are_each_pinned(
    ner_ready: pytest.MonkeyPatch, simple_profile: Profile, simple_config: dict
) -> None:
    ner_ready.setattr(ner, "installed_model_version", lambda model="x": f"v-{model}")
    rule = lambda target, model: {
        "target": target,
        "strategy": "text_mask",
        "strategy_config": {"ner": {"model": model}},
    }
    config = {
        "tables": [
            {
                "name": "customers",
                "columns": [
                    {
                        "name": "name",
                        "strategy": "nested",
                        "namespace": "ns",
                        "provider_config": {
                            "rules": [rule("$.a", "en_core_web_sm"), rule("$.b", "en_core_web_md")]
                        },
                    }
                ],
            }
        ]
    }
    plan = compile_plan(_on(simple_config, config), simple_profile, decoy_engine_version="0.1.0")
    stamp = dict(dict(plan.seed_envelope.per_table)["customers"].per_column)[
        "name"
    ].ner_model_version
    assert ner.pinned_ner_version(stamp, "en_core_web_sm") == "v-en_core_web_sm"
    assert ner.pinned_ner_version(stamp, "en_core_web_md") == "v-en_core_web_md"


def test_top_level_and_plain_seeds_are_unchanged(
    ner_ready: pytest.MonkeyPatch, simple_profile: Profile, simple_config: dict
) -> None:
    ner_ready.setattr(ner, "installed_model_version", lambda model="x": "9.9.9")
    top = compile_plan(
        _on(simple_config, _config("top", "text_mask", {"ner": True})),
        simple_profile,
        decoy_engine_version="0.1.0",
    )
    plain = compile_plan(
        _on(simple_config, _config("top", "redact", {})),
        simple_profile,
        decoy_engine_version="0.1.0",
    )
    top_seed = dict(dict(top.seed_envelope.per_table)["customers"].per_column)["name"]
    plain_seed = dict(dict(plain.seed_envelope.per_table)["customers"].per_column)["name"]
    # A top-level stamp is the bare installed version, as before; a plain column carries none.
    assert top_seed.ner_model_version == "9.9.9"
    assert plain_seed.ner_model_version is None
    assert ner.pin_ner_versions({"m": "1.2"}) == "1.2"
    assert ner.pin_ner_versions({"m": None}) is None
    assert ner.pinned_ner_version("1.2", "m") == "1.2"


def test_a_missing_model_version_warns_with_the_unchanged_text(
    ner_ready: pytest.MonkeyPatch, simple_profile: Profile, simple_config: dict
) -> None:
    ner_ready.setattr(ner, "installed_model_version", lambda model="x": None)
    plan = compile_plan(
        _on(simple_config, _config("top", "text_mask", {"ner": True})),
        simple_profile,
        decoy_engine_version="0.1.0",
    )
    expected = (
        "ner_model_version_unavailable: column customers.name uses ner model "
        f"{ner.DEFAULT_NER_MODEL!r} which has no installed package metadata; text_mask output is "
        "byte-stable only within this environment."
    )
    assert expected in plan.plan_compile.warnings


@pytest.mark.parametrize("form", ["top", "single", "rules"])
def test_provider_checks_reach_a_faker_in_every_form(form: str, simple_profile: Profile) -> None:
    column = {"provider": "no_such_provider"}
    config = _config(form, "faker", {}, **column)
    for call in _entry_points(config, simple_profile):
        with pytest.raises(PlanCompileError) as err:
            call()
        assert err.value.code == "unknown_provider"
    config = _config(form, "faker", {}, provider="address_full")
    for call in _entry_points(config, simple_profile):
        with pytest.raises(PlanCompileError) as err:
            call()
        assert err.value.code == "non_poolable_provider_with_pool_backend"


def test_a_provider_site_is_pooled_only_for_faker() -> None:
    sites = list(provider_sites(_config("single", "hash", {}, provider="person_email")))
    assert [s.pooled for s in sites] == [False]
