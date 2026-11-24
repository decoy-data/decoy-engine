"""WHEN-READS-SOURCE registry facts (plan revision 2.7, AT-27h and AT-27i).

The conversion allowlist stays at main's keys, and the compile-once allowlist is a registered
sentry, so neither can grow without a visible baseline change.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from tests.sentry import _baseline_sources as bs


def test_compile_once_allowlist_is_a_registered_source() -> None:
    source = next(s for s in bs.SOURCES if s.sentry_id == "compile-once")
    assert isinstance(source.keys, bs.InCode)
    assert (source.keys.test_file, source.keys.constant) == (
        "defects/test_compile_once.py",
        "ALLOWED",
    )
    baseline = json.loads((bs.BASELINES / "compile-once.json").read_text(encoding="utf-8"))
    assert set(baseline["entries"]) == source.keys()


def test_lossless_int_baseline_has_no_conversion_helper_key() -> None:
    entries = json.loads((bs.BASELINES / "lossless-int-columns.json").read_text(encoding="utf-8"))[
        "entries"
    ]
    assert not [k for k in entries if k.endswith("::masking_frame")]
    assert "to_pandas_fk_safe::execution/_pandas_adapter.py::PandasExecutionAdapter.run" in entries
    assert "to_pandas_fk_safe::execution/_sequential.py::run_sequential" in entries


def test_ratchet_check_passes_against_main() -> None:
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", "origin/main"],  # noqa: S607 - git on PATH
        cwd=bs.ROOT,
        capture_output=True,
    )
    if probe.returncode:
        pytest.skip("origin/main is not available in this checkout")
    run = subprocess.run(
        [sys.executable, "scripts/dev/ratchet_check.py", "--base", "origin/main"],
        cwd=bs.ROOT,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
