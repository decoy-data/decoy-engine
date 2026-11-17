"""The resume fingerprint carries the resolved NER model identity (SCAN-ML-MD A-12).

A caller that passes no engine version could otherwise resume an sm run with md after the default
flips. The engine adds one `decoy-ner:<surface>` pair per NER surface, so the fingerprint changes.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

import pytest

from decoy_engine.delivery.resume import (
    ResumeRefusedError,
    RunRecord,
    TableEntry,
    _fingerprint,
    build_fingerprint,
    plan_resume,
)
from decoy_engine.detection import ner

CALLER = (("example-caller", "1"),)
MARKER = "SEEDED_MARKER_21c4"


@dataclass
class _Provider:
    key_version: str = "v1"

    def mask_key(self) -> bytes:
        return bytes(range(32))


def _config(*, with_ner: bool = True) -> dict[str, Any]:
    config: dict[str, Any] = {
        "name": "p",
        "global_settings": {"seed": 7},
        "sources": {MARKER: {"path": "in/t.csv", "format": "csv"}},
        "targets": {MARKER: {"path": "out/t.csv", "format": "csv"}},
        "tables": [
            {
                "name": MARKER,
                "columns": [
                    {
                        "name": MARKER + "_col",
                        "strategy": "text_redact",
                        "provider_config": {"ner": with_ner},
                    }
                ],
            }
        ],
    }
    if with_ner:
        config["pre_scan"] = {"detectors": ["regex", "ner"]}
    return config


def _fp(config: dict[str, Any]) -> Any:
    return build_fingerprint(config, _Provider(), chunk_size=1000, components=CALLER)


@pytest.fixture
def versions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_fingerprint, "installed_model_version", lambda model="": "3.8.0")


def _stored(fingerprint: Any) -> RunRecord:
    entry = TableEntry(0, "sha256:" + "a" * 64, "sha256:" + "b" * 64)
    return RunRecord(
        run_id="20261116T101500123456Z-0a1b2c3d",
        invocation_id="0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
        operation_id="run-0a1b2c3d",
        route="chunked",
        fingerprint=fingerprint,
        tables=(entry,),
    )


def test_resume_across_the_default_flip_is_refused(
    monkeypatch: pytest.MonkeyPatch, versions: None
) -> None:
    monkeypatch.setattr(ner, "DEFAULT_NER_MODEL", "en_core_web_sm")
    before = _fp(_config())
    monkeypatch.setattr(ner, "DEFAULT_NER_MODEL", "en_core_web_md")
    after = _fp(_config())
    assert before.components != after.components
    with pytest.raises(ResumeRefusedError) as caught:
        plan_resume(_stored(before), after, _stored(before).tables, {})
    assert caught.value.code == "resume_fingerprint_changed"
    assert caught.value.field == "components"


def test_the_pairs_name_surfaces_and_models_only(versions: None) -> None:
    pairs = [p for p in _fp(_config()).components if p[0].startswith("decoy-ner:")]
    assert [p[0] for p in pairs] == ["decoy-ner:pre_scan", "decoy-ner:text_redact"]
    assert all(p[1].endswith("==3.8.0") for p in pairs)
    assert MARKER not in repr(pairs)


def test_a_model_that_is_not_installed_is_recorded_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_fingerprint, "installed_model_version", lambda model="": None)
    pairs = dict(_fp(_config()).components)
    assert pairs["decoy-ner:pre_scan"].endswith("==unavailable")


def test_several_models_in_one_surface_join_in_sorted_order(versions: None) -> None:
    config = _config(with_ner=False)
    columns = config["tables"][0]["columns"]
    for model in ("en_core_web_md", "en_core_web_lg"):
        columns.append(
            {"name": model, "strategy": "text_redact", "provider_config": {"ner": {"model": model}}}
        )
    pair = dict(_fp(config).components)["decoy-ner:text_redact"]
    assert pair == "en_core_web_lg==3.8.0,en_core_web_md==3.8.0"


def test_a_config_without_ner_adds_no_pair() -> None:
    plain = _config(with_ner=False)
    plain["tables"][0]["columns"][0]["provider_config"] = {}
    assert _fp(plain).components == CALLER


def test_a_caller_cannot_forge_the_reserved_prefix() -> None:
    forged = (*CALLER, ("decoy-ner:pre_scan", "x"))
    with pytest.raises(ValueError) as caught:
        build_fingerprint(copy.deepcopy(_config()), _Provider(), chunk_size=1, components=forged)
    assert "decoy-ner" not in str(caught.value) or MARKER not in str(caught.value)
