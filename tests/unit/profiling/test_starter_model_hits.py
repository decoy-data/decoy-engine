"""INIT-SCAN-SCAFFOLD E2: `starter_config` reads model hits and refuses a header-suspect scan.

Model hits are built directly (`TableScan.model_hits`), the way a scan with `--detectors` leaves
them, so no model has to load. The last section is E2 step 0: the cells of the CLI's
`test_init_inference.py` that the engine starter tests did not hold yet (hostile names, date
format, review wording), so the CLI test can go later.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from decoy_engine import reasons
from decoy_engine.config import PipelineConfigError
from decoy_engine.detection.types import DetectorMatch, ModelRef
from decoy_engine.profiling import recommendations, scan_sources
from decoy_engine.profiling._model_pass import ModelHit
from decoy_engine.profiling._starter_config import (
    ColumnSuggestion,
    StarterConfig,
    check_starter_config,
    detector_entry,
    starter_config,
)
from decoy_engine.profiling._starter_inference import (
    _AMBIGUOUS_TEMPLATE,
    _FALLBACK,
    confident_matches,
    infer_starter_strategy,
)
from decoy_engine.profiling.scan_set import ScanSet

MARKER = "MARKER-7f3a"
LGBM = ModelRef("lgbm-v1", "0.1.0")
SPACY = ModelRef("en_core_web_sm", "3.8.0")
COLUMN = "c"


def _cell(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def _scan(tmp_path: Path, columns: dict[str, list[str]], *, table: str = "t") -> ScanSet:
    rows = len(next(iter(columns.values())))
    lines = [",".join(_cell(n) for n in columns)]
    lines += [",".join(_cell(columns[n][i]) for n in columns) for i in range(rows)]
    path = tmp_path / f"{table}.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    source = {"type": "file", "format": "csv", "path": str(path), "has_header": True}
    return scan_sources({table: source})


def _plain(tmp_path: Path) -> ScanSet:
    return _scan(tmp_path, {COLUMN: [f"word{i}" for i in range(20)]})


def _patched(
    scan: ScanSet,
    *,
    matches: list[DetectorMatch] | None = None,
    hits: tuple[ModelHit, ...] = (),
    warnings: tuple[Any, ...] = (),
    column: str = COLUMN,
) -> ScanSet:
    """`scan` with `matches` on `column`'s stats, `hits` as its model hits, extra warnings."""
    table = scan.tables[0]
    fields = [
        dataclasses.replace(f, detector_matches=matches)
        if matches is not None and f.name == column
        else f
        for f in table.profile.fields
    ]
    model_hits = {**table.model_hits, **({column: hits} if hits else {})}
    patched = dataclasses.replace(
        table,
        profile=dataclasses.replace(table.profile, fields=fields),
        model_hits=model_hits,
        warnings=(*table.warnings, *warnings),
    )
    return dataclasses.replace(scan, tables=(patched, *scan.tables[1:]))


def _classifier(detector_id: str, band: str = "high") -> ModelHit:
    return ModelHit("classifier", detector_id, LGBM, band, None)  # type: ignore[arg-type]


def _ner(detector_id: str, bucket: str = ">=50%") -> ModelHit:
    return ModelHit("ner", detector_id, SPACY, None, bucket)  # type: ignore[arg-type]


def _suggestion(result: StarterConfig, column: str = COLUMN) -> ColumnSuggestion:
    return next(s for s in result.suggestions if s.column == column)


def _entry_of(result: StarterConfig, column: str = COLUMN) -> dict[str, Any]:
    columns = result.config["tables"][0]["columns"]
    return next(c for c in columns if c["name"] == column)


def _note(result: StarterConfig, column: str = COLUMN) -> str:
    return result.notes[(result.config["tables"][0]["name"], column)]


# --- AT-E2a .. AT-E2e: the decision rules -------------------------------------------------------


