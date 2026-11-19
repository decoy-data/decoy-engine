"""PROFILE-SAMPLE-LABELS E1: every scanned number says what it was counted over.

AT-1 to AT-7 (scan routes, the key rule, the profile document), AT-8 (the redactor keeps only the
two literal values), AT-9 and AT-10 (read and write models of `TableCore`), AT-17 (a record written
before the labels still exports). Do not skip a case or loosen an expected value to make one pass.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

from decoy_engine import records
from decoy_engine.profiling import (
    ScanSetCore,
    ScanSetCoreRead,
    profile_columns,
    profile_document,
    redact_profile_dict,
    scan_set_to_dict,
    scan_sources,
)
from decoy_engine.profiling._basis import claim_keys, read_basis
from tests.unit.records._helpers import corpus, make

HEAD_ROWS = 10_000


def _write_csv(path: Path, rows: int, *, skew: bool = False) -> Path:
    """`id` repeats after 12,000 rows, `n` has nulls only after row 10,000, `u` is unique."""
    lines = ["id,n,u"]
    for i in range(rows):
        n = "" if i >= HEAD_ROWS and i % 7 == 0 else str(i % 3)
        lines.append(f"{i % 12_000},{n},{i}")
    path.write_text("\n".join(lines) + "\n")
    return path


def _scan(path: Path, **kw: Any) -> dict[str, Any]:
    source = {"type": "file", "format": "csv", "path": str(path), "has_header": True}
    return scan_set_to_dict(scan_sources({"t": source}, **kw), detail=False)["tables"][0]


@pytest.fixture
def hostile(tmp_path: Path) -> Path:
    return _write_csv(tmp_path / "hostile.csv", 25_000)


def test_at1_a_default_head_scan_of_a_large_file_is_labelled_a_sample(hostile: Path) -> None:
    table = _scan(hostile)
    assert table["basis"] == "sample" and table["scanned_rows"] == HEAD_ROWS
    assert table["row_count"] >= 25_000


def test_at2_a_sample_claims_no_key_and_a_whole_read_claims_the_real_one(hostile: Path) -> None:
    assert _scan(hostile)["key_candidates"] == []
    whole = _scan(hostile, sample_rows=None)
    assert whole["basis"] == "whole" and whole["key_candidates"] == ["u"]


def test_at3_a_short_file_is_a_whole_exact_read(tmp_path: Path) -> None:
    table = _scan(_write_csv(tmp_path / "s.csv", 4_812))
    assert table["basis"] == "whole" and table["scanned_rows"] == 4_812
    assert table["row_count"] == 4_812 and table["row_count_exact"] is True
    assert table["key_candidates"] == ["id", "u"]


def test_at4_exactly_the_cap_is_whole_and_one_row_more_is_a_sample(tmp_path: Path) -> None:
    exact = _scan(_write_csv(tmp_path / "e.csv", HEAD_ROWS))
    assert exact["basis"] == "whole" and exact["key_candidates"] == ["id", "u"]
    over = _scan(_write_csv(tmp_path / "o.csv", HEAD_ROWS + 1))
    assert over["basis"] == "sample" and over["scanned_rows"] == HEAD_ROWS
    assert over["key_candidates"] == [] and over["row_count"] >= HEAD_ROWS + 1


@pytest.mark.parametrize(
    ("rows", "basis", "scanned"),
    [(25_000, "sample", HEAD_ROWS), (4_812, "whole", 4_812), (HEAD_ROWS, "whole", HEAD_ROWS)],
)
def test_at5_a_random_scan_is_whole_only_when_nothing_was_dropped(
    tmp_path: Path, rows: int, basis: str, scanned: int
) -> None:
    table = _scan(_write_csv(tmp_path / "r.csv", rows), strategy="random")
    assert (table["basis"], table["scanned_rows"]) == (basis, scanned)
    assert table["row_count"] == rows and table["row_count_exact"] is True
    assert (table["key_candidates"] == []) == (basis == "sample")


def test_at6_the_full_strategy_is_whole(hostile: Path) -> None:
    table = _scan(hostile, strategy="full")
    assert table["basis"] == "whole" and table["sample_row_cap"] is None
    assert table["scanned_rows"] == table["row_count"] == 25_000


def test_at7_profile_columns_stamps_the_basis_and_the_document_keeps_it() -> None:
    frame = pd.DataFrame({"a": range(1_000)})
    cut = profile_columns(frame.head(100), "t", sample_strategy="head", sample_row_cap=100)
    short = profile_columns(frame.head(50), "t", sample_strategy="head", sample_row_cap=100)
    assert (cut.basis, short.basis) == ("sample", "whole")
    assert claim_keys(cut) == () and claim_keys(short) == ("a",)
    for profile in (cut, short):
        document = profile_document(profile)
        assert document["basis"] == profile.basis
        assert list(profile.to_dict())[-1] == "basis"


def test_read_basis_is_one_rule() -> None:
    assert read_basis("full", 10, False) == "whole"
    assert read_basis("head", None, False) == "whole"
    assert read_basis("head", 10, True) == "whole"
    assert read_basis("head", 10, False) == "sample"


@pytest.mark.parametrize("bad", ["Jane Roe", True, 1, "WHOLE", ["whole"], None])
def test_at8_a_loaded_document_keeps_only_a_literal_basis(bad: Any) -> None:
    doc = profile_document(profile_columns(pd.DataFrame({"a": [1, 2]}), "t"))
    assert redact_profile_dict({**doc, "basis": bad})["basis"] == "[redacted]"
    for good in ("whole", "sample"):
        assert redact_profile_dict({**doc, "basis": good})["basis"] == good


# -- the persisted core -------------------------------------------------------------------------


def _core(**table: Any) -> dict[str, Any]:
    doc = copy.deepcopy(corpus("scan-set-v1-core.json"))
    doc["tables"][0].update(table)
    return doc


def _drop(**table: Any) -> dict[str, Any]:
    """The legacy core with the named table members removed."""
    doc = _core()
    for name in table:
        doc["tables"][0].pop(name, None)
    return doc


WHOLE = {"row_count": 40, "row_count_exact": True, "basis": "whole", "scanned_rows": 40}
# Refused on write and on read: each breaks one relation or a strict type.
CORRUPT: dict[str, dict[str, Any]] = {
    "negative row count": {"row_count": -1},
    "whole, fewer scanned": {**WHOLE, "scanned_rows": 39},
    "whole, estimated count": {**WHOLE, "row_count_exact": False},
    "whole, no scanned count": {**WHOLE, "scanned_rows": None},
    "scanned over the table": {"basis": "sample", "scanned_rows": 41},
    "negative scanned": {"basis": "sample", "scanned_rows": -1},
    "scanned as bool": {"basis": "sample", "scanned_rows": True},
    "scanned as text": {"basis": "sample", "scanned_rows": "10"},
    "scanned as float": {"basis": "sample", "scanned_rows": 10.0},
    "basis as bool": {"basis": True, "scanned_rows": 10},
    "basis as int": {"basis": 1, "scanned_rows": 10},
    "basis as list": {"basis": ["whole"], "scanned_rows": 10},
    "unknown basis, no scanned count": {"basis": "exact", "scanned_rows": None},
}
MODELS = [ScanSetCore, ScanSetCoreRead]


@pytest.mark.parametrize("model", MODELS, ids=["write", "read"])
@pytest.mark.parametrize("cell", sorted(CORRUPT))
def test_at9_at10_corrupt_row_relations_and_types_are_refused(model: Any, cell: str) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(_core(**CORRUPT[cell]))


@pytest.mark.parametrize("model", MODELS, ids=["write", "read"])
def test_at9_at10_the_legacy_shape_and_a_valid_whole_read_validate(model: Any) -> None:
    for table in (
        _drop(basis=1, scanned_rows=1),
        _core(basis="sample", scanned_rows=None),
        _core(basis="sample", scanned_rows=10),
        _core(**WHOLE),
    ):
        model.model_validate(table)


def test_at9_the_pre_basis_core_reads_as_a_sample_with_no_scanned_count() -> None:
    table = ScanSetCoreRead.model_validate(corpus("scan-set-v1-core.json")).tables[0]  # type: ignore[attr-defined]
    assert table.basis == "sample" and table.scanned_rows is None


@pytest.mark.parametrize("unknown", ["exact", "Jane Roe"])
def test_at9_a_basis_a_later_minor_added_reads_as_a_sample(unknown: str) -> None:
    got = ScanSetCoreRead.model_validate(_core(basis=unknown, scanned_rows=10))
    assert got.tables[0].basis == "sample"  # type: ignore[attr-defined]
    assert f'"{unknown}"' not in got.model_dump_json()
    with pytest.raises(ValidationError):
        ScanSetCore.model_validate(_core(basis=unknown, scanned_rows=10))


@pytest.mark.parametrize("tag", ["scan-set/v2", None])
def test_at9_the_schema_tag_stays_exact_on_read(tag: str | None) -> None:
    doc = _core()
    if tag is None:
        doc.pop("scan_schema")
    else:
        doc["scan_schema"] = tag
    with pytest.raises(ValidationError):
        ScanSetCoreRead.model_validate(doc)


def test_at9_at10_a_warning_code_is_checked_on_write_only() -> None:
    doc = _core(warnings=[{"namespace": "warning", "code": "added_by_a_later_minor"}])
    ScanSetCoreRead.model_validate(doc)
    with pytest.raises(ValidationError):
        ScanSetCore.model_validate(doc)


def test_at10_a_refused_record_payload_carries_no_exception_context() -> None:
    with pytest.raises(records.RecordError) as caught:
        make("scan-set", _core(**CORRUPT["whole, fewer scanned"]), labels={})
    assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.parametrize(
    ("kw", "rows"),
    [
        ({}, 25_000),
        ({}, 4_812),
        ({}, HEAD_ROWS),
        ({"strategy": "random"}, 25_000),
        ({"strategy": "random"}, 4_812),
        ({"strategy": "full"}, 25_000),
        ({"sample_rows": None}, 25_000),
    ],
)
def test_at10_every_scan_route_writes_a_scanned_row_count(
    tmp_path: Path, kw: dict[str, Any], rows: int
) -> None:
    table = _scan(_write_csv(tmp_path / "p.csv", rows), **kw)
    assert isinstance(table["scanned_rows"], int) and table["basis"] in ("whole", "sample")


def test_at10_a_whole_basis_without_a_scanned_count_cannot_be_built() -> None:
    from decoy_engine.profiling._scan_core import TableCore

    table = copy.deepcopy(_core()["tables"][0])
    table.update(basis="whole", scanned_rows=None, row_count_exact=True)
    with pytest.raises(ValidationError):
        TableCore.model_validate(table)
