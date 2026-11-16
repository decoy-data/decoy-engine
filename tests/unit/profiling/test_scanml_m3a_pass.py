"""AT-M3a (model-on half), AT-M3b, AT-M3f and AT-M3g: the pre-scan model pass on the real classifier
pack and, where marked, the real spaCy model.

Mutations: M-M3a (run the classifier by default), M-M3a2 (turn a `high` classifier hit into a config
entry), M-M3b2 (score with `iter_ner_spans_batch` directly instead of `ner_rates`), M-M3f (call
`spacy.cli.download` when the model is missing), M-M3g (classify the full sample).
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from decoy_engine.config import PreScanConfig
from decoy_engine.detection import DetectorRun, ModelRef, ModelUnavailableError, ner
from decoy_engine.profiling import scan_set_to_dict, scan_sources, starter_config
from tests._ml import require_ml_stack
from tests._ner import needs_ner
from tests.unit.detection_verification import _scanml_m4_support as m4
from tests.unit.profiling import _scanml_m3a_support as s

pytestmark = pytest.mark.ml

require_ml_stack()

from decoy_engine.profiling.features import builder  # noqa: E402

PACK = Path(__file__).resolve().parents[3] / "docs" / "v2" / "ml" / "packs" / "lgbm-v1"


@pytest.fixture(autouse=True)
def _enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DECOY_ML_DISABLED", raising=False)


def _classifier_ref() -> ModelRef:
    manifest = json.loads((PACK / "manifest.json").read_text())
    return ModelRef(manifest["pack_id"], manifest["version"])


def _ner_ref() -> ModelRef:
    version = ner.installed_model_version()
    assert version is not None
    return ModelRef(ner.DEFAULT_NER_MODEL, version)


def _tuple(hit: Any) -> tuple[Any, ...]:
    return (hit.source, hit.detector_id, hit.model, hit.band, hit.rate_bucket)


def test_the_classifier_labels_a_column_the_regex_misses(tmp_path: Path) -> None:
    sources = s.source(tmp_path, "customers", s.customers())
    scan = scan_sources(sources, pre_scan=s.pre_scan("classifier"))
    (hit,) = s.hits(scan, "customers", "email")
    assert (hit.source, hit.detector_id, hit.model) == ("classifier", "email", _classifier_ref())
    assert hit.band in ("high", "review") and hit.rate_bucket is None
    field = next(f for f in scan.tables[0].profile.fields if f.name == "email")
    assert not field.detector_matches, "the regex was meant to miss this column"
    assert s.hits(scan, "customers", "notes") == ()


def test_detectors_name_each_source_with_its_model(tmp_path: Path) -> None:
    scan = scan_sources(
        s.source(tmp_path, "customers", s.customers()), pre_scan=s.pre_scan("classifier")
    )
    assert scan.detectors == (DetectorRun("regex", None), DetectorRun("classifier", _classifier_ref()))
    doc = scan_set_to_dict(scan, detail=False)
    ref = _classifier_ref()
    assert doc["detectors"] == [
        {"source": "regex", "model": None},
        {"source": "classifier", "model": {"id": ref.id, "version": ref.version}},
    ]
    email = next(f for f in doc["tables"][0]["fields"] if f["name"] == "email")
    assert [(h["source"], h["detector_id"]) for h in email["model_hits"]] == [("classifier", "email")]
    assert set(email["model_hits"][0]) == {"source", "detector_id", "model", "band", "rate_bucket"}


def test_a_scan_without_pre_scan_runs_no_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # M-M3a: running the classifier by default would reach this.
    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a model ran without pre_scan")

    monkeypatch.setattr(builder, "build_column_features", boom)
    scan = scan_sources(s.source(tmp_path, "customers", s.customers()))
    assert all(t.model_hits == {} for t in scan.tables)


def test_the_starter_config_ignores_model_hits(tmp_path: Path) -> None:
    # M-M3a2: a `high` classifier hit turned into an entry changes this config.
    sources = s.source(tmp_path, "customers", s.customers())
    plain = starter_config(scan_sources(sources))
    with_models = scan_sources(sources, pre_scan=s.pre_scan("classifier"))
    assert s.hits(with_models, "customers", "email"), "the pass produced no hit to ignore"
    got = starter_config(with_models)
    assert got.config == plain.config
    assert got.notes == plain.notes
    assert got.suggestions == plain.suggestions


@needs_ner
def test_the_starter_config_ignores_every_detector_at_once(tmp_path: Path) -> None:
    sources = s.source(tmp_path, "customers", s.customers())
    plain = starter_config(scan_sources(sources))
    everything = scan_sources(sources, pre_scan=s.pre_scan("classifier", "ner"))
    assert s.hits(everything, "customers", "notes"), "the pass produced no NER hit to ignore"
    got = starter_config(everything)
    assert (got.config, got.notes, got.suggestions) == (
        plain.config,
        plain.notes,
        plain.suggestions,
    )


@needs_ner
def test_ner_flags_the_notes_column_and_not_the_short_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = s.customers()
    spy = m4.spy_pipeline(monkeypatch)
    scan = scan_sources(s.source(tmp_path, "customers", frame), pre_scan=s.pre_scan("ner"))
    ner_ref = _ner_ref()
    (hit,) = [h for h in s.hits(scan, "customers", "notes") if h.detector_id == "person_name"]
    assert (hit.source, hit.model, hit.band) == ("ner", ner_ref, None)
    assert hit.rate_bucket == "10-50%"
    assert s.hits(scan, "customers", "names") == ()
    assert scan.detectors == (DetectorRun("regex", None), DetectorRun("ner", ner_ref))
    # A bare-name column is not free text: none of its cells reaches the pipeline.
    assert spy.texts, "the notes column never reached the pipeline"
    assert not set(frame["names"]) & set(spy.texts)
    doc = scan_set_to_dict(scan, detail=False)
    notes = next(f for f in doc["tables"][0]["fields"] if f["name"] == "notes")
    assert any(
        h["source"] == "ner" and h["detector_id"] == "person_name" and h["rate_bucket"] == "10-50%"
        for h in notes["model_hits"]
    )


@needs_ner
def test_every_detector_on_completes_with_sockets_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the scan opened a socket")

    for name in ("connect", "connect_ex", "bind", "sendto"):
        monkeypatch.setattr(socket.socket, name, refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    scan = scan_sources(
        s.source(tmp_path, "customers", s.customers()), pre_scan=s.pre_scan("classifier", "ner")
    )
    assert s.hits(scan, "customers", "email") and s.hits(scan, "customers", "notes")


@needs_ner
def test_a_missing_model_is_refused_and_never_downloaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import spacy.cli

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the scan tried to download a model")

    monkeypatch.setattr(spacy.cli, "download", refuse)
    monkeypatch.setattr(ner, "installed_model_version", lambda *_a, **_k: None)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    with pytest.raises(ModelUnavailableError) as info:
        scan_sources(s.source(tmp_path, "customers", s.customers()), pre_scan=s.pre_scan("ner"))
    assert info.value.reason == "provider.ner_model_not_installed"


def _tiled_scan(tmp_path: Path, rows: int, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[int]]:
    base = pd.DataFrame(
        {
            "id": range(60),
            "email": s.obfuscated_emails(60),
            "ssn": [f"{100 + i:03d}-{10 + i % 80:02d}-{1000 + i:04d}" for i in range(60)],
        }
    )
    frame = pd.concat([base] * (rows // 60 + 1), ignore_index=True).head(rows)
    lengths: list[int] = []
    real = builder.build_column_features

    def measured(series: Any, name: str, *a: Any, **k: Any) -> Any:
        lengths.append(len(series))
        return real(series, name, *a, **k)

    monkeypatch.setattr(builder, "build_column_features", measured)
    scan = scan_sources(s.source(tmp_path, "t", frame), pre_scan=s.pre_scan("classifier"))
    return scan, lengths


def test_a_tiled_fixture_gets_the_labels_of_its_60_row_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    small, small_lengths = _tiled_scan(tmp_path / "a", 60, monkeypatch)
    big, big_lengths = _tiled_scan(tmp_path / "b", 10_000, monkeypatch)
    assert {t.name: t.model_hits for t in small.tables} == {t.name: t.model_hits for t in big.tables}
    assert s.hits(big, "t", "ssn"), "no hit to compare"
    assert max(small_lengths) == 60
    assert max(big_lengths) == 60, big_lengths  # M-M3g: the full sample would read 10,000
