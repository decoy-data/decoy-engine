"""One not-installed message for every NER surface (SCAN-ML-MD A-3).

With one model reported installed, a config that asks for another is refused before any row is
read, on all four surfaces, with a message that names the refused model, its pinned wheel and the
opt-out key of that surface. Nothing from the rest of the config reaches the text.
"""

from __future__ import annotations

import pickle
from typing import Any

import pytest

from decoy_engine.config import PreScanConfig
from decoy_engine.detection import ner
from decoy_engine.detection._ner_rate import NER_MIN_RATES
from decoy_engine.detection.ner import NER_MODEL_WHEELS, NerSurface
from decoy_engine.plan import PlanCompileError, _checks
from decoy_engine.profiling._model_pass import load_pre_scan
from decoy_engine.verification.postmask._model_findings import post_scan_detectors
from tests._ner import needs_ner

MODELS = sorted(NER_MIN_RATES)
MARKER = "SEEDED_MARKER_8f3a"
KEYS = {
    "pre_scan": "pre_scan.ner_model",
    "post_scan": "post_scan.ner_model",
    "text_redact": "provider_config.ner.model",
    "text_mask": "provider_config.ner.model",
}
CODE = "ner_model_not_installed"


def _wheel_url(model: str) -> str:
    return next(w.url for (name, _), w in NER_MODEL_WHEELS.items() if name == model)


@pytest.fixture
def only_installed(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Report one model installed; loading any pipeline fails the cell."""

    def install(model: str) -> None:
        monkeypatch.setattr(ner, "spacy_installed", lambda: True)
        monkeypatch.setattr(ner, "model_installed", lambda name=model: name == model)
        # A fallback to the installed model must be able to succeed (with or without a real
        # spaCy in this venv), or it cannot be caught.
        monkeypatch.setattr(ner, "_import_spacy", lambda: (object(), None))
        monkeypatch.setattr(ner, "_spacy_incompatible", lambda _spacy, _model: False)
        monkeypatch.setattr(
            ner, "installed_model_version", lambda name=model: "3.8.0" if name == model else None
        )

        def _no_load(_name: str) -> Any:
            raise AssertionError("a pipeline was loaded for a refused model")

        monkeypatch.setattr(ner, "_pipeline", _no_load)

    return install


def _config(surface: str, asked: str | None) -> dict[str, Any]:
    ner_cfg: Any = True if asked is None else {"model": asked}
    column = {
        "name": MARKER,
        "strategy": surface,
        "provider_config": {"ner": ner_cfg, "note": MARKER},
    }
    return {"tables": [{"name": MARKER, "columns": [column]}]}


def _run(surface: str, asked: str | None) -> None:
    if surface == "pre_scan":
        kwargs: dict[str, Any] = {"detectors": ("regex", "ner")}
        if asked is not None:
            kwargs["ner_model"] = asked
        load_pre_scan(PreScanConfig(**kwargs), None)
    elif surface == "post_scan":
        block: dict[str, Any] = {
            "integrity": True,
            "detectors": ["regex", "ner"],
            "dismissed": [{"table": MARKER}],
        }
        if asked is not None:
            block["ner_model"] = asked
        post_scan_detectors({"post_scan": block})
    elif surface == "text_redact":
        _checks.check_text_redact_ner_available(_config(surface, asked))
    else:
        _checks.check_text_mask_ner_available(_config(surface, asked))


CELLS = [
    (surface, installed, asked)
    for surface in KEYS
    for installed in MODELS
    for asked in [None, *MODELS]
    if (asked or ner.DEFAULT_NER_MODEL) != installed
]


@pytest.mark.parametrize(("surface", "installed", "asked"), CELLS)
def test_refusal_names_model_wheel_and_opt_out(
    only_installed: Any, surface: str, installed: str, asked: str | None
) -> None:
    only_installed(installed)
    refused = asked or ner.DEFAULT_NER_MODEL
    with pytest.raises((ner.NerUnavailableError, PlanCompileError, Exception)) as caught:
        _run(surface, asked)
    exc = caught.value
    assert CODE in (getattr(exc, "code", ""), str(getattr(exc, "reason", "")).rpartition(".")[2])
    text = str(getattr(exc, "message", None) or exc)
    assert refused in text
    assert _wheel_url(refused) in text
    assert KEYS[surface] in text
    assert surface in text
    assert MARKER not in text
    assert exc.__cause__ is None and exc.__context__ is None
    for key in KEYS.values():
        if key != KEYS[surface]:
            assert key not in text


def test_a_model_without_a_pinned_wheel_says_so() -> None:
    text = ner.model_not_installed_message("xx_unpinned_model", NerSurface.POST_SCAN)
    assert "xx_unpinned_model" in text
    assert "no pinned wheel" in text
    assert "post_scan.ner_model" in text


def test_the_run_time_call_without_a_surface_uses_the_column_key(only_installed: Any) -> None:
    only_installed("en_core_web_sm")
    with pytest.raises(ner.NerUnavailableError) as caught:
        ner.ensure_ner_available("en_core_web_md")
    assert "provider_config.ner.model" in caught.value.message
    assert _wheel_url("en_core_web_md") in caught.value.message


def test_a_refusal_survives_pickling(only_installed: Any) -> None:
    only_installed("en_core_web_sm")
    with pytest.raises(Exception) as caught:
        _run("pre_scan", "en_core_web_md")
    again = pickle.loads(pickle.dumps(caught.value))  # noqa: S301 (our own error)
    assert str(again) == str(caught.value)
    assert "en_core_web_md" in str(again)


@needs_ner
@pytest.mark.parametrize("surface", list(KEYS))
def test_the_default_installed_loads_on_every_surface(surface: str) -> None:
    default = ner.DEFAULT_NER_MODEL
    if surface == "pre_scan":
        _, runs = load_pre_scan(PreScanConfig(detectors=("regex", "ner")), None)
        assert any(run.model is not None and run.model.id == default for run in runs)
    elif surface == "post_scan":
        block = {"integrity": True, "detectors": ["regex", "ner"]}
        loaded = post_scan_detectors({"post_scan": block})
        assert loaded is not None and loaded.ner is not None and loaded.ner.id == default
    else:
        ner.ensure_ner_available(default, NerSurface(surface))
        spans = list(ner.iter_ner_spans_batch(["Maria Lopez lives in Paris"], model=default))
        assert spans