def test_at_e2a_a_high_classifier_hit_writes_the_hit_detectors_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The hit id is already mapped by the model pass; mapping it again would pick another entry.
    monkeypatch.setattr(recommendations, "classifier_detector_id", lambda label: "us_phone")
    result = starter_config(_patched(_plain(tmp_path), hits=(_classifier("email"),)))
    assert _entry_of(result) == detector_entry("email", COLUMN)
    found = _suggestion(result)
    assert (found.source, found.band, found.model, found.live) == (
        "classifier",
        "high",
        LGBM,
        False,
    )
    assert found.detector_id == "email"
    assert "classifier lgbm-v1 0.1.0: email (band high)" in _note(result)


def test_at_e2b_a_review_band_hit_changes_no_entry_and_is_named(tmp_path: Path) -> None:
    result = starter_config(_patched(_plain(tmp_path), hits=(_classifier("email", "review"),)))
    assert _entry_of(result) == {"name": COLUMN, "strategy": "redact"}
    assert _suggestion(result).source == "regex"
    assert "classifier lgbm-v1 0.1.0: email (band review)" in _note(result)


def test_at_e2c_a_confident_regex_match_beats_a_model_hit(tmp_path: Path) -> None:
    match = DetectorMatch(detector_id="email", match_rate=0.95)
    scan = _patched(_plain(tmp_path), matches=[match], hits=(_classifier("person_name"),))
    result = starter_config(scan)
    assert _entry_of(result) == detector_entry("email", COLUMN)
    assert _suggestion(result).source == "regex"
    note = _note(result)
    assert "person_name" in note
    assert "regex says email" in note
    assert "regex kept" in note


def test_at_e2c_a_model_hit_that_agrees_does_not_claim_a_conflict(tmp_path: Path) -> None:
    match = DetectorMatch(detector_id="email", match_rate=0.95)
    result = starter_config(
        _patched(_plain(tmp_path), matches=[match], hits=(_classifier("email"),))
    )
    assert "classifier lgbm-v1 0.1.0: email (band high)" in _note(result)
    assert "regex kept" not in _note(result)


def test_at_e2d_an_ner_hit_adds_evidence_and_never_an_entry(tmp_path: Path) -> None:
    result = starter_config(_patched(_plain(tmp_path), hits=(_ner("person_name"),)))
    assert _entry_of(result) == {"name": COLUMN, "strategy": "redact"}
    assert _suggestion(result).source == "regex"
    assert "ner en_core_web_sm 3.8.0: person_name (rate >=50%)" in _note(result)


def test_at_e2e_a_date_hit_without_a_complete_format_writes_redact(tmp_path: Path) -> None:
    control = starter_config(_patched(_plain(tmp_path), hits=(_classifier("email"),)))
    assert _entry_of(control)["strategy"] == "faker"
    result = starter_config(_patched(_plain(tmp_path), hits=(_classifier("iso_date"),)))
    assert _entry_of(result) == {"name": COLUMN, "strategy": "redact"}
    assert "classifier lgbm-v1 0.1.0: iso_date (band high)" in _note(result)


def test_a_date_hit_takes_the_complete_format_a_weak_regex_match_found(tmp_path: Path) -> None:
    weak = DetectorMatch(
        detector_id="iso_date",
        match_rate=0.3,
        format_pattern="%Y-%m-%d",
        format_pattern_complete=True,
    )
    result = starter_config(
        _patched(_plain(tmp_path), matches=[weak], hits=(_classifier("iso_date"),))
    )
    assert _entry_of(result) == detector_entry("iso_date", COLUMN, date_format="%Y-%m-%d")
    assert _entry_of(result)["strategy"] == "date_shift"
    assert _suggestion(result).source == "classifier"


def test_the_first_high_classifier_hit_wins_and_every_hit_is_named(tmp_path: Path) -> None:
    hits = (_classifier("us_phone"), _classifier("email"), _ner("person_name"))
    result = starter_config(_patched(_plain(tmp_path), hits=hits))
    assert _entry_of(result) == detector_entry("us_phone", COLUMN)
    note = _note(result)
    for part in ("us_phone (band high)", "email (band high)", "person_name (rate >=50%)"):
        assert part in note


# --- AT-E2i, AT-E2g: decided_by and live -------------------------------------------------------


