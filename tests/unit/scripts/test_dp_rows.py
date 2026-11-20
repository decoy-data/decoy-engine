"""AT-G9: release prep writes the DP certified rows through `stamp_release.py`.

Each case runs the real `main` on a clone of a scratch repository holding this working tree, so the
whole stamp transaction (registry, changelog, DP rows) is the one under test. The expected rows are
rebuilt here from sha256 over sorted `name==version` lines, not through the code under test. A
refusal must exit 1 and leave the clone's files and HEAD exactly as they were: the certified-stack
set is a supply-chain trust input.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from _fragment_repo import GIT, REPO
from scripts.release import dp_rows
from scripts.release import stamp_release as sr

PROVENANCE = "src/decoy_engine/quality/dp_provenance.py"
VERSION = "0.29.0"
CLI_VERSION = "9.8.7"
UV = shutil.which("uv")
_ROW = re.compile(r'^\s+"([0-9a-f]{64})",$', re.M)
_CLI_MARK = "# decoy-cli pristine RUNTIME profile"

pytestmark = pytest.mark.skipif(UV is None, reason="uv computes the dev row from uv.lock")

# The engine's own base-requirements closure from uv.lock: every candidate must name all of it, so
# the fixtures carry it as plain pins (names are what the guard reads; the versions are arbitrary).
_CLOSURE = sorted(dp_rows.base_closure(REPO, dp_rows.lock_profile_python(REPO), UV)) if UV else []
_CLOSURE_LINES = "".join(f"{name}==1.0.0\n" for name in _CLOSURE)
_CLOSURE_PINS = {(name, "1.0.0") for name in _CLOSURE}

BASE = (
    """# the previous certified pin file
