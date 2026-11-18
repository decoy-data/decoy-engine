"""`read_scan_set`: the tag rule and the read model for `scan-set/v1` (F15-T4)."""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine.errors import DecoyError
from decoy_engine.profiling import ScanSetReadError, read_scan_set

CANARY = "CANARY-5c21e8"


def _table(name: str = "customers") -> dict[str, Any]:
    return {
        "name": name,
        "descriptor": {},
        "row_count": 3,
        "row_count_exact": True,
        "sample_strategy": "head",
        "sample_row_cap": None,
        "fields": [
            {
                "name": "email",
                "dtype": "object",
                "null_count": 0,
                "null_rate": 0.0,
                "distinct_count": 3,
                "pii_score": 0.9,
                "pii_candidate": True,
                "detector_hits": ["email"],
                "leading_zero_count": None,
            }
        ],
        "key_candidates": [],
        "warnings": [],
        "reid_risk_score": None,
        "quasi_identifier_groups": [],
    }


def _doc(tag: object = "scan-set/v1") -> dict[str, Any]:
    return {
        "scan_schema": tag,
        "engine_version": "0.27.0",
        "scanned_at": "2026-11-17T00:00:00Z",
        "tables": [_table()],
        "relationships": [],
    }


@pytest.mark.parametrize("tag", ["scan-set/v1", "scan-set/v1.0", "scan-set/v1.3", "scan-set/v1.12"])
def test_reads_the_major_and_its_minors(tag: str) -> None:
    read = read_scan_set(_doc(tag))
    assert read["scan_schema"] == "scan-set/v1"
    assert read["tables"][0]["name"] == "customers"


@pytest.mark.parametrize(
    "tag",
    [
        "scan-set/v2",
        "scan-set/v10",
        "scan-set/v1\n",
        "scan-set/v1.3\n",
        "scan-set/v1.",
        "scan-set/v1.x",
        "scan-set/v1 ",
        "Scan-Set/v1",
        "scan-set/v1.3x",
        "",
        None,
        1,
        ["scan-set/v1"],
    ],
)
def test_refuses_a_tag_that_is_not_the_major_or_a_minor(tag: object) -> None:
    with pytest.raises(ScanSetReadError) as caught:
        read_scan_set(_doc(tag))
    assert caught.value.kind == "unsupported_tag"


def test_refuses_a_missing_tag() -> None:
    doc = _doc()
    del doc["scan_schema"]
    with pytest.raises(ScanSetReadError) as caught:
        read_scan_set(doc)
    assert caught.value.kind == "missing_tag"


@pytest.mark.parametrize("data", [[], "scan-set/v1", 3, None])
def test_refuses_a_document_that_is_not_an_object(data: object) -> None:
    with pytest.raises(ScanSetReadError) as caught:
        read_scan_set(data)
    assert caught.value.kind == "invalid"


def test_unknown_members_are_ignored_and_known_ones_are_strict() -> None:
    doc = _doc("scan-set/v1.2")
    doc["from_a_later_minor"] = CANARY
    doc["tables"][0]["extra"] = CANARY
    read = read_scan_set(doc)
    assert CANARY not in repr(read)

    wrong = _doc()
    wrong["tables"][0]["row_count"] = True
    with pytest.raises(ScanSetReadError) as caught:
        read_scan_set(wrong)
    assert caught.value.kind == "invalid"

    stringy = _doc()
    stringy["tables"][0]["fields"][0]["pii_score"] = "0.9"
    with pytest.raises(ScanSetReadError):
        read_scan_set(stringy)


@pytest.mark.parametrize("bad_tag", ["scan-set/v2", None])
def test_errors_are_value_free_and_unchained(bad_tag: object) -> None:
    doc = _doc(bad_tag)
    doc["tables"][0]["name"] = CANARY
    with pytest.raises(ScanSetReadError) as caught:
        read_scan_set(doc)
    assert CANARY not in str(caught.value) and "scan-set/v2" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_validation_failure_is_value_free_and_unchained() -> None:
    doc = _doc()
    doc["tables"][0]["row_count"] = CANARY
    with pytest.raises(ScanSetReadError) as caught:
        read_scan_set(doc)
    assert caught.value.kind == "invalid"
    assert CANARY not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_is_a_value_error_with_a_registered_family() -> None:
    assert issubclass(ScanSetReadError, (ValueError, DecoyError))
    with pytest.raises(ValueError):
        read_scan_set({})
