"""`scan-diff/v1`: the drift rules, the table matching and the persisted document (F15-T1 to T3, T5)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import decoy_engine
from decoy_engine import profiling
from decoy_engine.profiling import (
    SCAN_DIFF_SCHEMA,
    ScanDiffCore,
    ScanDiffCoreRead,
    diff_scan_documents,
    diff_scan_tables,
    pii_bucket,
    scan_diff_to_dict,
)

CORPUS = Path(__file__).resolve().parents[2] / "integration" / "compat_corpus" / "scan_diff"
PAIRS: list[dict[str, Any]] = json.loads((CORPUS / "pairs.json").read_text(encoding="utf-8"))[
    "pairs"
]
CANARY = "CANARY-77d0b4"
UNKNOWN_KIND = "scan-diff document holds an unknown drift kind"
CHANGE_LISTS = (
    "added_rows",
    "removed_rows",
    "pii_increased",
    "pii_decreased",
    "qi_added",
    "qi_removed",
)


def _field(name: str, score: float | None = 0.1) -> dict[str, Any]:
    return {"name": name, "pii_score": score}


def _doc(tables: list[dict[str, Any]], version: str = "0.27.0", detectors: Any = None) -> dict:
    doc: dict[str, Any] = {"engine_version": version, "tables": tables}
    if detectors is not None:
        doc["detectors"] = detectors
    return doc


def _table(name: str, fields: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"name": name, "fields": fields, **extra}


def _as_corpus(diff: profiling.TableDiff) -> dict[str, Any]:
    """The table diff in the shape the CLI function's output was captured in."""
    return {
        "added_rows": [r.as_dict() for r in diff.added_rows],
        "removed_rows": [r.as_dict() for r in diff.removed_rows],
        "pii_increased": [r.as_dict() for r in diff.pii_increased],
        "pii_decreased": [r.as_dict() for r in diff.pii_decreased],
        "qi_added": [list(g) for g in diff.qi_added],
        "qi_removed": [list(g) for g in diff.qi_removed],
        "risk_delta": diff.risk_delta,
        "new_high_pii": [r.as_dict() for r in diff.new_high_pii],
        "drift": diff.drift,
    }


# ---------------------------------------------------------------------------
# F15-T1: the per-table rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pair", PAIRS, ids=lambda p: p["id"])
def test_parity_with_the_captured_cli_function(pair: dict[str, Any]) -> None:
    assert _as_corpus(diff_scan_tables(pair["old"], pair["new"])) == pair["expected"]


def test_corpus_is_not_vacuous() -> None:
    ids = {p["id"] for p in PAIRS}
    assert {"legacy_int_scores", "legacy_no_qi_no_risk"} <= ids
    for pair in PAIRS:
        expected = pair["expected"]
        empty = not any(expected[k] for k in CHANGE_LISTS)
        assert empty == bool(pair.get("no_drift")), f"{pair['id']}: no_drift marker is wrong"
    kinds = {k for p in PAIRS for k in diff_scan_tables(p["old"], p["new"]).drift_kinds}
    assert kinds == {"pii_bucket_increased", "new_high_pii_field", "new_quasi_identifier_group"}
    legacy = next(p for p in PAIRS if p["id"] == "legacy_int_scores")
    assert all(isinstance(f.get("pii_score"), int) for f in legacy["old"]["fields"])
    assert "scan_schema" not in legacy["old"]


def test_reads_only_the_four_members() -> None:
    bare_old: dict[str, Any] = {
        "fields": [{"name": "a", "pii_score": 0.1}],
        "quasi_identifier_groups": [["a"]],
        "reid_risk_score": 1.0,
    }
    bare_new: dict[str, Any] = {
        "fields": [{"name": "a", "pii_score": 0.7}, {"name": "b", "pii_score": 0.9}],
        "quasi_identifier_groups": [["a"], ["b", "a"]],
        "reid_risk_score": 4.0,
    }
    noisy_old = {**bare_old, "name": "t", "row_count": "garbage", "descriptor": None}
    noisy_new = {**bare_new, "key_candidates": 7, "warnings": "x"}
    noisy_new["fields"] = [{**f, "dtype": 3, "sample": CANARY} for f in bare_new["fields"]]
    assert diff_scan_tables(noisy_old, noisy_new) == diff_scan_tables(bare_old, bare_new)
    diff = diff_scan_tables(bare_old, bare_new)
    assert [c.name for c in diff.pii_increased] == ["a"]
    assert diff.qi_added == (("a", "b"),)
    assert diff.risk_delta == 3.0