def test_at_e2i_decided_by_names_the_rule_that_chose_each_entry(tmp_path: Path) -> None:
    mixed = DetectorMatch(detector_id="iso_date", match_rate=0.9)  # confident, no format
    ipv4 = DetectorMatch(detector_id="ipv4", match_rate=0.9)
    cols = {
        "mixed": [f"2024-01-{i:02d}" for i in range(1, 21)],
        "ip": [f"10.0.0.{i}" for i in range(1, 21)],
        "cvv": [f"word{i}" for i in range(20)],
        "num": [str(i) for i in range(1, 21)],
        "plain": [f"word{i}" for i in range(20)],
    }
    scan = _scan(tmp_path, cols)
    scan = _patched(scan, matches=[mixed], hits=(_classifier("email"),), column="mixed")
    scan = _patched(scan, matches=[ipv4], column="ip")
    scan = _patched(scan, hits=(_classifier("cvv"),), column="cvv")
    result = starter_config(scan)
    assert _entry_of(result, "mixed") == {"name": "mixed", "strategy": "redact"}
    assert _suggestion(result, "mixed").decided_by == "fallback"
    assert "email" in _note(result, "mixed")
    assert _entry_of(result, "ip")["strategy"] == "redact"
    assert _suggestion(result, "ip").decided_by == "regex"
    assert _entry_of(result, "cvv")["strategy"] == "redact"
    assert _suggestion(result, "cvv").decided_by == "classifier"
    assert _suggestion(result, "num").decided_by == "integer_key"
    assert _suggestion(result, "plain").decided_by == "fallback"


def test_at_e2i_a_declared_key_is_decided_by_the_declaration(tmp_path: Path) -> None:
    parent = _scan(tmp_path, {"id": [str(i) for i in range(1, 21)]}, table="p")
    child = _scan(tmp_path, {"pid": [str(i) for i in range(1, 21)]}, table="k")
    scan = dataclasses.replace(parent, tables=(*parent.tables, *child.tables))
    rel = {
        "parent": {"table": "p", "columns": ["id"]},
        "children": [{"table": "k", "columns": ["pid"]}],
        "orphan_policy": "warn",
    }
    result = starter_config(scan, relationships=[rel])
    assert {s.column: s.decided_by for s in result.suggestions} == {
        "id": "declared_key",
        "pid": "declared_key",
    }


def test_at_e2g_live_is_false_only_for_a_model_chosen_entry(tmp_path: Path) -> None:
    cols = {"model": ["a b c d"] * 20, "num": [str(i) for i in range(1, 21)], "plain": ["x"] * 20}
    scan = _patched(_scan(tmp_path, cols), hits=(_classifier("email"),), column="model")
    result = starter_config(scan)
    live = {s.column: s.live for s in result.suggestions}
    assert live == {"model": False, "num": True, "plain": True}
    configured = {c["name"] for c in result.config["tables"][0]["columns"]}
    assert configured == {s.column for s in result.suggestions}
    assert "written into the config" not in (ColumnSuggestion.__doc__ or "")


def test_confident_matches_is_the_one_rule_both_callers_use() -> None:
    weak = SimpleNamespace(detector_id="a", match_rate=0.2, confidence_bucket=None)
    strong = SimpleNamespace(detector_id="b", match_rate=0.6, confidence_bucket=None)
    bucketed = SimpleNamespace(detector_id="c", match_rate=0.1, confidence_bucket="high")
    stats = SimpleNamespace(detector_matches=[weak, strong, bucketed])
    assert [m.detector_id for m in confident_matches(stats)] == ["b", "c"]
    assert confident_matches(SimpleNamespace(detector_matches=None)) == []
    assert infer_starter_strategy(SimpleNamespace(detector_matches=[weak])) == _FALLBACK


# --- AT-E2f: no value reaches a note ------------------------------------------------------------


def test_at_e2f_a_model_hit_note_holds_ids_and_buckets_only(tmp_path: Path) -> None:
    scan = _scan(tmp_path, {COLUMN: [f"{MARKER} {i}" for i in range(20)]})
    hits = (_classifier("email"), _ner("person_name"))
    result = starter_config(_patched(scan, hits=hits))
    assert MARKER not in repr(result.config)
    assert MARKER not in repr(dict(result.notes))
    assert MARKER not in repr(result.suggestions)
    check_starter_config(result.config)


