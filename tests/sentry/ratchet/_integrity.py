"""Registry integrity rules for the shrink-only ratchet (stdlib only).

``tests/sentry/_ratchet.py`` loads this file by path (``_integrity()`` there), so a copy of the
checker extracted from a base commit loads only its own helper. Every rule returns finding
strings that carry ids, paths, keys and numbers from the repo's own files, never file content
or exception text. A read of the base tree that fails raises ``BaseReadError``; the caller turns
it into one finding, because treating an unreadable file as an empty one would let a guard
vanish silently.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath
from stat import S_ISDIR, S_ISLNK, S_ISREG
from types import ModuleType
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

MANIFEST = "tests/sentry/test_sentry_manifest.py"
DECISION_TABLES = ("retired", "retired_files", "checker_change")


class BaseReadError(Exception):
    """A file or list of the base commit could not be read; ``what`` names it."""

    def __init__(self, what: str, side: str = "base") -> None:
        super().__init__(what)
        self.what, self.side = what, side


def _git(root: Path, what: str, *args: str, side: str = "base") -> bytes:
    res = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(root), *args],  # noqa: S607
        capture_output=True,
    )
    if res.returncode != 0:
        raise BaseReadError(what, side)
    return res.stdout


def resolve_commit(root: Path, ref: str) -> str | None:
    """The commit sha ``ref`` names, or ``None`` when no such commit exists."""
    res = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],  # noqa: S607
        capture_output=True,
        text=True,
    )
    return res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else None


class BaseTree:
    """One checked listing of the base commit, so "absent" is proven and never a read failure."""

    def __init__(self, root: Path, sha: str, side: str = "base") -> None:
        self.root, self.sha, self.side = root, sha, side
        raw = _git(
            root,
            f"the {side} tree listing",
            "ls-tree",
            "-r",
            "-t",
            "-z",
            "--full-tree",
            sha,
            side=side,
        )
        self.types: dict[str, str] = {}
        self.modes: dict[str, str] = {}
        for entry in raw.split(b"\0"):
            if not entry:
                continue
            meta, _, path = entry.partition(b"\t")
            name = path.decode("utf-8", "surrogateescape")
            self.types[name] = meta.split(b" ")[1].decode()
            self.modes[name] = meta.split(b" ")[0].decode()

    def files(self) -> Iterable[str]:
        return (p for p, kind in self.types.items() if kind == "blob")

    def has_file(self, path: str) -> bool:
        return self.types.get(path) == "blob"

    def children(self, directory: str) -> list[str]:
        """Names directly below ``directory`` in the listing."""
        prefix = directory + "/"
        return sorted(
            n[len(prefix) :]
            for n in self.types
            if n.startswith(prefix) and "/" not in n[len(prefix) :]
        )

    def blob(self, path: str) -> bytes:
        """Raw bytes of a listed blob; the caller has already checked its kind and mode."""
        return _git(self.root, path, "cat-file", "blob", f"{self.sha}:{path}", side=self.side)


class InputReadError(Exception):
    """An input could not be read the one allowed way; ``side`` is ``head`` or ``base``."""

    def __init__(self, what: str, side: str) -> None:
        super().__init__(what)
        self.what, self.side = what, side


class Side:
    """Where inputs come from: the checkout (``tree`` is ``None``) or a commit's tree.

    HEAD and BASE use the same ``kind_of``, ``open_input`` and ``list_entries`` below, so a mode
    or link policy cannot differ between them.
    """

    def __init__(self, name: str, root: Path, tree: BaseTree | None = None) -> None:
        self.name, self.root, self.tree = name, root, tree


def _probe(side: Side, rel: str) -> str | None:
    """The one guarded stat of a single path: ``dir``, ``file``, ``link``, ``other``, or ``None``
    when the path is proven absent. Any other stat error propagates to the caller's guard."""
    if side.tree is None:
        try:
            mode = os.lstat(side.root / rel).st_mode
        except FileNotFoundError:
            return None
        if S_ISLNK(mode):
            return "link"
        return "dir" if S_ISDIR(mode) else "file" if S_ISREG(mode) else "other"
    kind = side.tree.types.get(rel)
    if kind is None:
        return None
    if kind == "tree":
        return "dir"
    mode_text = side.tree.modes[rel]
    if kind == "blob" and mode_text in {"100644", "100755"}:
        return "file"
    return "link" if mode_text == "120000" else "other"


