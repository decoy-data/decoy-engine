"""Residual sentry for the retired product name (this repository only).

Each consumer repo carries its own copy of this sentry for its own tree; this one cannot see
them, so a green run here says nothing about the other repos.

Every tracked path and every tracked text file is scanned, case-insensitively, for the retired
name, written plainly and rebuilt from quoted pieces. Only the dated history folders in `HISTORY`
(and the released sections of `CHANGELOG.md`) may keep it. The name is spelled in two parts
below, so this file holds no plain literal; other tests that need the string import
`RETIRED_NAME` or `RETIRED_PATTERN` from here, which keeps one source for the spelling.

The sentry also checks a short list of removed canary-check names the case-insensitive scan
cannot see. A seeded violation per surface keeps a green run from being vacuous.
"""

from __future__ import annotations

import ast
import fnmatch
import os
import pathlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SENTRY_REL = "tests/sentry/test_no_residual_removed_surface.py"

RETIRED_NAME = "st" + "orm"
RETIRED_PATTERN = re.compile(re.escape(RETIRED_NAME), re.IGNORECASE)
# The name rebuilt from string pieces ("a" + "b", "a" "b"). A match counts only when its span
# holds a quote, so plain text is left to RETIRED_PATTERN.
SPLIT_PATTERN = re.compile(r"""[\s'"+]*""".join(RETIRED_NAME), re.IGNORECASE)

FORBIDDEN_TOKENS: tuple[str, ...] = (
    # removed canary-check surface (the case-insensitive scan cannot see these)
    "canary_check",
    "canary-check",
    "CanaryReport",
    "/canary-check",
)


@dataclass(frozen=True)
class Allowed:
    glob: str
    purpose: str


# Folders that hold dated history. Adding a root is a review decision, never a routine edit.
HISTORY_ROOTS: tuple[str, ...] = (
    "docs/plans/",
    "docs/records/",
    "docs/archive/",
    "docs/decisions/",
)

HISTORY: tuple[Allowed, ...] = (
    Allowed("docs/plans/*", "dated plans and their captured evidence"),
    Allowed("docs/records/*", "dated build, gate and audit records"),
    Allowed("docs/archive/*", "archived reviews and discussions"),
    Allowed("docs/decisions/*", "ADRs and the dated module-size census history"),
)


def _history(rel: str) -> bool:
    return any(fnmatch.fnmatch(rel, h.glob) for h in HISTORY)


# A released section has a version and a date in its heading. Everything else in CHANGELOG.md (the
# preamble, `[Unreleased]`, an undated or oddly spelled heading) is scanned.
_RELEASED_HEADING = re.compile(r"^## \[\d+\.\d+\.\d+\] - \d{4}-\d{2}-\d{2}\s*$")


def _non_history_text(changelog: str) -> str:
    """CHANGELOG.md without its dated release sections, which are history."""
    keep: list[str] = []
    inside = True  # the preamble before the first heading is not history
    for line in changelog.splitlines():
        if line.startswith("## "):
            inside = not _RELEASED_HEADING.match(line)
        if inside:
            keep.append(line)
    return "\n".join(keep)


def _is_binary(data: bytes) -> bool:
    return b"\0" in data[:8000]  # git's own rule


def scan(root: pathlib.Path, rel_paths: list[str]) -> list[str]:
    """Return `path: reason` for every residual in `rel_paths` outside the history allowlist."""
    hits: list[str] = []
    for rel in rel_paths:
        if _history(rel):
            continue
        if RETIRED_PATTERN.search(rel):
            hits.append(f"{rel}: path")
        path = root / rel
        if not os.path.lexists(path):  # a tracked path that is not on disk must not hide a file
            hits.append(f"{rel}: missing")
            continue
        if path.is_symlink():  # git tracks the link text, not what it points at
            if RETIRED_PATTERN.search(os.readlink(path)):
                hits.append(f"{rel}: symlink target")
            continue
        if not path.is_file():  # a submodule or other non-regular entry has no text to read
            hits.append(f"{rel}: not a regular file")
            continue
        try:
            data = path.read_bytes()
        except OSError:
            hits.append(f"{rel}: unreadable")
            continue
        if _is_binary(data):
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            # Bytes that are not UTF-8 are still scanned, one byte per character, so a retired name
            # (always ASCII) in such a file is caught and a deliberately invalid fixture is not a hit.
            text = data.decode("latin-1")
        if rel == "CHANGELOG.md":
            text = _non_history_text(text)
        if RETIRED_PATTERN.search(text):
            hits.append(f"{rel}: content")
        if rel != SENTRY_REL and any(
            "'" in m.group() or '"' in m.group() for m in SPLIT_PATTERN.finditer(text)
        ):
            hits.append(f"{rel}: split literal")
        for token in FORBIDDEN_TOKENS:
            if rel != SENTRY_REL and token in text:  # this file defines the list
                hits.append(f"{rel}: forbidden token {token!r}")
    return hits


