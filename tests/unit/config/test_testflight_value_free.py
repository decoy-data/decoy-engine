"""The test-flight failure text carries no cell values.

The flight workflow prints the report to the CI log and uploads report.md, and the
assertion message lands in the pytest log. A job error or an invariant detail can quote
a cell value, so both surfaces show only the exception type name, the invariant name and
a fixed category. These tests build results by hand, so they run in the default suite
without a live flight.
"""

from __future__ import annotations

from testflight._report import format_job_section, render_report
from testflight._runner import (
    INVARIANT_FAILED_CATEGORY,
    InvariantResult,
    JobResult,
    failure_text,
)

SENTINEL = "SENTINEL-cell-value-0042"


def _errored(error_type: str | None) -> JobResult:
    return JobResult(job_name="j", error=f"bad date {SENTINEL}", error_type=error_type)


def _invariant_failed() -> JobResult:
    return JobResult(
        job_name="j",
        invariant_results=[
            InvariantResult(family="fk_integrity", passed=False, detail=f"orphan {SENTINEL}"),
            InvariantResult(family="determinism", passed=True, detail="rows=3"),
        ],
    )


def test_failure_text_names_error_type_only() -> None:
    text = failure_text(_errored("ValueError"))
    assert "ValueError" in text
    assert SENTINEL not in text


def test_failure_text_untyped_error_is_unclassified() -> None:
    text = failure_text(_errored(None))
    assert "unclassified" in text
    assert SENTINEL not in text


def test_failure_text_names_failed_invariant_and_category() -> None:
    text = failure_text(_invariant_failed())
    assert "fk_integrity" in text
    assert INVARIANT_FAILED_CATEGORY in text
    assert "determinism" not in text
    assert SENTINEL not in text


def test_job_section_hides_error_text() -> None:
    section = format_job_section(_errored("ValueError"))
    assert "ValueError" in section
    assert SENTINEL not in section
    assert "unclassified" in format_job_section(_errored(None))


def test_job_section_hides_invariant_detail_on_failure() -> None:
    section = format_job_section(_invariant_failed())
    assert "fk_integrity" in section
    assert INVARIANT_FAILED_CATEGORY in section
    assert SENTINEL not in section


def test_full_report_hides_sentinel() -> None:
    report = render_report([_errored("ValueError"), _invariant_failed()], now="t")
    assert SENTINEL not in report
