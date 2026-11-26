"""The test-flight failure text carries no cell values.

The flight workflow prints the report to the CI log and uploads report.md, and the
assertion message lands in the pytest log. A job error or an invariant detail can quote
a cell value, so both surfaces show only the exception type name, the invariant name and
a fixed category. These tests build results by hand, so they run in the default suite
without a live flight.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
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


def test_job_section_names_type_for_empty_error_message() -> None:
    # A bare AssertionError() gives error="" and error_type="AssertionError".
    bare = JobResult(job_name="j", error="", error_type="AssertionError")
    assert "AssertionError" in format_job_section(bare)


_FAILING_TEST = textwrap.dedent(
    """
    import os

    from testflight._assert import assert_job_passed
    from testflight._runner import InvariantResult, JobResult

    def test_flight() -> None:
        # Via env so the sentinel is never in this source, which pytest prints.
        secret = os.environ["FLIGHT_SENTINEL"]
        assert_job_passed(
            JobResult(
                job_name="j",
                error=f"bad date {secret}",
                error_type="ValueError",
                invariant_results=[
                    InvariantResult(
                        family="fk_integrity",
                        passed=False,
                        detail=f"orphan {secret}",
                    )
                ],
            )
        )
    """
)


@pytest.mark.parametrize("flags", [[], ["--tb=short"], ["--tb=long", "-vv"]])
def test_pytest_failure_output_hides_sentinel(tmp_path: Path, flags: list[str]) -> None:
    # Real pytest output: assertion rewriting can echo the JobResult repr.
    (tmp_path / "test_flight_case.py").write_text(_FAILING_TEST, encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[3]
    proc = subprocess.run(  # noqa: S603 - fixed argv, test-owned file
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-o", "addopts=", *flags],
        cwd=tmp_path,
        env={
            "PYTHONPATH": f"{repo_root}:{repo_root / 'src'}",
            "PATH": "/usr/bin:/bin",
            "FLIGHT_SENTINEL": SENTINEL,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, "the inner test should fail"
    assert "ValueError" in out
    assert SENTINEL not in out
