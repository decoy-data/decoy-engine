"""AT-M3a, the record half: `scan-set/v1` gains `model_hits` and `detectors` without breaking old
records, and the new models are strict.

Mutations: M-M3a3 (make `model_hits` required), M-M3a4 (widen `ModelHitCore.rate_bucket` to `str`),
M-M3a5 (replace the detector-run tagged union with independent source and nullable-model fields).
The model-on half is `test_scanml_m3a_pass.py`.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from decoy_engine.detection import DetectorRun, ModelRef
from decoy_engine.profiling import (
    ModelHit,
    ScanSetCore,
    ScanSetCoreRead,
    scan_set_to_dict,
    scan_sources,
)
from decoy_engine.profiling.scan_set import ModelHitCore, ModelRefCore, _DetectorRunCore
from tests.unit.profiling import _scanml_m3a_support as s

MODEL = {"id": "lgbm-v1", "version": "0.1.0"}
HIT = {
    "source": "classifier",
    "detector_id": "email",
    "model": MODEL,
    "band": "high",
    "rate_bucket": None,
}
CLASSIFIER_RUN = {"source": "classifier", "model": MODEL}


def _scan(tmp_path: Path, **kw: Any) -> Any:
    return scan_sources(s.source(tmp_path, "t", s.customers()), **kw)


def _legacy(doc: dict[str, Any]) -> dict[str, Any]:
    """The dict as a pre-M3a writer produced it."""
    old = copy.deepcopy(doc)
    old.pop("detectors")
    for table in old["tables"]:
        for field in table["fields"]:
            field.pop("model_hits")
    return old


def test_no_pre_scan_lists_regex_only_and_no_hits(tmp_path: Path) -> None:
    scan = _scan(tmp_path)
    assert scan.detectors == (DetectorRun("regex", None),)
    assert all(t.model_hits == {} for t in scan.tables)
    doc = scan_set_to_dict(scan, detail=False)
    assert doc["detectors"] == [{"source": "regex", "model": None}]
    assert all(f["model_hits"] == [] for t in doc["tables"] for f in t["fields"])


def test_a_regex_only_pre_scan_equals_no_pre_scan(tmp_path: Path) -> None:
    sources = s.source(tmp_path, "t", s.customers())
    plain = scan_set_to_dict(scan_sources(sources), detail=False)
    asked = scan_set_to_dict(scan_sources(sources, pre_scan=s.pre_scan()), detail=False)
    assert {**asked, "scanned_at": ""} == {**plain, "scanned_at": ""}


def test_a_record_without_the_new_keys_validates_and_reads_back_empty(tmp_path: Path) -> None:
    old = _legacy(scan_set_to_dict(_scan(tmp_path), detail=False))
    for model in (ScanSetCore, ScanSetCoreRead):
        loaded = model.model_validate(old)
        assert loaded.detectors == []
        assert all(f.model_hits == [] for t in loaded.tables for f in t.fields)


def test_a_newer_record_with_an_unknown_key_reads_but_does_not_write(tmp_path: Path) -> None:
    doc = scan_set_to_dict(_scan(tmp_path), detail=False)
    doc["tables"][0]["fields"][0]["model_hits"] = [{**HIT, "extra": 1}]
    ScanSetCoreRead.model_validate(doc)
    with pytest.raises(ValidationError):
        ScanSetCore.model_validate(doc)


def test_the_new_keys_are_additive_parts_of_the_core(tmp_path: Path) -> None:
    doc = scan_set_to_dict(_scan(tmp_path), detail=False)
    assert set(doc) - set(_legacy(doc)) == {"detectors"}
    field = doc["tables"][0]["fields"][0]
    assert "model_hits" in field


@pytest.mark.parametrize(
    "hit",
    [
        {**HIT, "model": None},
        {k: v for k, v in HIT.items() if k != "model"},
        {**HIT, "source": "regex"},
        {**HIT, "source": "llm"},
        {**HIT, "band": "low"},
        {**HIT, "band": "medium"},
        {**HIT, "rate_bucket": "75%"},
        {**HIT, "rate_bucket": "10-50"},
        {**HIT, "detector_id": 7},
        {**HIT, "model": {"id": "lgbm-v1", "version": 1}},
        {**HIT, "model": {**MODEL, "path": "/x"}},
    ],
    ids=lambda h: repr(h)[:60],
)
def test_a_model_hit_refuses_what_is_not_a_hit(hit: dict[str, Any], tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        ModelHitCore.model_validate(hit)
    doc = scan_set_to_dict(_scan(tmp_path), detail=False)
    doc["tables"][0]["fields"][0]["model_hits"] = [hit]
    for model in (ScanSetCore, ScanSetCoreRead):
        if "extra" in str(hit) or "path" in str(hit):
            continue  # an unknown key is refused to write and ignored to read, by design
        with pytest.raises(ValidationError):
            model.model_validate(doc)


@pytest.mark.parametrize(
    "run",
    [
        {"source": "regex", "model": MODEL},
        {"source": "classifier", "model": None},
        {"source": "ner", "model": None},
        {"source": "classifier"},
        {"source": "regex"},
        {"source": "llm", "model": MODEL},
        {"source": "ner", "model": {"id": 3, "version": "1"}},
    ],
    ids=lambda r: repr(r),
)
def test_a_detector_run_refuses_a_regex_run_with_a_model_or_a_model_run_without(
    run: dict[str, Any], tmp_path: Path
) -> None:
    doc = scan_set_to_dict(_scan(tmp_path), detail=False)
    doc["detectors"] = [{"source": "regex", "model": None}, run]
    for model in (ScanSetCore, ScanSetCoreRead):
        with pytest.raises(ValidationError):
            model.model_validate(doc)


def test_a_hit_and_a_run_validate_in_both_forms(tmp_path: Path) -> None:
    doc = scan_set_to_dict(_scan(tmp_path), detail=False)
    doc["detectors"] = [{"source": "regex", "model": None}, CLASSIFIER_RUN]
    doc["tables"][0]["fields"][1]["model_hits"] = [HIT]
    for model in (ScanSetCore, ScanSetCoreRead):
        loaded = model.model_validate(doc)
        assert [d.source for d in loaded.detectors] == ["regex", "classifier"]
        assert loaded.tables[0].fields[1].model_hits[0].detector_id == "email"


def test_the_stored_forms_are_the_strict_core_types() -> None:
    ModelRefCore.model_validate(MODEL)
    assert ModelHitCore.model_validate(HIT).band == "high"
    assert _DetectorRunCore is not None
    with pytest.raises(ValidationError):
        ModelRefCore.model_validate({"id": "x", "version": "1", "path": "/x"})


def test_a_model_hit_is_value_free_by_construction() -> None:
    hit = ModelHit("ner", "person_name", ModelRef("en_core_web_sm", "3.8.0"), None, "10-50%")
    assert set(vars(hit)) == {"source", "detector_id", "model", "band", "rate_bucket"}
