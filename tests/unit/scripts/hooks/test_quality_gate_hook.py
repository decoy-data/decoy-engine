"""The Claude push gate hook stops PR creation and risky pushes, never a plain push."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
GIT = shutil.which("git") or "/usr/bin/git"
HOOK = Path(__file__).resolve().parents[4] / ".claude" / "hooks" / "decoy-quality-gate.sh"


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
    subprocess.run(  # noqa: S603 - fixed git executable, test-literal arguments
        [GIT, "-C", str(tmp_path), "tag", "v9.9.9"], check=True
    )
    return tmp_path


def test_a_receipt_covers_only_risky_pushes_run_in_its_own_worktree(
    repo: Path, tmp_path_factory
) -> None:
    other = tmp_path_factory.mktemp("other")
    subprocess.run([GIT, "init", "-q", str(other)], check=True)  # noqa: S603 - fixed git
    git_dir = subprocess.run(  # noqa: S603 - fixed git executable, test-literal arguments
        [GIT, "-C", str(repo), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    head = subprocess.run(  # noqa: S603 - fixed git executable, test-literal arguments
        [GIT, "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    Path(git_dir, "decoy-quality-gate").write_text(head + "\n")
    assert not denied(repo, "git push --force origin feat/x")
    assert denied(repo, f"git -C {other} push --force origin feat/x")
    assert denied(repo, f"cd {other} && git push --force-with-lease origin feat/x")
    assert not denied(repo, f"cd {other} && git push origin feat/x")


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
        "git status\ngit push --force origin feat/x",
        "/usr/bin/git push --force origin feat/x",
        "GH_HOST=github.com gh pr create --fill",
        "gh -R decoy-data/decoy-engine pr create --fill",
        "env FOO=1 git push -f origin feat/x",
        "git push origin feat/issue#123 --force",
        "git push origin HEAD:refs/tags/v1",
        "git push origin feat/x && git fetch --all",
        "git push origin feat/x # not --force",
        "git push origin feat/x\ngit fetch --all",
        "if git push --force-with-lease origin feat/x; then echo pushed; fi",
        'git commit -m "#123: fix typo" && git push --force-with-lease origin feat/x',
    ],
)
def test_pr_creation_and_risky_pushes_wait_for_the_gate(repo: Path, command: str) -> None:
    assert denied(repo, command)


@pytest.mark.parametrize(
    "command",
    [
        "git push -u origin feat/x",
        "git push origin feat/x",
        "git push origin feat/allow--all",
        "git push origin HEAD:feat/x",
        "git fetch --all --prune",
        "git tag -d v1",
        "pytest -q tests/unit",
        "git push -odeploy=1 origin feat/x",
        'git commit -m "first line\n\nsecond line"',
        "cat <<'EOF' > notes.md\nline one\nEOF",
    ],
)
def test_plain_pushes_and_other_commands_pass(repo: Path, command: str) -> None:
    assert not denied(repo, command)
