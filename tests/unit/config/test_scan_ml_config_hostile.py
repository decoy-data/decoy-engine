"""Hostile config corpus. Each case is refused with its code and no value is echoed."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from decoy_engine.config import PipelineConfig
from decoy_engine.detection.ner import NerUnavailableError, ensure_ner_available
from decoy_engine.detection.types import validate_ner_model_name
from decoy_engine.plan import PlanCompileError
from decoy_engine.plan._checks import check_text_redact_ner_available

BASE: dict[str, Any] = {
    "version": 2,
    "global_settings": {"seed": 7},
    "sources": {"p": {"type": "file", "format": "csv", "has_header": True, "path": "/data/p.csv"}},
    "tables": [{"name": "p", "columns": [{"name": "id", "strategy": "hash", "namespace": "ids"}]}],
    "targets": {"p": {"type": "file", "format": "csv", "path": "/data/o.csv"}},
}
HOSTILE_MODELS = ["../x", "/tmp/m", "En_Core", "https://evil.example/m.whl", "en_core_web_sm\n", ""]
DISMISSAL: dict[str, Any] = {
    "table": "t",
    "column": "c",
    "detector_id": "person_name",
    "source": "ner",
    "model_id": "en_core_web_sm",
    "model_version": "3.8.0",
    "strategy": "text_redact",
}


def _cfg(**blocks: Any) -> dict[str, Any]:
    raw = copy.deepcopy(BASE)
    raw.update(blocks)
    return raw


def _refused(raw: dict[str, Any], code: str, *secrets: str) -> None:
    with pytest.raises(ValidationError) as caught:
        PipelineConfig.model_validate(raw)
    exc = caught.value
    assert code in {e["type"] for e in exc.errors()}
    shown = str(exc) + repr(exc) + exc.json(include_input=False)
    for secret in secrets:
        assert secret not in shown


def _block(scan: str, **fields: Any) -> dict[str, Any]:
    block: dict[str, Any] = dict(fields)
    if scan == "post_scan":
        block["integrity"] = True
    return _cfg(**{scan: block})


@pytest.mark.parametrize("scan", ["pre_scan", "post_scan"])
@pytest.mark.parametrize(
    ("detectors", "expected"),
    [
        (["classifier"], ("regex", "classifier")),
        (["ner"], ("regex", "ner")),
        ([], ("regex",)),
        (["ner", "regex"], ("regex", "ner")),
        (["ner", "classifier"], ("regex", "classifier", "ner")),
    ],
)
def test_regex_is_added_when_missing(
    scan: str, detectors: list[str], expected: tuple[str, ...]
) -> None:
    """AT-E1a, AT-E1b: a list without regex is normalized, never refused."""
    parsed = PipelineConfig.model_validate(_block(scan, detectors=detectors))
    assert getattr(parsed, scan).detectors == expected


@pytest.mark.parametrize("scan", ["pre_scan", "post_scan"])
@pytest.mark.parametrize(
    ("detectors", "code"),
    [
        (["regex", "regex"], "detectors_invalid"),
        (["regex", "ner", "ner"], "detectors_invalid"),
        (["ner", "ner"], "detectors_invalid"),
        (["bogus"], "literal_error"),
        (["regex\n"], "literal_error"),
    ],
)
def test_detector_repeats_and_unknown_sources_stay_refused(
    scan: str, detectors: list[str], code: str
) -> None:
    """AT-E1c: the repeat and unknown-source refusals keep the codes main raises today."""
    _refused(_block(scan, detectors=detectors), code)


@pytest.mark.parametrize("detectors", [["regex"], ["classifier"], []])
def test_ner_model_without_ner_is_still_refused(detectors: list[str]) -> None:
    """AT-E1c: normalizing regex in does not make `ner_model` valid without ner."""
    raw = _cfg(pre_scan={"detectors": detectors, "ner_model": "en_core_web_sm"})
    _refused(raw, "pre_scan_ner_inactive")


@pytest.mark.parametrize("scan", ["pre_scan", "post_scan"])
@pytest.mark.parametrize("model", HOSTILE_MODELS)
def test_ner_model_must_be_a_plain_package_name(scan: str, model: str) -> None:
    block: dict[str, Any] = {"detectors": ["regex", "ner"], "ner_model": model}
    if scan == "post_scan":
        block["integrity"] = True
    _refused(
        _cfg(**{scan: block}), "ner_model_invalid", model.strip() or "xxxx-never", "evil.example"
    )


@pytest.mark.parametrize(
    "model", [m for m in HOSTILE_MODELS if m]
)  # "" means the default model there
def test_provider_config_ner_model_is_refused_before_spacy_is_asked(model: str) -> None:
    config = {
        "tables": [
            {
                "name": "p",
                "columns": [
                    {
                        "name": "note",
                        "strategy": "text_redact",
                        "provider_config": {"ner": {"model": model}},
                    }
                ],
            }
        ]
    }
    with pytest.raises(PlanCompileError) as caught:
        check_text_redact_ner_available(config)
    assert caught.value.code == "ner_model_invalid"
    shown = str(caught.value) + caught.value.message
    assert "evil.example" not in shown and "/tmp" not in shown and "../" not in shown
    with pytest.raises(NerUnavailableError) as direct:
        ensure_ner_available(model)
    assert direct.value.code == "ner_model_invalid"
    assert model.strip() == "" or model.strip() not in str(direct.value)


def test_validate_ner_model_name_accepts_plain_names_and_uses_fullmatch() -> None:
    for ok in ("en_core_web_sm", "de_core_news_md", "xx_ent_wiki_sm"):
        assert validate_ner_model_name(ok) == ok
    for bad in [*HOSTILE_MODELS, "a", "9abc", "x" * 65, "en-core", "en core", None, 5]:
        with pytest.raises(NerUnavailableError):
            validate_ner_model_name(bad)


@pytest.mark.parametrize(
    "dismissal",
    [
        {**DISMISSAL, "source": "regex"},  # a regex dismissal with a model id
        {**{k: v for k, v in DISMISSAL.items() if k not in ("model_id", "model_version")}},
        {**DISMISSAL, "model_version": None},
        {**DISMISSAL, "strategy": 5},
        {**DISMISSAL, "strategy": ["text_redact"]},
        {**DISMISSAL, "table": 3},
    ],
)
def test_dismissal_shape_is_refused_without_echo(dismissal: dict[str, Any]) -> None:
    raw = _cfg(post_scan={"integrity": True, "dismissed": [dismissal]})
    _refused(raw, "dismissal_invalid", "en_core_web_sm", "3.8.0")


def test_a_regex_dismissal_needs_no_model_and_a_null_strategy_is_valid() -> None:
    ok = {"table": "t", "column": "c", "detector_id": "email", "source": "regex", "strategy": None}
    cfg = PipelineConfig.model_validate(_cfg(post_scan={"integrity": True, "dismissed": [ok]}))
    assert cfg.post_scan.dismissed[0].strategy is None


@pytest.mark.parametrize(
    "post_scan",
    [
        {"integrity": True, "ner_findings": "fail"},  # fail without ner
        {"integrity": True, "ner_model": "en_core_web_sm"},  # a set model without ner
        {"integrity": True, "ner_model": "en_core_web_sm", "detectors": ["regex"]},
        {"integrity": False, "detectors": ["regex", "ner"]},  # model detectors, no integrity
        {"integrity": False, "detectors": ["regex", "ner"], "ner_findings": "fail"},
        {"integrity": False, "dismissed": [{**DISMISSAL}]},
    ],
)
def test_post_scan_settings_that_would_silently_do_nothing_are_refused(
    post_scan: dict[str, Any],
) -> None:
    _refused(_cfg(post_scan=post_scan), "post_scan_inactive")


def test_pre_scan_ner_model_without_ner_is_refused_with_its_own_code() -> None:
    _refused(_cfg(pre_scan={"ner_model": "en_core_web_sm"}), "pre_scan_ner_inactive")
    with pytest.raises(ValidationError) as caught:
        PipelineConfig.model_validate(_cfg(pre_scan={"ner_model": "en_core_web_sm"}))
    assert "post_scan_inactive" not in {e["type"] for e in caught.value.errors()}


def test_the_valid_neighbours_of_the_corpus_pass() -> None:
    PipelineConfig.model_validate(
        _cfg(
            pre_scan={"detectors": ["regex", "classifier", "ner"], "ner_model": "en_core_web_sm"},
            post_scan={
                "integrity": True,
                "detectors": ["regex", "ner"],
                "ner_model": "de_core_news_sm",
                "ner_findings": "fail",
                "dismissed": [DISMISSAL],
            },
        )
    )
