"""F07 82-E2b: `FieldCore.nested` is additive, strict on write and open on read (AT-E2-7)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ConfigDict, ValidationError, create_model

from decoy_engine.profiling import (
    NestedCore,
    PathObservationCore,
    ScanSetCore,
    ScanSetCoreRead,
    scan_set_to_dict,
)
from decoy_engine.profiling._scan_core import FieldCore

from ._support import dumps, scan_cells


def _document(tmp_path: Path) -> dict[str, Any]:
    cells = dumps([{"a": {"b": 1}, "s": "x"}] * 3)
    return scan_set_to_dict(scan_cells(tmp_path, cells), detail=False)


def _path(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "path": "$.a",
        "present_count": 5,
        "null_count": 0,
        "kinds": ["string"],
        "detector_hits": [],
    }
    return {**base, **overrides}


def test_at_e2_7_a_record_without_nested_validates_on_write_and_read(tmp_path: Path) -> None:
    document = _document(tmp_path)
    old = copy.deepcopy(document)
    for table in old["tables"]:
        for field in table["fields"]:
            del field["nested"]
    ScanSetCore.model_validate(old)
    ScanSetCoreRead.model_validate(old)
    ScanSetCore.model_validate(document)


def test_at_e2_7_a_record_with_nested_reads_under_a_model_without_the_field(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)
    field = document["tables"][0]["fields"][0]
    assert field["nested"]["paths"]
    fields = {k: (i.annotation, i) for k, i in FieldCore.model_fields.items() if k != "nested"}
    older = create_model("OlderField", __config__=ConfigDict(extra="ignore"), **fields)
    assert older.model_validate(field).name == field["name"]
    with pytest.raises(ValidationError):
        FieldCore.model_validate({k: v for k, v in field.items() if k != "nested"} | {"extra": 1})


@pytest.mark.parametrize(
    "bad",
    [
        _path(present_count=True),
        _path(present_count="5"),
        _path(null_count=1.0),
        _path(kinds=["decimal"]),
        _path(kinds=["string", 3]),
    ],
)
def test_at_e2_7_write_cells_are_strict(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PathObservationCore.model_validate(bad)


def test_at_e2_7_the_read_model_accepts_an_unknown_kind_token(tmp_path: Path) -> None:
    document = _document(tmp_path)
    document["tables"][0]["fields"][0]["nested"]["paths"][0]["kinds"] = ["decimal"]
    with pytest.raises(ValidationError):
        ScanSetCore.model_validate(document)
    read = ScanSetCoreRead.model_validate(document)
    assert read.tables[0].fields[0].nested.paths[0].kinds == ["decimal"]  # type: ignore[attr-defined]


def test_at_e2_7_nested_core_refuses_unknown_members() -> None:
    members = dict.fromkeys(NestedCore.model_fields, 0) | {
        "paths_truncated": False,
        "paths": [],
    }
    NestedCore.model_validate(members)
    with pytest.raises(ValidationError):
        NestedCore.model_validate(members | {"extra": 1})
