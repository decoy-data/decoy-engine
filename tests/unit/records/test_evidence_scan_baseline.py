"""SCAN-CHECKS B-1: the optional ``scan_baseline`` member of the ``cli-local-1`` evidence payload."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from decoy_engine import records
from decoy_engine.records import RecordError, canonical_bytes
from decoy_engine.records._payloads import EvidencePayload
from tests.unit.records._helpers import PRODUCER, T0, corpus, make, raw_of

SAMPLE = "evidence-cli-local-1-baseline.json"
OLD_SAMPLES = (
    "evidence-cli-local-1.json",
    "evidence-cli-local-1-legacy.json",
    "evidence-cli-local-1-project.json",
)


def test_b_t1_the_corpus_sample_decodes_and_keeps_its_bytes() -> None:
    manifest = corpus(SAMPLE)
    model = EvidencePayload.model_validate(manifest)
    assert model.scan_baseline is not None
    assert model.scan_baseline.fingerprint_method == "full"
    env = make("evidence", manifest, labels={})
    assert canonical_bytes(env.payload) == canonical_bytes(manifest)
    decoded = records.decode(records.encode(env))
    assert isinstance(decoded, records.DecodedRecord)
    assert decoded.raw["payload"]["scan_baseline"] == manifest["scan_baseline"]


@pytest.mark.parametrize("extra", [{"extra": 1}, {"fingerprint": "not-a-digest"}])
def test_b_t1_the_member_is_strict(extra: dict[str, Any]) -> None:
    manifest = deepcopy(corpus(SAMPLE))
    manifest["scan_baseline"].update(extra)
    with pytest.raises(ValidationError):
        EvidencePayload.model_validate(manifest)
    with pytest.raises(RecordError):
        make("evidence", manifest, labels={})


def test_b_t1_a_missing_baseline_records_a_null_fingerprint() -> None:
    manifest = deepcopy(corpus(SAMPLE))
    manifest["scan_baseline"].update(fingerprint=None, fingerprint_method=None, size_bytes=None)
    env = make("evidence", manifest, labels={})
    assert env.payload["scan_baseline"]["fingerprint"] is None


@pytest.mark.parametrize("name", OLD_SAMPLES)
def test_b_t2_a_manifest_without_the_member_dumps_without_the_key(name: str) -> None:
    manifest = corpus(name)
    assert "scan_baseline" not in manifest
    env = make("evidence", manifest, labels={})
    assert "scan_baseline" not in env.payload
    assert "scan_baseline" not in raw_of(env)["payload"]
    assert canonical_bytes(env.payload) == canonical_bytes(manifest)


def test_b_t2_the_member_is_not_defaulted_to_an_empty_object() -> None:
    assert EvidencePayload.model_fields["scan_baseline"].default is None


def test_a_default_export_withholds_the_machine_path_of_the_baseline() -> None:
    manifest = deepcopy(corpus(SAMPLE))
    manifest["scan_baseline"]["path"] = "/home/jane/work/baseline.json"
    rec = raw_of(make("evidence", manifest, labels={}))
    lines = list(records.export_lines([rec], producer=PRODUCER, exported_at=T0))
    text = b"".join(lines).decode()
    assert "/home/jane" not in text
    kept = b"".join(records.export_lines([rec], producer=PRODUCER, exported_at=T0, keep_paths=True))
    assert b"/home/jane/work/baseline.json" in kept
