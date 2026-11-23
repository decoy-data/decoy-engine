"""A22 and A25: the native path scope and the macOS aggregator's decision, offline.

`changes` takes an injectable git runner, so no test needs a repository. `judge` reads the
`toJSON(needs)` document the workflow pipes in.
"""

from __future__ import annotations

import io
import json
import subprocess
from collections.abc import Sequence
from typing import Any

import pytest
from scripts.dev import native_scope as ns

BASE, HEAD = "a" * 40, "b" * 40


def runner(out: str, calls: list[list[str]] | None = None) -> Any:
    def run(argv: Sequence[str]) -> str:
        if calls is not None:
            calls.append(list(argv))
        return out

    return run


def changes(paths: list[str], event: str = "pull_request") -> str:
    out = "\0".join(paths) + ("\0" if paths else "")
    return ns.native_line(event, BASE, HEAD, runner(out))


@pytest.mark.parametrize(
    "path",
    [
        "decoy-engine-native/src/lib.rs",
        "decoy-engine-native/Cargo.toml",
        ".github/workflows/native-companion.yml",
        "scripts/dev/lock_version.sh",
        "uv.lock",
    ],
)
def test_changes_matches_each_native_path(path: str) -> None:
    assert changes(["README.md", path]) == "native=true"


@pytest.mark.parametrize(
    "paths",
    [
        [],
        ["src/decoy_engine/engine.py", "docs/guide.md"],
        ["decoy-engine-native-notes.md", "scripts/dev/lock_version.shx", "uv.lock.bak"],
        [".github/workflows/ci.yml"],
    ],
)
def test_changes_ignores_unrelated_paths(paths: list[str]) -> None:
    assert changes(paths) == "native=false"


def test_a_rename_out_of_the_native_dir_is_native() -> None:
    # --no-renames lists the old path as a deletion, so the old side still matches.
    assert changes(["decoy-engine-native/old.rs", "src/new.rs"]) == "native=true"


def test_non_ascii_native_path_is_not_quoted_away() -> None:
    assert changes(["decoy-engine-native/café.rs"]) == "native=true"


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch", ""])
def test_events_other_than_pull_request_run_the_legs_without_git(event: str) -> None:
    def boom(argv: Sequence[str]) -> str:
        raise AssertionError("git must not run")

    assert ns.native_line(event, "", "", boom) == "native=true"


def test_a_push_to_main_skips_the_legs_without_git() -> None:
    # The PR that merged already built them; the aggregator judges native=false with skipped legs.
    def boom(argv: Sequence[str]) -> str:
        raise AssertionError("git must not run")

    assert ns.native_line("push", "", "", boom) == "native=false"


def test_a_git_error_and_a_runner_exception_run_the_legs() -> None:
    def failing(argv: Sequence[str]) -> str:
        raise subprocess.CalledProcessError(128, list(argv))

    def odd(argv: Sequence[str]) -> str:
        raise RuntimeError("boom")

    assert ns.native_line("pull_request", BASE, HEAD, failing) == "native=true"
    assert ns.native_line("pull_request", BASE, HEAD, odd) == "native=true"


@pytest.mark.parametrize(("base", "head"), [("", HEAD), (BASE, ""), ("", "")])
def test_a_missing_sha_runs_the_legs_without_git(base: str, head: str) -> None:
    def boom(argv: Sequence[str]) -> str:
        raise AssertionError("git must not run")

    assert ns.native_line("pull_request", base, head, boom) == "native=true"


def test_git_argv_has_no_renames_and_the_three_dot_range() -> None:
    calls: list[list[str]] = []
    ns.native_line("pull_request", BASE, HEAD, runner("", calls))
    assert len(calls) == 1
    assert "--no-renames" in calls[0] and "--name-only" in calls[0]
    assert f"{BASE}...{HEAD}" in calls[0]


def test_changes_writes_exactly_one_line(capsys: pytest.CaptureFixture[str]) -> None:
    code = ns.main(["changes", "--event", "schedule", "--base", "", "--head", ""])
    assert code == 0
    assert capsys.readouterr().out == "native=true\n"


# --- A25: the judge ----------------------------------------------------------------------

NC_RESULTS = ["success", "failure", "cancelled", "skipped"]
NATIVE_VALUES = ["true", "false", None, "", "TRUE"]
MAC_RESULTS = ["success", "failure", "cancelled", "skipped"]


def needs_doc(nc: str, native: str | None, mac: str) -> dict[str, Any]:
    outputs = {} if native is None else {"native": native}
    return {
        "native-changes": {"result": nc, "outputs": outputs},
        "companion-wheel-macos": {"result": mac, "outputs": {}},
    }


@pytest.mark.parametrize("nc", NC_RESULTS)
@pytest.mark.parametrize("native", NATIVE_VALUES)
@pytest.mark.parametrize("mac", MAC_RESULTS)
def test_judge_truth_table(nc: str, native: str | None, mac: str) -> None:
    passes = nc == "success" and (
        (native == "true" and mac == "success") or (native == "false" and mac == "skipped")
    )
    problems = ns.judge(needs_doc(nc, native, mac))
    assert (problems == []) is passes


def test_judge_names_the_failed_need_without_echoing_values() -> None:
    problems = ns.judge(needs_doc("success", "true", "failure"))
    assert problems and any("companion-wheel-macos" in p for p in problems)
    odd = ns.judge(needs_doc("success", "secret-looking-value", "skipped"))
    assert odd and all("secret-looking-value" not in p for p in odd)


@pytest.mark.parametrize(
    "doc",
    [{}, {"native-changes": {"result": "success"}}, [], "x", {"native-changes": 3}],
)
def test_judge_fails_closed_on_a_malformed_document(doc: Any) -> None:
    assert ns.judge(doc) != []


def test_judge_main_exit_codes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def run(doc: str) -> int:
        monkeypatch.setattr("sys.stdin", io.StringIO(doc))
        return ns.main(["judge"])

    assert run(json.dumps(needs_doc("success", "false", "skipped"))) == 0
    assert run(json.dumps(needs_doc("success", "true", "failure"))) == 1
    assert run("not json") == 1
    assert run("") == 1
    capsys.readouterr()
