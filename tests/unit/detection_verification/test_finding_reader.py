"""The one versioned reader of a persisted residual-PII finding row.

It takes its field set, required fields and defaults from `ResidualPIIFinding`, so these tests
pin the reader to the writer: a field added to the dataclass fails here until it has a check.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from decoy_engine.verification.postmask import (
    V3_ADDED_FIELDS,
    MalformedFindingError,
    ResidualPIIFinding,
    read_residual_finding,
)
from decoy_engine.verification.postmask.finding_reader import FIELD_CHECKS

V2 = "post-scan-integrity/v2"
V3 = "post-scan-integrity/v3"
_FIELDS = [f.name for f in dataclasses.fields(ResidualPIIFinding)]
_BASE = {
    "table": "t",
    "column": "c",
    "detector_id": "email",
    "match_rate": 0.5,
    "severity": "warning",
}


def _v3() -> dict[str, Any]:
    row = {
        f.name: f.default
        for f in dataclasses.fields(ResidualPIIFinding)
        if f.default is not dataclasses.MISSING
    }
    return {**_BASE, **row, "match_rate": 0.5}


def test_the_checks_cover_exactly_the_writer_fields() -> None:
    assert set(FIELD_CHECKS) == set(_FIELDS)


def test_the_v3_added_fields_are_the_last_defaulted_fields() -> None:
    assert tuple(_FIELDS[-len(V3_ADDED_FIELDS) :]) == V3_ADDED_FIELDS
    defaults = {f.name: f.default for f in dataclasses.fields(ResidualPIIFinding)}
    assert all(defaults[n] is not dataclasses.MISSING for n in V3_ADDED_FIELDS)


@pytest.mark.parametrize("missing", _FIELDS)
def test_a_v3_row_must_carry_every_field(missing: str) -> None:
    row = {k: v for k, v in _v3().items() if k != missing}
    with pytest.raises(MalformedFindingError):
        read_residual_finding(row, version=V3)


def test_a_v2_row_gets_the_writer_defaults() -> None:
    read = read_residual_finding(dict(_BASE), version=V2)
    expected = {
        f.name: f.default
        for f in dataclasses.fields(ResidualPIIFinding)
        if f.default is not dataclasses.MISSING
    }
    assert {k: read[k] for k in expected} == expected


@pytest.mark.parametrize("required", list(_BASE))
def test_a_v2_row_must_carry_the_required_fields(required: str) -> None:
    with pytest.raises(MalformedFindingError):
        read_residual_finding({k: v for k, v in _BASE.items() if k != required}, version=V2)


def test_a_null_match_rate_is_v3_only() -> None:
    with pytest.raises(MalformedFindingError):
        read_residual_finding({**_BASE, "match_rate": None}, version=V2)
    assert read_residual_finding({**_v3(), "match_rate": None}, version=V3)["match_rate"] is None


@pytest.mark.parametrize("bad", [None, "x", [1], 3])
def test_a_row_that_is_not_a_mapping_or_has_an_unreadable_version_is_refused(bad: Any) -> None:
    with pytest.raises(MalformedFindingError):
        read_residual_finding(bad, version=V3)
    with pytest.raises(MalformedFindingError):
        read_residual_finding(_v3(), version="post-scan-integrity/v9")