def test_a_missing_score_compares_as_zero() -> None:
    diff = diff_scan_tables(
        {"fields": [{"name": "a"}, {"name": "b", "pii_score": None}]},
        {"fields": [{"name": "a", "pii_score": 0.65}, {"name": "b", "pii_score": 0.2}]},
    )
    by_name = {c.name: c for c in diff.pii_increased}
    assert by_name["a"].old_score == 0.0 and by_name["a"].old_bucket == "none"
    assert by_name["b"].new_bucket == "low"
    assert isinstance(by_name["a"].old_score, float)


def test_risk_delta_needs_both_sides() -> None:
    assert diff_scan_tables({"reid_risk_score": 1}, {"reid_risk_score": 3}).risk_delta == 2.0
    assert diff_scan_tables({}, {"reid_risk_score": 3}).risk_delta is None
    assert diff_scan_tables({"reid_risk_score": 1}, {"reid_risk_score": None}).risk_delta is None


def test_non_numeric_score_is_refused_without_the_value() -> None:
    with pytest.raises(TypeError) as caught:
        diff_scan_tables(
            {"fields": [_field("a")]}, {"fields": [{"name": "a", "pii_score": CANARY}]}
        )
    assert CANARY not in str(caught.value)


@pytest.mark.parametrize(
    ("score", "bucket"),
    [
        (None, "none"),
        (0, "none"),
        (0.0, "none"),
        (-0.5, "none"),
        (1e-9, "low"),
        (0.2999, "low"),
        (0.3, "med"),
        (0.5999, "med"),
        (0.6, "high"),
        (1, "high"),
    ],
)
def test_pii_bucket_thresholds(score: float | None, bucket: str) -> None:
    assert pii_bucket(score) == bucket


def test_two_pairs_sharing_a_table_name_do_not_share_results() -> None:
    first = _doc([_table("t", [_field("a", 0.1)])]), _doc([_table("t", [_field("a", 0.9)])])
    second = _doc([_table("t", [_field("a", 0.9)])]), _doc([_table("t", [_field("a", 0.1)])])
    results = []
    for order in ((first, second), (second, first)):
        results.append([diff_scan_documents(*pair) for pair in order])
    assert results[0][0] == results[1][1] and results[0][1] == results[1][0]
    assert [c.name for c in results[0][0].tables[0].pii_increased] == ["a"]
    assert not results[0][1].tables[0].pii_increased
    assert results[0][1].tables[0].pii_decreased


# ---------------------------------------------------------------------------
# F15-T2: table matching
# ---------------------------------------------------------------------------


def test_table_only_in_current_is_added_drift() -> None:
    diff = diff_scan_documents(
        _doc([_table("a", [_field("x")])]),
        _doc([_table("a", [_field("x")]), _table("b", [_field("y")])]),
    )
    assert diff.tables_added == ("b",)
    assert diff.drift_kinds == ("table_added",)
    assert diff.drift and not diff.no_common_table
    assert [t.table for t in diff.tables] == ["a"]


def test_table_only_in_baseline_is_reported_not_drift() -> None:
    diff = diff_scan_documents(
        _doc([_table("a", [_field("x")]), _table("gone", [_field("y")])]),
        _doc([_table("a", [_field("x")])]),
    )
    assert diff.tables_removed == ("gone",)
    assert not diff.drift and diff.drift_kinds == ()


def test_no_common_table_is_one_kind_and_no_added_entries() -> None:
    diff = diff_scan_documents(
        _doc([_table("a", [_field("x")])]),
        _doc([_table("b", [_field("x")]), _table("c", [_field("x")])]),
    )
    assert diff.drift_kinds == ("no_common_table",)
    assert diff.no_common_table and diff.drift
    assert diff.tables_added == ()
    assert diff.tables_removed == ("a",)
    assert diff.tables == ()


def test_empty_sets_have_nothing_in_common_and_no_drift() -> None:
    diff = diff_scan_documents(_doc([]), _doc([]))
    assert not diff.drift and not diff.no_common_table


def test_a_table_matches_by_name_and_its_own_drift_counts() -> None:
    diff = diff_scan_documents(
        _doc([_table("a", [_field("x", 0.1)])]), _doc([_table("a", [_field("x", 0.9)])])
    )
    assert diff.drift and diff.drift_kinds == ()
    assert diff.tables[0].drift_kinds == ("pii_bucket_increased",)