alpha==1.0.0
beta-pkg==2.0.0
gamma_pkg==3.1.0
delta==4.0.0 ; python_version >= "3.10"
omega==9.9.9 ; sys_platform == "win32"
"""
    + _CLOSURE_LINES
)
CAND_A = BASE
CAND_B = BASE.replace("alpha==1.0.0", "alpha==1.0.1").replace("delta==4.0.0", "delta==4.0.1")
# The certified platform evaluates each marker; omega is off it. Names are canonical.
_A_PINS = {
    ("alpha", "1.0.0"),
    ("beta-pkg", "2.0.0"),
    ("gamma-pkg", "3.1.0"),
    ("delta", "4.0.0"),
} | _CLOSURE_PINS
_B_PINS = {
    ("alpha", "1.0.1"),
    ("beta-pkg", "2.0.0"),
    ("gamma-pkg", "3.1.0"),
    ("delta", "4.0.1"),
} | _CLOSURE_PINS


def _fp(pins: set[tuple[str, str]]) -> str:
    lines = "\n".join(f"{n}=={v}" for n, v in sorted(pins))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def _git(cwd: Path, *args: str) -> str:
    run = subprocess.run(  # noqa: S603 - fixed git executable, test-literal arguments
        [GIT, "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return run.stdout.strip()


@pytest.fixture(scope="module")
def base_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """This working tree (uncommitted edits included) as a one-commit repository."""
    dest = tmp_path_factory.mktemp("dp-rows-base") / "repo"
    files = _git(REPO, "ls-files", "-co", "--exclude-standard", "-z").split("\0")
    for rel in filter(None, files):
        src = REPO / rel
        if not src.is_file():
            continue
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / rel, follow_symlinks=False)
    _git(dest, "init", "-q", "-b", "main")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "chore: base")
    return dest


@pytest.fixture
def clone(base_repo: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", "--local", str(base_repo), str(dest))
    return dest


@pytest.fixture
def pins(tmp_path: Path) -> dict[str, Path]:
    out = {}
    for name, text in {"base": BASE, "a": CAND_A, "b": CAND_B}.items():
        out[name] = tmp_path / f"{name}.txt"
        out[name].write_text(text, encoding="utf-8")
    return out


def _args(pins: dict[str, Path], **over: object) -> list[str]:
    argv = ["--version", VERSION, "--date", "2026-11-17"]
    argv += ["--cli-pins-base", str(pins["base"])]
    argv += ["--cli-pins", str(pins["a"]), "--cli-pins", str(pins["b"])]
    argv += ["--cli-version", CLI_VERSION]
    for flag in over.get("drop", ()):  # type: ignore[attr-defined]
        while flag in argv:
            i = argv.index(flag)
            del argv[i : i + 2]
    return argv


def _run(clone: Path, argv: list[str]) -> int:
    return sr.main([*argv, "--repo", str(clone)])


def _blocks(text: str) -> tuple[list[str], list[str]]:
    """(dev rows, cli rows) in file order, split at the decoy-cli comment."""
    cut = text.index(_CLI_MARK)
    return _ROW.findall(text[:cut]), _ROW.findall(text[cut:])


def _dev_row(clone: Path) -> str:
    py = dp_rows.lock_profile_python(clone)
    extras = dp_rows.bootstrap_extras((clone / "scripts/dev/bootstrap.sh").read_text("utf-8"))
    got = dp_rows.profile_pins(clone, extras, py, UV)
    assert ("decoy-engine", "0.28.0") not in got  # the engine version is added, not exported
    return _fp({*got, ("decoy-engine", VERSION)})


def test_stamp_writes_the_dev_row_and_two_cli_rows(clone: Path, pins: dict[str, Path]) -> None:
    before = (clone / PROVENANCE).read_text("utf-8")
    old_dev, old_cli = _blocks(before)
    dev = _dev_row(clone)
    cli_a = _fp({*_A_PINS, ("decoy-engine", VERSION), ("decoy-cli", CLI_VERSION)})
    cli_b = _fp({*_B_PINS, ("decoy-engine", VERSION), ("decoy-cli", CLI_VERSION)})

    assert _run(clone, _args(pins)) == 0

    new_dev, new_cli = _blocks((clone / PROVENANCE).read_text("utf-8"))
    assert new_dev == [dev, *old_dev]  # inserted at the top, every old row kept in order
    assert new_cli == [cli_a, cli_b, *old_cli]
    changed = _git(clone, "diff", "--numstat", "--", PROVENANCE).split()
    assert changed[:2] == ["3", "0"]  # three rows added, nothing removed


def test_inserting_the_same_rows_again_adds_nothing(clone: Path, pins: dict[str, Path]) -> None:
    assert _run(clone, _args(pins)) == 0
    once = (clone / PROVENANCE).read_text("utf-8")
    dev, cli = _blocks(once)
    again = dp_rows.insert_rows(once, "3.10.20.final", dev[:1], cli[:2])
    assert again == once


def test_the_rows_are_computed_for_the_stamped_version(clone: Path, pins: dict[str, Path]) -> None:
    assert _run(clone, _args(pins)) == 0
    dev, _ = _blocks((clone / PROVENANCE).read_text("utf-8"))
    assert dev[0] == _dev_row(clone)
    # A row for the pyproject version (0.28.0) would be a different hash: the stamp used --version.
    assert dev[0] != dp_rows.dev_row(clone, "0.28.0", UV)


def test_allow_delta_admits_a_named_package(clone: Path, pins: dict[str, Path]) -> None:
    pins["b"].write_text(CAND_B + "newpkg==0.1.0\n", encoding="utf-8")
    assert _run(clone, _args(pins)) == 1
    assert _run(clone, [*_args(pins), "--allow-delta", "newpkg"]) == 0
    _, cli = _blocks((clone / PROVENANCE).read_text("utf-8"))
    assert cli[1] == _fp(
        {*_B_PINS, ("newpkg", "0.1.0"), ("decoy-engine", VERSION)} | {("decoy-cli", CLI_VERSION)}
    )


def _bad_pin(text: str) -> str:
    return text + "this is not a pin\n"


def _bad_requirement(text: str) -> str:
    return text + 'zeta==1.0.0 ; python_version >>> "3"\n'


def _more_names(text: str) -> str:
    return text + "extra==1.0.0\n"


def _fewer_names(text: str) -> str:
    return text.replace("beta-pkg==2.0.0\n", "")


def _lacks_a_closure_name(text: str) -> str:
    """The 0.28.0 situation: the previous pin file kept as is while the engine gained requirements."""
    return text.replace(f"{_CLOSURE[0]}==1.0.0\n", "")


REFUSALS = {
    "missing-base": lambda p: ({}, ["--cli-pins-base"]),
    "missing-candidates": lambda p: ({}, ["--cli-pins"]),
    "missing-cli-version": lambda p: ({}, ["--cli-version"]),
    "malformed-base": lambda p: ({"base": _bad_pin(BASE)}, []),
    "malformed-base-requirement": lambda p: ({"base": _bad_requirement(BASE)}, []),
    "malformed-first-candidate": lambda p: ({"a": _bad_pin(CAND_A)}, []),
    "malformed-second-candidate": lambda p: ({"b": _bad_pin(CAND_B)}, []),
    "candidate-requirement": lambda p: ({"b": _bad_requirement(CAND_B)}, []),
    "candidate-adds-a-name": lambda p: ({"b": _more_names(CAND_B)}, []),
    "candidate-drops-a-name": lambda p: ({"a": _fewer_names(CAND_A)}, []),
    # base and candidate agree (both lack the name), so only the closure guard can refuse this.
    "candidate-lacks-an-engine-requirement": lambda p: (
        {k: _lacks_a_closure_name(t) for k, t in (("base", BASE), ("a", CAND_A), ("b", CAND_B))},
        [],
    ),
    "missing-file": lambda p: ({}, []),
}


@pytest.mark.parametrize("cell", sorted(REFUSALS))
def test_refusals_exit_1_and_leave_the_tree_unchanged(
    cell: str, clone: Path, pins: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    rewrite, drop = REFUSALS[cell](pins)
    for name, text in rewrite.items():
        pins[name].write_text(text, encoding="utf-8")
    if cell == "missing-file":
        pins["a"].unlink()
    head = _git(clone, "rev-parse", "HEAD")
    before = (clone / PROVENANCE).read_bytes()

    assert _run(clone, _args(pins, drop=drop)) == 1

    assert "refused" in capsys.readouterr().err
    assert _git(clone, "status", "--porcelain", "--untracked-files=all") == ""
    assert _git(clone, "rev-parse", "HEAD") == head
    assert (clone / PROVENANCE).read_bytes() == before


def test_the_refusal_names_the_missing_engine_requirement(
    clone: Path, pins: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    for name, text in (("base", BASE), ("a", CAND_A), ("b", CAND_B)):
        pins[name].write_text(_lacks_a_closure_name(text), encoding="utf-8")
    assert _run(clone, _args(pins)) == 1
    err = capsys.readouterr().err
    assert "lacks the engine's base requirements" in err
    assert _CLOSURE[0] in err


def test_a_late_refusal_leaves_the_tree_unchanged(clone: Path, pins: dict[str, Path]) -> None:
    """A version CHANGELOG.md already holds fails after the DP plan exists; nothing is written."""
    before = (clone / PROVENANCE).read_bytes()
    argv = _args(pins)
    argv[argv.index("--version") + 1] = "0.28.0"
    assert _run(clone, argv) == 1
    assert _git(clone, "status", "--porcelain", "--untracked-files=all") == ""
    assert (clone / PROVENANCE).read_bytes() == before


def test_a_dirty_provenance_file_is_refused(clone: Path, pins: dict[str, Path]) -> None:
    (clone / PROVENANCE).write_text(
        (clone / PROVENANCE).read_text("utf-8") + "\n# edit\n", encoding="utf-8"
    )
    assert _run(clone, _args(pins)) == 1
