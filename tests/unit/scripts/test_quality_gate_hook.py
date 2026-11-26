"""The Claude push gate hook stops PR creation and risky pushes, never a plain push."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
GIT = shutil.which("git") or "/usr/bin/git"
HOOK = Path(__file__).resolve().parents[3] / ".claude" / "hooks" / "decoy-quality-gate.sh"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(  # noqa: S603 - fixed git executable, test-literal arguments
        [GIT, "init", "-q", str(tmp_path)], check=True
    )
    subprocess.run(  # noqa: S603 - fixed git executable, test-literal arguments
        [
            GIT,
            "-C",
            str(tmp_path),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        check=True,
    )
    return tmp_path


def denied(repo: Path, command: str) -> bool:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    out = subprocess.run(  # noqa: S603 - fixed bash executable, the repo hook
        [BASH, str(HOOK)], input=payload, capture_output=True, text=True, cwd=repo, check=True
    ).stdout
    return (
        bool(out.strip()) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    )


@pytest.mark.parametrize(
    "command",
    [
        "gh pr create --fill",
        "git push --force origin feat/x",
        "git push -f origin feat/x",
        "git push -uf origin feat/x",
        "git push -vd origin feat/x",
        "git push --force-with-lease origin feat/x",
        'git push origin "+feat/x"',
        "git push origin +feat/x",
        "git push origin :feat/x",
        "git push --delete origin feat/x",
        "git push origin --prune",
        "git push --tags",
        "git push --follow-tags",
        "git push origin tag v1",
        "git push origin refs/tags/v1",
        "git push --mirror origin",
        "git push --all origin",
        "git push origin \\\n  --force feat/x",
        "cd /x && git push --force origin feat/x",
        "git -C /x push -f origin feat/x",
        "git push origin 'feat/x",
    ],
)
def test_pr_creation_and_risky_pushes_wait_for_the_gate(repo: Path, command: str) -> None:
    assert denied(repo, command)


@pytest.mark.parametrize(
    "command",
    [
        "git push -u origin feat/x",
        "git push origin feat/x",
        "git push origin feat/x && git fetch --all",
        "git push origin feat/allow--all",
        "git push origin HEAD:feat/x",
        "git fetch --all --prune",
        "git tag -d v1",
        "pytest -q tests/unit",
    ],
)
def test_plain_pushes_and_other_commands_pass(repo: Path, command: str) -> None:
    assert not denied(repo, command)