def _tracked(root: pathlib.Path = ROOT) -> list[str]:
    """Tracked paths, NUL-separated so a non-ASCII name is not C-quoted into a path that does not
    exist on disk."""
    out = subprocess.run(  # noqa: S603 - fixed argv, no user input
        [shutil.which("git") or "git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    return [os.fsdecode(raw) for raw in out.split(b"\0") if raw]


def test_no_residual_retired_name_in_tracked_files() -> None:
    assert scan(ROOT, _tracked()) == []


def test_former_exceptions_are_scanned_now() -> None:
    for rel in (
        "src/decoy_engine/reasons/route/_retired.py",
        "tests/fixtures/f29/reason-manifest-v1.json",
        "tests/fixtures/f29/reason-registry-release.json",
        "tests/unit/test_shipped_reason_identities.py",
        SENTRY_REL,
    ):
        assert not _history(rel), rel


NAME = RETIRED_NAME
SPLIT_TITLE = f'"{NAME[:2].title()}" + "{NAME[2:]}"'
SPLIT_ADJACENT = f"'{NAME[:1]}' '{NAME[1:]}'"

# surface -> (path, body, the exact hit the sentry must report)
SEEDS = {
    "path": (f"src/pkg/{NAME}_helper.py", "x = 1\n", "path"),
    "python-identifier": (
        "src/pkg/mod.py",
        f"def compute_{NAME}_postmask():\n    pass\n",
        "content",
    ),
    "help-string": ("src/pkg/cli.py", f'HELP = "Path to a {NAME.upper()} scan JSON"\n', "content"),
    "yaml-comment": (
        "examples/p.yaml",
        f"version: 2\n# REVIEW: {NAME.title()} detected a key\n",
        "content",
    ),
    "json-schema-description": (
        "docs/schemas/s.json",
        f'{{"description": "Compare two {NAME} files"}}\n',
        "content",
    ),
    "test-file-name": (f"tests/e2e/test_{NAME}_animation.py", "x = 1\n", "path"),
    "doc-page": ("docs/ref.md", f"The {NAME} pass runs first.\n", "content"),
    "changelog-unreleased": (
        "CHANGELOG.md",
        f"## [Unreleased]\n\n- the {NAME} flag\n\n## [0.1.0] - 2026-01-01\n",
        "content",
    ),
    "changelog-preamble": (
        "CHANGELOG.md",
        f"# Changelog\n\nThe {NAME} notes.\n\n## [0.1.0] - 2026-01-01\n",
        "content",
    ),
    "changelog-undated-heading": (
        "CHANGELOG.md",
        f"## Unreleased\n\n- the {NAME} flag\n\n## [0.1.0] - 2026-01-01\n",
        "content",
    ),
    "changelog-fragment": ("changelog.d/x.md", f"### Added (the {NAME} option)\n", "content"),
    "split-literal-title": ("src/pkg/mod.py", f"x = {SPLIT_TITLE}\n", "split literal"),
    "split-literal-adjacent": ("src/pkg/mod.py", f"x = {SPLIT_ADJACENT}\n", "split literal"),
    "non-ascii-path": (f"docs/caf\u00e9_{NAME}.md", "x\n", "path"),
    "removed-canary": (
        "docs/api.md",
        "the report type is CanaryReport\n",
        "forbidden token 'CanaryReport'",
    ),
}


@pytest.mark.parametrize("surface", sorted(SEEDS))
def test_sentry_catches_seeded_violation(tmp_path: pathlib.Path, surface: str) -> None:
    rel, body, reason = SEEDS[surface]
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    assert scan(tmp_path, [rel]) == [f"{rel}: {reason}"]


def test_a_non_ascii_tracked_file_is_scanned_not_skipped(tmp_path: pathlib.Path) -> None:
    """`git ls-files` C-quotes a non-ASCII name; the sentry must still open that file."""
    git = shutil.which("git") or "git"
    subprocess.run([git, "init", "-q"], cwd=tmp_path, check=True)  # noqa: S603
    (tmp_path / "caf\u00e9.md").write_text(f"the {NAME} pass\n", encoding="utf-8")
    subprocess.run([git, "add", "."], cwd=tmp_path, check=True)  # noqa: S603
    rels = _tracked(tmp_path)
    assert rels == ["caf\u00e9.md"]
    assert scan(tmp_path, rels) == ["caf\u00e9.md: content"]


def test_a_tracked_symlink_is_read_as_link_text_not_followed(tmp_path: pathlib.Path) -> None:
    (tmp_path / "ok.md").write_text(f"the {NAME} pass\n", encoding="utf-8")
    (tmp_path / "benign").symlink_to("ok.md")  # the link text is clean; git tracks only that
    (tmp_path / "dangling").symlink_to(f"gone_{NAME}.md")  # dangling, and its text spells the name
    assert scan(tmp_path, ["benign"]) == []
    assert scan(tmp_path, ["dangling"]) == ["dangling: symlink target"]


def test_a_tracked_directory_entry_is_a_hit(tmp_path: pathlib.Path) -> None:
    (tmp_path / "sub").mkdir()  # how a submodule appears in a checkout
    assert scan(tmp_path, ["sub"]) == ["sub: not a regular file"]


def test_a_tracked_path_missing_from_disk_is_a_hit(tmp_path: pathlib.Path) -> None:
    assert scan(tmp_path, ["docs/gone.md"]) == ["docs/gone.md: missing"]


def test_an_undecodable_text_file_is_scanned_not_skipped(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "docs" / "page.md"
    target.parent.mkdir()
    target.write_bytes(b"caf\xe9 " + NAME.encode())
    assert scan(tmp_path, ["docs/page.md"]) == ["docs/page.md: content"]


def test_an_undecodable_file_without_a_retired_name_is_clean(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "vector.bin"
    target.write_bytes(b'{"a": "\xff\xfe"}')
    assert scan(tmp_path, ["vector.bin"]) == []


def test_a_binary_file_is_checked_by_path_only(tmp_path: pathlib.Path) -> None:
    (tmp_path / "blob.bin").write_bytes(b"\0" + NAME.encode())
    (tmp_path / f"{NAME}.bin").write_bytes(b"\0")
    assert scan(tmp_path, ["blob.bin"]) == []
    assert scan(tmp_path, [f"{NAME}.bin"]) == [f"{NAME}.bin: path"]


def test_history_and_released_changelog_sections_pass(tmp_path: pathlib.Path) -> None:
    for rel in ("docs/plans/p.md", "docs/records/r.md", "docs/archive/a.md", "docs/decisions/d.md"):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"the {NAME} pass\n")
        assert scan(tmp_path, [rel]) == []
    (tmp_path / "CHANGELOG.md").write_text(
        f"## [Unreleased]\n\n## [0.1.0] - 2026-01-01\n\n- dropped the {NAME} flag\n"
    )
    assert scan(tmp_path, ["CHANGELOG.md"]) == []


def test_plain_words_are_not_split_literals(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "src" / "m.py"
    target.parent.mkdir()
    target.write_text("# unrelated text: stop, on the room.\nx = 'a'\n")
    assert scan(tmp_path, ["src/m.py"]) == []


def test_every_history_glob_is_under_a_history_root() -> None:
    for entry in HISTORY:
        assert entry.purpose and entry.glob.startswith(HISTORY_ROOTS), entry.glob
    assert not _history("src/decoy_engine/anything.py")
    assert not _history("tests/unit/test_x.py")


def _exclude_patterns() -> list[str]:
    tree = ast.parse((ROOT / "docs" / "conf.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "exclude_patterns" for t in node.targets
        ):
            return list(ast.literal_eval(node.value))
    raise AssertionError("docs/conf.py has no exclude_patterns list")


def _sdist_excludes() -> list[str]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(config["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"])


@pytest.mark.parametrize("root", HISTORY_ROOTS)
def test_history_roots_stay_out_of_the_docs_site_and_the_sdist(root: str) -> None:
    folder = root.removeprefix("docs/").rstrip("/")
    assert f"{folder}/**" in _exclude_patterns(), f"docs/conf.py does not exclude {folder}/**"
    assert f"docs/{folder}" in _sdist_excludes(), f"the sdist still ships docs/{folder}"
