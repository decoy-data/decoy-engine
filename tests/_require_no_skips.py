"""Fail the run on a skipped test when ``DECOY_REQUIRE_PROVIDER_SDKS`` is set (F13 SR-7).

The SDK lane (``secret-provider-sdks`` in ``.github/workflows/ci.yml``) installs every adapter SDK
and semgrep, so a skip there means a cell did not run. A module-level ``pytest.importorskip`` skips
at COLLECTION, which a run-time hook never sees, so both hooks are needed. A skip whose test id
starts with an entry of ``ALLOWED_SKIPS`` still skips (the live Vault test needs a real server).

Registered by importing the hooks into ``tests/conftest.py``. Inert when the variable is unset.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

ENV = "DECOY_REQUIRE_PROVIDER_SDKS"

# Named, exact: a test id or module path prefix. Nothing else may skip in the lane.
ALLOWED_SKIPS = ("tests/secret_providers/test_vault_live.py",)

_MESSAGE = (
    f"{ENV} is set: a skipped test means an SDK cell did not run. Install the SDK in this lane "
    "or add the test id to ALLOWED_SKIPS in tests/_require_no_skips.py."
)
_offenders: list[str] = []


def _enforced() -> bool:
    return os.environ.get(ENV, "") not in ("", "0")


def _allowed(nodeid: str) -> bool:
    return nodeid.startswith(ALLOWED_SKIPS)


def _refuse(report: Any) -> None:
    if _enforced() and report.skipped and not _allowed(report.nodeid):
        _offenders.append(report.nodeid)
        report.outcome = "failed"
        report.longrepr = _MESSAGE


@pytest.hookimpl(tryfirst=True)
def pytest_collectreport(report: Any) -> None:
    _refuse(report)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report: Any) -> None:
    _refuse(report)


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    """A skip turned into a failure above can still leave the run green when the session already
    tallied the report as a skip, so the exit status is set here as well."""
    if _offenders and exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
