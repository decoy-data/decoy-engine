"""M-1 (row 32c): the per-model NER hit rate for en_core_web_md and the md wheel pin.

M-T2 recomputes the md rule over the calibration corpus plus the clinical negatives and asserts it
equals `NER_MIN_RATES["en_core_web_md"]`. M-T3 checks the md rate catches a notes column where one
cell in four or five names a person and clears the held-out negatives; it is a stop condition, so a
failure goes back to the owner and the rate is not tuned. M-T4 and M-T6 need no scoring.

Mutations: MM-2 (md shares sm's threshold), MM-3 (md uses 0.211), MM-4 (`NerRate.hit` reads the
global constant), MM-6 (the wheel row carries the wrong spaCy range).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.detection import _ner_rate as nr
from decoy_engine.detection.detectors import Span
from decoy_engine.detection.ner import (
    NER_ENTITY_MAP,
    NER_MODEL_WHEELS,
    installed_model_version,
)
from tests._ner import needs_model
from tests.unit.detection_verification import _ner_clinical_corpus as cc
from tests.unit.detection_verification import _ner_corpus as nc
from tests.unit.detection_verification.test_ner_free_text_scope import _notes_column
from tests.unit.detection_verification.test_ner_min_rate import (
    ceil_to_thousandth,
    clopper_pearson_upper,
)

MD = "en_core_web_md"
SM = "en_core_web_sm"
MD_WHEEL_SHA256 = "5e6329fe3fecedb1d1a02c3ea2172ee0fede6cea6e4aefb6a02d832dba78a310"
# The md rule must stay under the 1-in-4 realistic-name notes column's measured rate (0.2005 in the
# 2026-11-07 comparison), or md would miss the column it was chosen to catch.
STOP_VALUE = 0.2005


def test_sm_keeps_its_accepted_rate_and_md_has_its_own() -> None:
    assert nr.NER_MIN_RATES[SM] == 0.211
    assert MD in nr.NER_MIN_RATES
    assert 0 < nr.NER_MIN_RATES[MD] < nr.NER_MIN_RATES[SM]
    assert nr.NER_MIN_RATES[SM] == nr.NER_MIN_RATE


@needs_model(MD)
def test_the_md_rate_is_the_calibrated_threshold() -> None:
    table = []
    for column in (*nc.corpus(), *cc.corpus()):
        rates = nr.ner_rates(column.cells, model=MD)
        assert set(rates) == set(NER_ENTITY_MAP.values()), column.name
        for detector_id in sorted(column.negative_for):
            r = rates[detector_id]
            assert r.scanned_cells == nc.N, (column.name, "was not scored as free text")
            table.append(
                {
                    "column": column.name,
                    "detector_id": detector_id,
                    "hits": r.hit_cells,
                    "cells": r.scanned_cells,
                    "rate": r.rate,
                    "upper_95": clopper_pearson_upper(r.hit_cells, r.scanned_cells),
                }
            )
    highest_rate = max(row["rate"] for row in table)
    highest_upper_95 = max(row["upper_95"] for row in table)
    threshold = max(2 * highest_rate, highest_upper_95, 0.01)
    expected = ceil_to_thousandth(threshold)
    evidence = {
        "rows": table,
        "2x_highest_rate": 2 * highest_rate,
        "highest_upper_95": highest_upper_95,
        "threshold": threshold,
        "NER_MIN_RATES[md]": expected,
    }
    path = os.environ.get("DECOY_NER_RATE_EVIDENCE")
    if path:
        Path(path).write_text(json.dumps(evidence, indent=1))
    print(json.dumps(evidence, indent=1))
    assert expected <= STOP_VALUE, f"above the stop value: report it, do not tune\n{evidence}"
    assert expected == nr.NER_MIN_RATES[MD]


@needs_model(MD)
@pytest.mark.parametrize("every", [4, 5])
def test_md_flags_a_notes_column_where_one_cell_in_four_or_five_names_a_person(
    every: int,
) -> None:
    rate = nr.ner_rates(_notes_column(every), model=MD)["person_name"]
    assert rate.scanned_cells == 400
    assert rate.hit, rate
    assert rate.min_rate == nr.NER_MIN_RATES[MD]
    print(f"md 1-in-{every} person_name rate", rate.rate, rate.hit_cells)


@needs_model(MD)
def test_no_held_out_column_is_a_hit_for_md() -> None:
    for column in nc.held_out_corpus():
        rates = nr.ner_rates(column.cells, model=MD)
        for detector_id in column.negative_for:
            r = rates[detector_id]
            assert r.scanned_cells == nc.HELD_OUT_N, column.name
            assert not r.hit, (column.name, detector_id, r.rate)
            print("md", column.name, detector_id, r.hit_cells, r.scanned_cells, r.rate)


def _spans(texts: Any, **_k: Any) -> list[list[Span]]:
    return [[Span("person_name", 0, 1, "X")] if t.startswith("P") else [] for t in texts]


def _cells(hits: int, total: int) -> list[str]:
    return [("P" if i < hits else "x") + " then one two" for i in range(total)]


def test_a_rate_between_the_md_and_sm_thresholds_is_a_hit_for_md_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(nr, "iter_ner_spans_batch", _spans)
    md_rate, sm_rate = nr.NER_MIN_RATES[MD], nr.NER_MIN_RATES[SM]
    hits = int(((md_rate + sm_rate) / 2) * 1000)
    assert md_rate < hits / 1000 < sm_rate
    md = nr.ner_rates(_cells(hits, 1000), model=MD)["person_name"]
    sm = nr.ner_rates(_cells(hits, 1000), model=SM)["person_name"]
    assert (md.min_rate, md.hit) == (md_rate, True)
    assert (sm.min_rate, sm.hit) == (sm_rate, False)


def test_md_decides_a_hit_exactly_at_its_own_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nr, "iter_ner_spans_batch", _spans)
    at = round(nr.NER_MIN_RATES[MD] * 1000)
    assert nr.ner_rates(_cells(at, 1000), model=MD)["person_name"].hit
    assert not nr.ner_rates(_cells(at - 1, 1000), model=MD)["person_name"].hit


def test_a_model_without_a_rate_is_not_scored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nr, "iter_ner_spans_batch", _spans)
    with pytest.raises(ValueError, match="calibrated"):
        nr.ner_rates(_cells(5, 10), model="en_core_web_lg")


def test_the_md_wheel_row_is_pinned() -> None:
    wheel = NER_MODEL_WHEELS[(MD, "3.8.0")]
    assert wheel.sha256 == MD_WHEEL_SHA256
    assert wheel.spacy_range == ">=3.8.0,<3.9.0"
    assert (SM, "3.8.0") in NER_MODEL_WHEELS


@needs_model(MD)
def test_the_md_wheel_row_matches_the_installed_wheels_meta_json() -> None:
    import importlib

    meta = json.loads(
        (Path(importlib.import_module(MD).__file__ or "").parent / "meta.json").read_text()
    )
    wheel = NER_MODEL_WHEELS[(MD, meta["version"])]
    assert installed_model_version(MD) == meta["version"]
    assert wheel.spacy_range == meta["spacy_version"]
