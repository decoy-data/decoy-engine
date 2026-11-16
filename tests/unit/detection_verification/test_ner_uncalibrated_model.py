"""M-T5: a scan NER model with no calibrated rate is refused at load, before any row is read.

`pre_scan` and `post_scan` score a column against the model's own `NER_MIN_RATES` entry. A model
without one (`en_core_web_lg`, `en_core_web_trf`, a non-English model) would have run on sm's
0.211 until now. It is refused when the detectors load, with `provider.ner_model_uncalibrated`.
`text_redact` redacts spans and reads no rate, so the same name is not refused there.

The model is faked as installed so the refusal is the calibration one and not "not installed". A
model that is absent or incompatible keeps its own, earlier reason.

Mutations: MM-5 (fall back to sm's rate instead of refusing), MM-5b (refuse in `text_redact` too).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from decoy_engine import reasons
from decoy_engine.config import PreScanConfig
from decoy_engine.detection import ModelRef, ModelStatus, ModelUnavailableError, ner
from decoy_engine.detection import _model_status as ms
from decoy_engine.detection._ner_rate import NER_MIN_RATES
from decoy_engine.detection.ner import NER_MODEL_WHEELS
from decoy_engine.plan._checks import check_text_redact_ner_available
from decoy_engine.profiling import scan_set, scan_sources
from decoy_engine.profiling.model_pack import _detectors
from decoy_engine.profiling.model_pack._detectors import load_detectors
from decoy_engine.verification.postmask._model_findings import post_scan_detectors
from tests._ner import needs_ner
from tests.unit.detection_verification._fake_ner_model import make_fake_model
from tests.unit.profiling import _scanml_m3a_support as s

UNCALIBRATED = "provider.ner_model_uncalibrated"
UNCALIBRATED_NAMES = ["en_core_web_lg", "en_core_web_trf", "de_core_news_sm"]


@pytest.fixture(autouse=True)
def _installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every model name reads as installed, so only the calibration check can refuse."""

    def state(model: str) -> tuple[ModelStatus, ModelRef]:
        return ModelStatus("ner", model, True, "3.8.0", "3.8.14", None), ModelRef(model, "3.8.0")

    monkeypatch.setattr(_detectors, "ner_model_state", state)


def test_the_reason_is_registered_and_unreleased() -> None:
    code = reasons.provider.NER_MODEL_UNCALIBRATED
    assert ms.qualified(code) == UNCALIBRATED
    assert ms.registered_model_reason(UNCALIBRATED) is code


@pytest.mark.parametrize("name", UNCALIBRATED_NAMES)
def test_load_detectors_refuses_a_model_with_no_rate(name: str) -> None:
    assert name not in NER_MIN_RATES
    with pytest.raises(ModelUnavailableError) as refused:
        load_detectors(("regex", "ner"), ner_model=name)
    assert refused.value.reason == UNCALIBRATED
    assert refused.value.__cause__ is None and refused.value.__context__ is None
    assert name not in str(refused.value)  # the message names the code, never the value


@pytest.mark.parametrize("name", sorted(NER_MIN_RATES))
def test_a_calibrated_model_loads(name: str) -> None:
    found = load_detectors(("regex", "ner"), ner_model=name)
    assert found.ner == ModelRef(name, "3.8.0")


def test_a_set_with_no_ner_never_looks_at_the_model_name() -> None:
    assert load_detectors(("regex",), ner_model="en_core_web_lg").ner is None


def test_post_scan_refuses_at_run_start() -> None:
    config = {
        "post_scan": {
            "integrity": True,
            "detectors": ["regex", "ner"],
            "ner_model": "en_core_web_lg",
        }
    }
    with pytest.raises(ModelUnavailableError) as refused:
        post_scan_detectors(config)
    assert refused.value.reason == UNCALIBRATED


def test_pre_scan_refuses_before_the_first_table_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def read(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a table was read before the model was refused")

    # `_scan_one` is the per-table read: loading the models after it turns this red (MM-7).
    monkeypatch.setattr(scan_set, "_scan_one", read)
    monkeypatch.setattr(ner, "iter_ner_spans_batch", read)
    monkeypatch.setattr(ner, "_pipeline", read)
    pre_scan = PreScanConfig(detectors=("regex", "ner"), ner_model="en_core_web_lg")
    with pytest.raises(ModelUnavailableError) as refused:
        scan_sources(s.source(tmp_path, "customers", s.customers()), pre_scan=pre_scan)
    assert refused.value.reason == UNCALIBRATED


def test_every_calibrated_model_has_a_pinned_wheel_and_the_reverse() -> None:
    """The rate table and the wheel table name the same models (one cannot drift from the other)."""
    wheel_models = {model for model, _version in NER_MODEL_WHEELS}
    assert wheel_models == set(NER_MIN_RATES)


@needs_ner
@pytest.mark.parametrize("name", UNCALIBRATED_NAMES)
def test_text_redact_is_not_refused_for_the_same_name(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = make_fake_model(tmp_path, name)
    monkeypatch.syspath_prepend(str(tmp_path))
    config = {
        "tables": [
            {
                "name": "p",
                "columns": [
                    {
                        "name": "n",
                        "strategy": "text_redact",
                        "provider_config": {"ner": {"model": fake}},
                    }
                ],
            }
        ]
    }
    check_text_redact_ner_available(config)  # does not raise
