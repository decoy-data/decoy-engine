"""AT-M3c: the canary corpus through the pre-scan with every detector on.

The cells hold a canary person name spaCy tags as PERSON, a canary token and a canary email. The
test first proves the markers are in the input and that the pass made a hit and wrote its log
records, then proves no marker reached a log record, the engine log file or a scan-set dict.
Mutation M-M3c: put the first span text in the `pre_scan.models` event.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
import pytest

from decoy_engine.profiling import scan_set_to_dict, scan_sources
from tests._ml import require_ml_stack
from tests._ner import needs_ner
from tests.unit.detection_verification import _scanml_m4_support as m4
from tests.unit.detection_verification.test_scanml_m4_canary import _EngineLogFile
from tests.unit.profiling import _scanml_m3a_support as s

pytestmark = pytest.mark.ml

require_ml_stack()


@pytest.fixture(autouse=True)
def _enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DECOY_ML_DISABLED", raising=False)


@needs_ner
def test_the_pre_scan_leaves_no_canary_anywhere(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    notes = m4.canary_notes()
    emails = [m4.CANARY_EMAIL if i % 3 == 0 else f"user{i}(at)x.com" for i in range(len(notes))]
    frame = pd.DataFrame({"notes": notes, "email": emails})
    text = "\n".join(list(frame["notes"]) + list(frame["email"]))
    for marker in m4.CANARIES:
        assert marker in text, marker
    sources = s.source(tmp_path, "t", frame)
    with _EngineLogFile(tmp_path) as log, caplog.at_level(logging.DEBUG):
        scan = scan_sources(sources, pre_scan=s.pre_scan("classifier", "ner"))
    # The pass made a hit of each kind and logged both of its records.
    kinds = {h.source for t in scan.tables for hs in t.model_hits.values() for h in hs}
    assert kinds == {"classifier", "ner"}, kinds
    lines = [r.getMessage() for r in caplog.records if r.name == s.DETECTOR_LOGGER]
    assert any(line.startswith("pre_scan.detectors ") for line in lines), lines
    assert any(line.startswith("pre_scan.models ") for line in lines), lines
    everything = {
        "records": "\n".join(f"{r.name} {r.getMessage()}" for r in caplog.records),
        "log file": log.text(),
        "scan set": json.dumps(scan_set_to_dict(scan, detail=False)),
        "hits": repr([t.model_hits for t in scan.tables]),
    }
    for where, shown in everything.items():
        for marker in m4.CANARIES:
            assert marker not in shown, (where, marker)
