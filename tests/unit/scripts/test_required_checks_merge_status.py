"""A20 and A23: the gate verdict status and the macOS path scope in the required-check verifier.

Moved out of test_required_checks.py to keep that module under the size cap; it reuses that
module's fakes.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_required_checks import (
    GATE_CONTEXT,
    HEAD,
    MAIN,
    ROOT,
    FakeGit,
    FakeGitHub,
    green_pr,
    run_main,
    verify,
)


def with_status(state: str | None, context: str = GATE_CONTEXT) -> FakeGitHub:
    gh = green_pr()
    gh.statuses = [] if state is None else [{"id": 7, "context": context, "state": state}]
    return gh


def test_verify_requires_gate_status(capsys: pytest.CaptureFixture[str]) -> None:
    assert verify(with_status("success")) == 0
    capsys.readouterr()
    for state in (None, "pending", "failure", "error"):
        assert verify(with_status(state)) == 1, state
        out = capsys.readouterr().out
        assert f"{GATE_CONTEXT}: dispatch gate-selfhosted.yml on {HEAD}" in out, state
        assert "tier green" not in out


def test_a_status_under_another_context_does_not_count() -> None:
    assert verify(with_status("success", context="something/else")) == 1


def test_one_green_context_among_others_passes() -> None:
    gh = green_pr()
    gh.statuses = [
        {"id": 1, "context": "other", "state": "failure"},
        {"id": 2, "context": GATE_CONTEXT, "state": "success"},
    ]
    assert verify(gh) == 0


def test_registry_without_a_merge_status_table_is_an_error() -> None:
    class Git(FakeGit):
        def __call__(self, args: Any) -> str:
            argv = list(args)
            if argv[0] == "show" and argv[1].endswith("ci/required-jobs.toml"):
                text = (ROOT / "ci/required-jobs.toml").read_text()
                return text.split("[[merge_status]]")[0]
            return super().__call__(args)

    assert verify(green_pr(), git=Git()) == 2


def test_status_listing_errors_are_never_a_pass() -> None:
    gh = green_pr()
    gh.error = None
    gh.response_transform = lambda path, out: (
        {**out, "total_count": 5} if "/status?" in path else out
    )
    assert verify(gh) == 2


def test_contexts_skip_exempt_legs_and_include_aggregator(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_main(["contexts", "--ref", MAIN], FakeGitHub()) == 0
    got = json.loads(capsys.readouterr().out)
    assert not any(n.startswith("companion-wheel-macos (") for n in got)
    assert "companion-wheel-macos-ok" in got and "native-changes" in got