def test_tables_selects_the_names_compared() -> None:
    base = _doc([_table("a", [_field("x", 0.1)]), _table("b", [_field("x", 0.1)])])
    cur = _doc([_table("a", [_field("x", 0.1)]), _table("b", [_field("x", 0.9)]), _table("c", [])])
    only_a = diff_scan_documents(base, cur, tables=["a"])
    assert [t.table for t in only_a.tables] == ["a"] and not only_a.drift
    only_b = diff_scan_documents(base, cur, tables=["b"])
    assert only_b.drift and only_b.tables_added == ()


def test_set_members_survive_a_selection() -> None:
    diff = diff_scan_documents(
        _doc([_table("a", [])], version="0.27.0"),
        _doc([_table("a", [])], version="0.29.0"),
        tables=["a"],
    )
    assert (diff.baseline_engine_version, diff.current_engine_version) == ("0.27.0", "0.29.0")


def test_a_detector_change_is_information_not_drift() -> None:
    a, b = [_table("t", [_field("x")])], [_table("t", [_field("x")])]
    same = diff_scan_documents(_doc(a), _doc(b))
    assert not same.detectors_changed
    version = diff_scan_documents(_doc(a, "0.27.0"), _doc(b, "0.29.0"))
    runs = diff_scan_documents(
        _doc(a, detectors=[{"source": "regex", "model": None}]),
        _doc(b, detectors=[{"source": "regex", "model": None}, {"source": "ner", "model": {}}]),
    )
    for diff in (version, runs):
        assert diff.detectors_changed and not diff.drift


def test_a_document_that_repeats_a_table_name_is_refused() -> None:
    twice = _doc([_table(CANARY, []), _table(CANARY, [_field("x", 0.9)])])
    with pytest.raises(ValueError) as caught:
        diff_scan_documents(twice, _doc([_table(CANARY, [])]))
    assert CANARY not in str(caught.value)


# ---------------------------------------------------------------------------
# F15-T3: the persisted document
# ---------------------------------------------------------------------------


def _document() -> dict[str, Any]:
    base = _doc(
        [_table("customers", [_field("a", 0.1), _field("gone", 0.2)], quasi_identifier_groups=[])],
        detectors=[{"source": "regex", "model": None}],
    )
    cur = _doc(
        [
            _table(
                "customers",
                [_field("a", 0.9), _field("alt_email", 0.91), _field("odd", None)],
                quasi_identifier_groups=[["a", "alt_email"]],
                reid_risk_score=3.0,
                descriptor={"path": CANARY},
            ),
            _table("orders", [_field("n", 0.1)]),
        ],
        version="0.29.0",
    )
    for field in cur["tables"][0]["fields"]:
        field["sample"] = CANARY
    return scan_diff_to_dict(diff_scan_documents(base, cur))


def test_document_shape_and_round_trip() -> None:
    document = _document()
    assert list(document) == [
        "scan_diff_schema",
        "baseline_engine_version",
        "current_engine_version",
        "detectors_changed",
        "drift",
        "drift_kinds",
        "no_common_table",
        "tables_added",
        "tables_removed",
        "tables",
    ]
    assert document["scan_diff_schema"] == SCAN_DIFF_SCHEMA == "scan-diff/v1"
    assert document["drift_kinds"] == ["table_added"]
    assert document["tables"][0]["drift_kinds"] == [
        "pii_bucket_increased",
        "new_high_pii_field",
        "new_quasi_identifier_group",
    ]
    assert document["tables"][0]["removed"] == [
        {"name": "gone", "pii_score": 0.2, "pii_bucket": "low"}
    ]
    assert json.loads(json.dumps(document, allow_nan=False)) == document
    assert ScanDiffCoreRead.model_validate(document).model_dump() == document
    assert ScanDiffCore.model_validate(document).model_dump() == document


def test_document_holds_no_input_text_beyond_names_and_numbers() -> None:
    assert CANARY not in json.dumps(_document())


def test_the_write_model_refuses_what_a_writer_must_not_emit() -> None:
    good = _document()

    def mutate(path: tuple[Any, ...], value: Any) -> dict[str, Any]:
        doc = copy.deepcopy(good)
        node: Any = doc
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        return doc

    bad = [
        {**good, "extra": 1},
        mutate(("tables", 0, "extra"), 1),
        mutate(("tables", 0, "added", 0, "extra"), 1),
        mutate(("tables", 0, "added", 0, "pii_score"), True),
        mutate(("tables", 0, "added", 0, "pii_score"), "0.5"),
        mutate(("tables", 0, "pii_increased", 0, "new_score"), True),
        mutate(("tables", 0, "risk_delta"), float("nan")),
        mutate(("tables", 0, "added", 0, "pii_bucket"), "extreme"),
        mutate(("tables", 0, "drift_kinds", 0), "free text"),
        mutate(("drift_kinds", 0), "free text"),
        mutate(("drift_kinds", 0), "pii_bucket_increased"),
        mutate(("scan_diff_schema",), "scan-diff/v1.1"),
        mutate(("drift",), 1),
        mutate(("detectors_changed",), "false"),
    ]
    for doc in bad:
        with pytest.raises(ValidationError):
            ScanDiffCore.model_validate(doc)
    with pytest.raises(ValidationError) as caught:
        ScanDiffCore.model_validate(mutate(("drift_kinds", 0), CANARY))
    assert UNKNOWN_KIND in str(caught.value)


