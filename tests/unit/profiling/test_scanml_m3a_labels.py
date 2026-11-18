"""AT-M3d: the classifier's labels and the labels the scan maps never drift apart.

`CLASSIFIER_LABELS` is derived from the descriptors' `classifier_label` markers, so a new pack
label with no marker fails here instead of silently dropping its hits.
Mutation M-M3d: remove the marker from the `npi` descriptor.
"""

from __future__ import annotations

import pytest

from decoy_engine.detection.ner import NER_ENTITY_MAP
from decoy_engine.profiling import DEFAULT_STRATEGY_BY_DETECTOR, DETECTOR_DESCRIPTORS
from decoy_engine.profiling import recommendations as rec
from tests._ml import require_ml_stack

NONE = "none"


@pytest.mark.ml
def test_the_pack_classes_are_the_marked_labels_plus_none(monkeypatch: pytest.MonkeyPatch) -> None:
    require_ml_stack()
    monkeypatch.delenv("DECOY_ML_DISABLED", raising=False)
    from decoy_engine import load_detectors

    pack = load_detectors(("regex", "classifier"), ner_model="en_core_web_sm").classifier_pack
    assert pack is not None
    assert {str(c) for c in pack["clf"].classes_} == rec.CLASSIFIER_LABELS | {NONE}


def test_every_label_maps_to_a_known_detector_with_a_default_entry() -> None:
    assert rec.CLASSIFIER_LABELS, "no descriptor carries a classifier label"
    for label in rec.CLASSIFIER_LABELS:
        detector_id = rec.classifier_detector_id(label)
        assert detector_id in DETECTOR_DESCRIPTORS, label
        assert detector_id in DEFAULT_STRATEGY_BY_DETECTOR, label
    assert rec.classifier_detector_id(NONE) is None
    assert rec.classifier_detector_id("not_a_label") is None


def test_the_labels_come_from_the_descriptors_alone() -> None:
    marked = {d.classifier_label for d in DETECTOR_DESCRIPTORS.values() if d.classifier_label}
    assert marked == rec.CLASSIFIER_LABELS


def test_the_ner_labels_map_through_the_one_table() -> None:
    assert set(NER_ENTITY_MAP.values()) == {"person_name", "location"}
    assert NER_ENTITY_MAP["PERSON"] == NER_ENTITY_MAP["PER"] == "person_name"
    assert {NER_ENTITY_MAP[k] for k in ("GPE", "LOC", "FAC")} == {"location"}


def test_the_classifier_labels_are_not_exported() -> None:
    import decoy_engine
    import decoy_engine.profiling as profiling

    assert "CLASSIFIER_LABELS" not in dir(decoy_engine)
    assert "CLASSIFIER_LABELS" not in profiling.__all__