def kind_of(side: Side, path: str) -> str | None:
    """``dir`` or ``file`` for a path whose every ancestor is a plain directory, ``None`` when it
    is proven absent. A link or special file at any depth, a bad path or a stat error raises
    ``InputReadError``."""
    try:
        pure = PurePosixPath(path)
        if (
            not path
            or "\\" in path
            or str(pure) != path
            or pure.is_absolute()
            or ".." in pure.parts
        ):
            raise ValueError("not a plain relative path")
        for n in range(1, len(pure.parts) + 1):
            kind = _probe(side, "/".join(pure.parts[:n]))
            if kind is None:
                return None
            if kind not in {"dir", "file"} or (kind == "file" and n < len(pure.parts)):
                raise ValueError("a link, a special file or a file used as a directory")
        return kind
    except Exception:
        raise InputReadError(path, side.name) from None


def open_input(side: Side, path: str) -> str | None:
    """UTF-8 text of a regular file, ``None`` when proven absent; any other failure raises."""
    kind = kind_of(side, path)
    if kind is None:
        return None
    try:
        if kind != "file":
            raise ValueError("not a regular file")
        if side.tree is not None:
            data = side.tree.blob(path)
        else:
            fd = os.open(side.root / path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as handle:
                data = handle.read()
        return data.decode("utf-8")
    except Exception:
        raise InputReadError(path, side.name) from None


def list_entries(side: Side, directory: str) -> list[str]:
    """Every regular ``.json`` file below ``directory``, nested folders included, sorted.

    A proven absent directory holds none; a file there is a failure. Every directory is checked before descent, and a link,
    a special file or any listing error raises ``InputReadError``.
    """
    kind = kind_of(side, directory)
    if kind is None:
        return []
    try:
        if kind != "dir":
            raise ValueError("not a directory")
        if side.tree is not None:
            names = side.tree.children(directory)
        else:
            with os.scandir(side.root / directory) as it:
                names = sorted(entry.name for entry in it)
        out: list[str] = []
        for name in names:
            child = f"{directory}/{name}"
            kind = kind_of(side, child)
            if kind == "dir":
                out += list_entries(side, child)
            elif kind == "file" and name.endswith(".json"):
                out.append(child)
            elif kind is None:
                raise ValueError("listed but gone")
        return out
    except InputReadError:
        raise
    except Exception:
        raise InputReadError(directory, side.name) from None


def safe_path(path: object, baseline_dir: str) -> bool:
    """A plain relative path with at least one component below ``baseline_dir``."""
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    pure = PurePosixPath(path)
    prefix = PurePosixPath(baseline_dir).parts
    return (
        str(pure) == path
        and not pure.is_absolute()
        and ".." not in pure.parts
        and pure.parts[: len(prefix)] == prefix
        and len(pure.parts) > len(prefix)
    )


def registry_present(base_rows: int, head_rows: int) -> list[str]:
    """A HEAD registry keeps at least one row when the base had rows."""
    if base_rows and not head_rows:
        return ["registry has no [[sentry]] rows; the base registry listed sentries"]
    return []


def validate_registry(text: str) -> tuple[dict[str, Any], list[str]]:
    """The one shape check for a registry, run on HEAD and on the base before anyone reads it.

    Returns the parsed document and the problems that make it unusable (no file content, no TOML
    text). Past this point every ``[[sentry]]`` row is a table with a non-empty string ``id``, a
    string ``baseline`` and, when present, a list ``approved_growth``.
    """
    try:
        doc = tomllib.loads(text)
    except (ValueError, RecursionError):  # bad TOML, an oversized integer, nesting too deep
        return {}, ["is not valid TOML"]
    rows = doc.get("sentry", [])
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        return {}, ["must hold [[sentry]] as an array of tables"]
    problems = []
    for n, row in enumerate(rows, 1):
        if not isinstance(row.get("id"), str) or not row["id"]:
            problems.append(f"[[sentry]] row {n}: id must be a non-empty string")
        elif not isinstance(row.get("baseline"), str):
            problems.append(f"{row['id']}: baseline must be a string path")
        elif not isinstance(row.get("approved_growth", []), list):
            problems.append(f"{row['id']}: approved_growth must be a list")
    return doc, problems


def closed_keys(
    doc: dict[str, object],
    allowed: frozenset[str],
    problem: Callable[[object], str | None],
    waived: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[list[str], list[str]]:
    """Unknown row keys and malformed decision tables, plus the waiver report lines.

    ``waived`` holds exact ``(id, field)`` pairs; only the unknown-key finding of that pair is
    omitted. Unknown top-level tables are ignored.
    """
    out: list[str] = []
    used: list[str] = []
    for row in doc.get("sentry", []):  # shape was checked by ``validate_registry``
        sid = row["id"]
        for key in sorted(set(row) - allowed):
            if (sid, key) in waived:
                used.append(f"{sid}: registry key {key} waived by checker_change")
            else:
                out.append(f"{sid}: unknown registry key {key}")
    for table in DECISION_TABLES:
        rows_ = doc.get(table, {})
        if not isinstance(rows_, dict):
            out.append(f"registry: [{table}] must be a table of dated decision strings")
            continue
        for name, decision in sorted(rows_.items()):
            why = problem(decision)
            if why:
                out.append(f"{table} {name}: {why}")
    return out, used


def decisions(doc: dict[str, object]) -> dict[str, dict[str, str]]:
    """``{table: {name: decision string}}``; non-string values are left to ``closed_keys``."""
    out: dict[str, dict[str, str]] = {}
    for table in DECISION_TABLES:
        rows = doc.get(table, {})
        out[table] = (
            {k: v for k, v in rows.items() if isinstance(v, str)} if isinstance(rows, dict) else {}
        )
    return out


def table_names(doc: dict[str, object]) -> dict[str, set[str]]:
    """Every key of each decision table, whatever its value type (freshness is about names)."""
    out: dict[str, set[str]] = {}
    for t in DECISION_TABLES:
        rows = doc.get(t)
        out[t] = set(rows) if isinstance(rows, dict) else set()
    return out


def fresh(
    head: dict[str, str], base: set[str], problem: Callable[[object], str | None]
) -> set[str]:
    """Names of valid decisions at head whose name is not in the base table."""
    return {name for name, text in head.items() if name not in base and problem(text) is None}


def new_decisions(
    head: dict[str, dict[str, str]],
    base: dict[str, set[str]],
    approvals: dict[str, dict[str, str]],
    base_approvals: dict[str, dict[str, str]],
) -> list[str]:
    """Report lines for every decision row at head whose name is not at base."""
    out = [
        f"decision {table} {name}: {text}"
        for table in DECISION_TABLES
        for name, text in sorted(head[table].items())
        if name not in base[table]
    ]
    out += [
        f"decision approved_growth {sid} {key}: {text}"
        for sid, rows in sorted(approvals.items())
        for key, text in sorted(rows.items())
        if key not in base_approvals.get(sid, {})
    ]
    return out


def new_baseline_findings(tree: BaseTree, created_in: dict[str, str]) -> list[str]:
    """A baseline file new in the diff needs a non-empty ``created_in`` (``{path: value}``)."""
    return [
        f"{path}: new baseline has no created_in"
        for path, value in sorted(created_in.items())
        if not tree.has_file(path) and not value.strip()
    ]


def transfer_findings(
    r: ModuleType,
    donors: dict[str, dict[str, object]],
    successors: dict[str, dict[str, object]],
    per_site: bool,
    removed: Iterable[str] = (),
) -> tuple[list[str], list[str]]:
    """Match every successor key to one removed donor's key; each ``(donor, key)`` pair once.

    ``donors`` are removed ids without a fresh retirement, ``successors`` the ids new in the
    diff. A key with no free donor is new, a key with two free donors is ambiguous, a matched key
    may not loosen a bound against its donor, and every donor with an inventory must supply at
    least one key. With ``per_site`` the unmatched ``permitted::`` keys fall back to ``r.growth``.
    """
    if not donors and not successors:
        return [], []
    holders: dict[str, list[str]] = {}
    for did, entries in donors.items():
        for key in entries:
            holders.setdefault(key, []).append(did)
    spent: set[tuple[str, str]] = set()
    supplied: set[str] = set()
    unmatched: set[str] = set()
    loosened: set[str] = set()
    out: list[str] = []
    for sid in sorted(successors):
        for key in sorted(successors[sid]):
            free = [d for d in holders.get(key, []) if (d, key) not in spent]
            if len(free) > 1:
                out.append(f"replacement or split: key {key} has more than one removed donor")
            elif free:
                spent.add((free[0], key))
                supplied.add(free[0])
                if r.bound_loosened(successors[sid][key], donors[free[0]][key]):
                    loosened.add(key)
            else:
                unmatched.add(key)
    report: list[str] = []
    if per_site and unmatched:
        left = frozenset(k for d, e in donors.items() for k in e if (d, k) not in spent)
        grown, rekeyed = r.growth(frozenset(unmatched), left, True)
        report = [f"replacement: re-keyed permitted site {s} (review the message)" for s in rekeyed]
        sites = set(rekeyed)
        supplied |= {d for d, e in donors.items() if any(r.permit_site(k) in sites for k in e)}
        unmatched = set(grown)
    ids = ", ".join(sorted(donors or removed))
    if unmatched:
        out.append(f"replacement or split of {ids} adds key(s): {', '.join(sorted(unmatched))}")
    if loosened:
        out.append(
            f"replacement or split of {ids} raised or dropped max for key(s): "
            f"{', '.join(sorted(loosened))}"
        )
    out += [
        f"{d}: removed from the registry without a fresh [retired] decision or a key moved to a new sentry"
        for d in sorted(donors)
        if d not in supplied
    ]
    return out, report


def outside_sentries(text: str) -> list[str] | None:
    """``OUTSIDE_SENTRIES`` read by ``ast`` (never imported), or ``None`` if it is not a literal."""
    for node in ast.parse(text).body:
        targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
        if any(isinstance(t, ast.Name) and t.id == "OUTSIDE_SENTRIES" for t in targets):
            value = getattr(node, "value", None)
            if isinstance(value, (ast.Tuple, ast.List)) and all(
                isinstance(e, ast.Constant) and isinstance(e.value, str) for e in value.elts
            ):
                return [e.value for e in value.elts]  # type: ignore[attr-defined]
            return None
    return None


def is_test_filename(name: str) -> bool:
    """``test_*.py``: the one definition of a test file name (sentry membership and gate pins)."""
    return name.startswith("test_") and name.endswith(".py")


def is_sentry_glob(path: str) -> bool:
    """``tests/sentry/**/test_*.py``: the one definition of sentry-file membership."""
    parts = PurePosixPath(path).parts
    return parts[:2] == ("tests", "sentry") and is_test_filename(parts[-1])


def sentry_set(files: Iterable[str], manifest: str | None) -> set[str] | None:
    """Sentry files among ``files`` plus the manifest's ``OUTSIDE_SENTRIES``; ``None`` if unparsable."""
    outside = [] if manifest is None else outside_sentries(manifest)
    if outside is None:
        return None
    return {f for f in files if is_sentry_glob(f)} | set(outside)


def _manifest(side: Side) -> str | None:
    try:
        return open_input(side, MANIFEST)
    except InputReadError:
        raise BaseReadError(MANIFEST, side.name) from None


def sentry_file_findings(root: Path, tree: BaseTree, retired_files: set[str]) -> list[str]:
    """Sentry test files of the base tree that are gone at head without a rename or retirement.

    The head set comes from the HEAD commit, the same one rename detection diffs, and is then
    limited to files still in the checkout, found by the guarded stat: only proven absence counts
    as removal, and an unreadable path is a finding.
    """
    base_set = sentry_set(tree.files(), _manifest(Side("base", root, tree)))
    if base_set is None:
        raise BaseReadError(MANIFEST)
    base_set = {p for p in base_set if tree.has_file(p)}
    head_sha = resolve_commit(root, "HEAD")
    if head_sha is None:
        raise BaseReadError("the head commit", "head")
    head_tree = BaseTree(root, head_sha, "head")
    head_set = sentry_set(head_tree.files(), _manifest(Side("head", root, head_tree)))
    if head_set is None:
        return [f"{MANIFEST}: OUTSIDE_SENTRIES is not a literal tuple of strings"]
    checkout, findings, present = Side("head", root), [], set()
    for path in sorted(p for p in head_set if head_tree.has_file(p)):
        try:
            if kind_of(checkout, path) == "file":
                present.add(path)
        except InputReadError:
            findings.append(f"{path}: sentry test file cannot be read at head")
            present.add(path)
    head_set = present
    gone = sorted(base_set - head_set)
    if not gone:
        return findings
    renamed = _renames(root, tree.sha)
    return findings + [
        f"{path}: sentry test file was removed without a rename inside the sentry set "
        "or a fresh [retired_files] decision"
        for path in gone
        if path not in retired_files and renamed.get(path) not in head_set
    ]


def _renames(root: Path, sha: str) -> dict[str, str]:
    raw = _git(root, "the rename list", "diff", "-M", "--name-status", "-z", sha, "HEAD").split(
        b"\0"
    )
    out: dict[str, str] = {}
    i = 0
    while i < len(raw) and raw[i]:
        status = raw[i].decode()
        if status.startswith("R") and i + 2 < len(raw):
            out[raw[i + 1].decode("utf-8", "surrogateescape")] = raw[i + 2].decode(
                "utf-8", "surrogateescape"
            )
            i += 3
        else:
            i += 2
    return out