def test_a_model_id_cannot_split_a_note_across_lines(tmp_path: Path) -> None:
    hit = ModelHit("classifier", "email", ModelRef("evil\nid\x07", "1\r\n0"), "high", None)
    result = starter_config(_patched(_plain(tmp_path), hits=(hit,)))
    note = _note(result)
    assert "\n" not in note and "\r" not in note and "\x07" not in note


# --- AT-E2h: header-suspect refusal -------------------------------------------------------------


def test_at_e2h_a_header_suspect_table_is_refused_without_a_name(tmp_path: Path) -> None:
    scan = _scan(tmp_path, {MARKER: [f"{MARKER}{i}" for i in range(20)]}, table="MARKER_T")
    suspect = reasons.warning.SCAN_HEADER_SUSPECT.spec.ref
    with pytest.raises(PipelineConfigError) as raised:
        starter_config(_patched(scan, warnings=(suspect,), column=MARKER))
    err = raised.value
    code = str(reasons.config.STARTER_HEADER_SUSPECT)
    assert [(p.code, p.location) for p in err.problems] == [(code, "tables[0]")]
    assert err.problems[0].text == (
        "A scanned table looks like it has no header row; its column names may be data."
    )
    assert MARKER not in str(err)
    assert all(MARKER not in f"{p.code}{p.location}{p.text}" for p in err.problems)


def test_at_e2h_the_second_table_is_named_by_position(tmp_path: Path) -> None:
    first = _scan(tmp_path, {"a": ["x"] * 20}, table="one")
    second = _scan(tmp_path, {"b": ["y"] * 20}, table="two")
    suspect = reasons.warning.SCAN_HEADER_SUSPECT.spec.ref
    flagged = dataclasses.replace(second.tables[0], warnings=(suspect,))
    scan = dataclasses.replace(first, tables=(first.tables[0], flagged))
    with pytest.raises(PipelineConfigError) as raised:
        starter_config(scan)
    assert [p.location for p in raised.value.problems] == ["tables[1]"]


def test_a_scan_without_the_warning_is_not_refused(tmp_path: Path) -> None:
    scan = _plain(tmp_path)
    assert reasons.warning.SCAN_HEADER_SUSPECT.spec.ref not in scan.tables[0].warnings
    assert starter_config(scan).config["tables"]


# --- E2 step 0: cells ported from the CLI's test_init_inference.py ------------------------------


def test_hostile_column_names_scaffold_a_valid_config(tmp_path: Path) -> None:
    names = ["a: b # c", "-x", '"q"']
    scan = _scan(tmp_path, {n: [f"word{i}" for i in range(20)] for n in names})
    result = starter_config(scan)
    assert [c["name"] for c in result.config["tables"][0]["columns"]] == names
    assert {c for (_, c) in result.notes} == set(names)
    check_starter_config(result.config)


def test_a_complete_date_format_writes_date_shift_and_a_mixed_one_writes_redact(
    tmp_path: Path,
) -> None:
    iso = [f"2024-01-{i:02d}" for i in range(1, 21)]
    mixed = [f"2024-01-{i:02d}" if i % 2 else f"{i:02d}/01/2024" for i in range(1, 21)]
    result = starter_config(_scan(tmp_path, {"iso": iso, "mixed": mixed}))
    by_name = {c["name"]: c for c in result.config["tables"][0]["columns"]}
    assert by_name["iso"]["strategy"] == "date_shift"
    assert by_name["iso"]["provider_config"]["date_format"] == "%Y-%m-%d"
    assert by_name["mixed"]["strategy"] == "redact"


def test_every_starter_review_reads_as_the_scan_found_it() -> None:
    texts = [_FALLBACK.review, _AMBIGUOUS_TEMPLATE]
    texts += [
        choice.review
        for d in recommendations.DETECTOR_DESCRIPTORS
        if (choice := recommendations.starter_choice(d)) is not None
    ]
    assert len(texts) > 2
    assert all(t.startswith("The scan ") for t in texts)
