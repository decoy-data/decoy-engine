"""Pytest-facing assertion for a test-flight job result."""

from __future__ import annotations

import pytest

from ._runner import JobResult, failure_text


def assert_job_passed(result: JobResult) -> None:
    """Fail with value-free text; a bare assert would let pytest print the result repr."""
    if not result.passed:
        pytest.fail(failure_text(result), pytrace=False)