def test_the_read_model_takes_a_minor_and_ignores_unknown_members() -> None:
    doc = _document()
    doc["scan_diff_schema"] = "scan-diff/v1.1"
    doc["added_later"] = {"x": 1}
    doc["tables"][0]["added_later"] = [CANARY]
    doc["tables"][0]["added"][0]["added_later"] = CANARY
    read = ScanDiffCoreRead.model_validate(doc).model_dump()
    assert read == _document()
    assert "added_later" not in json.dumps(read)


@pytest.mark.parametrize(
    "tag",
    [
        "scan-diff/v2",
        "scan-diff/v1\n",
        "scan-diff/v1.\n",
        "scan-diff/v1.x",
        "scan-diff/v10",
        "",
        None,
        1,
    ],
)
def test_the_read_model_refuses_another_major_or_trailing_text(tag: object) -> None:
    doc = _document()
    doc["scan_diff_schema"] = tag
    with pytest.raises(ValidationError):
        ScanDiffCoreRead.model_validate(doc)


def test_the_read_model_refuses_a_missing_tag() -> None:
    doc = _document()
    del doc["scan_diff_schema"]
    with pytest.raises(ValidationError):
        ScanDiffCoreRead.model_validate(doc)


@pytest.mark.parametrize("where", [("drift_kinds",), ("tables", 0, "drift_kinds")])
def test_an_unknown_drift_kind_is_refused_with_fixed_text(where: tuple[Any, ...]) -> None:
    doc = _document()
    node: Any = doc
    for key in where:
        node = node[key]
    node.append(f"renamed_column_{CANARY}")
    with pytest.raises(ValidationError) as caught:
        ScanDiffCoreRead.model_validate(doc)
    assert UNKNOWN_KIND in str(caught.value)
    assert CANARY not in str(caught.value)
    assert [e["type"] for e in caught.value.errors()] == ["scan_diff_unknown_kind"]


def test_a_kind_of_the_other_level_is_refused() -> None:
    doc = _document()
    doc["tables"][0]["drift_kinds"].append("no_common_table")
    with pytest.raises(ValidationError):
        ScanDiffCoreRead.model_validate(doc)


def test_the_read_model_stays_strict_about_known_members() -> None:
    doc = _document()
    doc["tables"][0]["added"][0]["pii_score"] = "0.91"
    with pytest.raises(ValidationError) as caught:
        ScanDiffCoreRead.model_validate(doc)
    assert "0.91" not in str(caught.value)


@pytest.mark.parametrize("name", ["scan-diff-v1.json", "scan-diff-v1.1.json"])
def test_corpus_samples_read(name: str) -> None:
    sample = json.loads((CORPUS / name).read_text(encoding="utf-8"))
    read = ScanDiffCoreRead.model_validate(sample).model_dump()
    assert read["scan_diff_schema"] == "scan-diff/v1"
    assert read["tables"][0]["pii_decreased"][0]["name"] == "zip"
    assert read["drift_kinds"] == ["table_added"]
    if name == "scan-diff-v1.json":
        assert ScanDiffCore.model_validate(sample).model_dump() == sample
        assert read == sample
    else:
        assert "added_in_v1_1" not in json.dumps(read)


# ---------------------------------------------------------------------------
# F15-T5: exports
# ---------------------------------------------------------------------------

E1_NAMES = (
    "SCAN_DIFF_SCHEMA",
    "pii_bucket",
    "diff_scan_tables",
    "diff_scan_documents",
    "TableDiff",
    "ScanSetDiff",
    "FieldChange",
    "FieldPresence",
    "scan_diff_to_dict",
    "ScanDiffCore",
    "ScanDiffCoreRead",
    "read_scan_set",
    "ScanSetReadError",
)


def test_names_are_exported_from_profiling_only() -> None:
    assert set(E1_NAMES) <= set(profiling.__all__)
    for name in E1_NAMES:
        assert hasattr(profiling, name)
        assert name not in decoy_engine.__all__
        assert not hasattr(decoy_engine, name)
