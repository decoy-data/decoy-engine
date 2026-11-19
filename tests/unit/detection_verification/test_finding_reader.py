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
    ResidualPIIFinding,
    post_scan_verdict,
    read_residual_finding,
)
from decoy_engine.verification.postmask.finding_reader import FIELD_CHECKS, project_for_verdict

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
    assert read_residual_finding(row, version=V3) is None


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
    assert (
        read_residual_finding({k: v for k, v in _BASE.items() if k != required}, version=V2) is None
    )


def test_a_null_match_rate_is_v3_only() -> None:
    assert read_residual_finding({**_BASE, "match_rate": None}, version=V2) is None
    assert read_residual_finding({**_v3(), "match_rate": None}, version=V3)["match_rate"] is None


@pytest.mark.parametrize("bad", [None, "x", [1], 3])
def test_a_row_that_is_not_a_mapping_or_has_an_unreadable_version_is_refused(bad: Any) -> None:
    assert read_residual_finding(bad, version=V3) is None
    assert read_residual_finding(_v3(), version="post-scan-integrity/v9") is None


@pytest.mark.parametrize("field", V3_ADDED_FIELDS)
def test_a_v2_row_that_carries_a_v3_only_field_is_refused(field: str) -> None:
    """A v2 report predates these fields, so a row holding one is not a v2 row."""
    carried = {**_BASE, field: _v3()[field]}
    assert read_residual_finding(carried, version=V2) is None
    assert read_residual_finding(dict(_BASE), version=V2) is not None


def _report(version: str, **row: Any) -> dict[str, Any]:
    return {"schema_version": version, "residual_pii": [{**_BASE, "severity": "fail", **row}]}


@pytest.mark.parametrize("ner_findings", ["warn", "fail"])
def test_the_verdict_reads_a_v2_row_as_regex_whatever_its_source_says(ner_findings: str) -> None:
    """Probe: a v2 fail row blocks as a failed check with `source` absent, and must with `ner`."""
    bare = post_scan_verdict(_report(V2), ner_findings=ner_findings)
    with_source = post_scan_verdict(_report(V2, source="ner"), ner_findings=ner_findings)
    assert bare.blocking and with_source.blocking
    assert with_source.codes == bare.codes


def test_a_v3_ner_row_is_still_a_model_row_for_the_verdict() -> None:
    row = {"source": "ner", "severity": "fail"}
    v3 = post_scan_verdict(_report(V3, **row), ner_findings="warn")
    assert not v3.blocking
    assert post_scan_verdict(_report(V3, **row), ner_findings="fail").blocking


@pytest.mark.parametrize("raw", [None, "x", 3, [1]])
def test_the_projection_never_refuses_a_malformed_row(raw: Any) -> None:
    row = project_for_verdict(raw, version=V3)
    assert row.severity is None and row.source is None


def test_the_projection_names_the_location_fields() -> None:
    row = project_for_verdict({**_BASE, "source": "ner"}, version=V3)
    assert (row.table, row.column, row.detector_id, row.source) == ("t", "c", "email", "ner")
    assert project_for_verdict({**_BASE, "source": "ner"}, version=V2).source == "regex"
