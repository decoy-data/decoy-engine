"""Sentry: the engine imports and opens files on Windows (Windows plan D1, EW1).

An AST walk of every engine module, import aliases normalized, fails on a POSIX-only name that
Windows lacks. Rules: `os-flag` an `os.O_*` read outside `_osflags.py`, at module or function
scope; `posix-import` a module-scope `import resource|fcntl|pwd|grp|termios` outside a
`try`/`except ImportError`; `signal` a `signal.SIG*` name Windows lacks; `fchmod`
`os.fchmod`; `geteuid` `os.geteuid`; `dir-fd` a `dir_fd=` keyword (also `src_dir_fd`,
`dst_dir_fd`).

A name is allowed inside the body of an `if not _osflags.WINDOWS:` branch. Until the slice that
owns a module adds that branch, its sites sit in `EXCEPTIONS` with the owner and the reason. An
entry is exact: a site more or fewer than the entry fails, so an entry only shrinks. Named limits:
a `getattr`/`hasattr` string probe is not an attribute read; scope shadowing is not modelled.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.sentry._platform_ast import (
    OSFLAGS_REL,
    SRC,
    engine_trees,
    import_map,
    not_windows_ids,
    resolve,
)

POSIX_ONLY_MODULES = frozenset({"resource", "fcntl", "pwd", "grp", "termios"})
# What `signal` defines on Windows; any other `signal.SIG*` name fails the import or the call.
WINDOWS_SIGNALS = frozenset(
    {
        "SIGABRT",
        "SIGFPE",
        "SIGILL",
        "SIGINT",
        "SIGSEGV",
        "SIGTERM",
        "SIGBREAK",
        "SIG_DFL",
        "SIG_IGN",
    }
)
DIR_FD_KEYWORDS = ("dir_fd", "src_dir_fd", "dst_dir_fd")
IMPORT_ERRORS = frozenset({"ImportError", "ModuleNotFoundError"})


OWNERS = frozenset({"permanent", "EW2", "EW3", "EW4", "EW5"})


@dataclass(frozen=True)
class Finding:
    rel: str
    line: int
    rule: str


def _handles_import_error(handler: ast.ExceptHandler) -> bool:
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(getattr(t, "id", None) in IMPORT_ERRORS for t in types)


def _module_scope_imports(tree: ast.Module) -> list[ast.stmt]:
    """Imports outside every function body and outside `try` bodies that catch ImportError."""
    out: list[ast.stmt] = []

    def walk(stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                out.append(stmt)
            elif isinstance(stmt, ast.Try):
                if not any(_handles_import_error(h) for h in stmt.handlers):
                    walk(stmt.body)
                for h in stmt.handlers:
                    walk(h.body)
                walk(stmt.orelse + stmt.finalbody)
            elif isinstance(stmt, (ast.If, ast.With, ast.ClassDef)):
                walk(stmt.body)
                if isinstance(stmt, ast.If):
                    walk(stmt.orelse)

    walk(tree.body)
    return out


def _import_roots(stmt: ast.stmt) -> list[str]:
    if isinstance(stmt, ast.Import):
        return [a.name.split(".")[0] for a in stmt.names]
    assert isinstance(stmt, ast.ImportFrom)
    return [(stmt.module or "").split(".")[0]] if stmt.level == 0 else []


def scan_source(source: str, rel: str) -> list[Finding]:
    return scan_tree(ast.parse(source), rel)


def scan_tree(tree: ast.Module, rel: str) -> list[Finding]:
    imap = import_map(tree, rel)
    safe = not_windows_ids(tree, imap)
    found: list[Finding] = []

    def add(node: ast.AST, rule: str) -> None:
        if id(node) not in safe:
            found.append(Finding(rel, getattr(node, "lineno", 0), rule))

    for stmt in _module_scope_imports(tree):
        if any(root in POSIX_ONLY_MODULES for root in _import_roots(stmt)):
            add(stmt, "posix-import")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [a.name for a in node.names]
            if node.module == "os" and any(n.startswith("O_") for n in names):
                add(node, "os-flag")
            if node.module == "os" and "fchmod" in names:
                add(node, "fchmod")
            if node.module == "os" and "geteuid" in names:
                add(node, "geteuid")
            if node.module == "signal" and any(
                n.startswith("SIG") and n not in WINDOWS_SIGNALS for n in names
            ):
                add(node, "signal")
        elif isinstance(node, ast.Attribute):
            dotted = resolve(node, imap) or ""
            if dotted.startswith("os.O_") and rel != OSFLAGS_REL:
                add(node, "os-flag")
            elif dotted == "os.fchmod":
                add(node, "fchmod")
            elif dotted == "os.geteuid":
                add(node, "geteuid")
            elif dotted.startswith("signal.SIG") and dotted[7:] not in WINDOWS_SIGNALS:
                add(node, "signal")
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in DIR_FD_KEYWORDS:
                    add(node, "dir-fd")
                    break
    return found


_FA = "decoy_engine/fileaccess/"
_GOV = "decoy_engine/execution/_governor_monitor.py"
_OOC = "decoy_engine/execution/out_of_core/_scratch.py"
_QUARANTINE = "decoy_engine/declared_casting/_quarantine_local.py"
_OPENAT2, _DURABLE, _LOCAL, _OUTPUT = (
    _FA + "_openat2.py",
    _FA + "_durable.py",
    _FA + "_local.py",
    _FA + "_output.py",
)
_PROTECTED, _SCRATCH = _FA + "_protected_dir.py", _FA + "_scratch.py"

# Sites that stay until the owning slice adds an `if not _osflags.WINDOWS` branch around them.
# (rel path, rule) -> (exact site count, owner, reason). An entry only shrinks: the table is
# registered as the `win32-import-surface` baseline, whose `max` per entry the ratchet never lets
# rise. `owner` is one of OWNERS.
EXCEPTIONS: dict[tuple[str, str], tuple[int, str, str]] = {
    (_GOV, "signal"): (
        1,
        "permanent",
        "the governor's SIGKILL belongs to the isolated route, which refuses on win32 (EW3)",
    ),
    (_OPENAT2, "dir-fd"): (
        2,
        "permanent",
        "openat2 is Linux only; its probe reports unavailable elsewhere and nothing reaches it",
    ),
    (_OPENAT2, "os-flag"): (
        9,
        "permanent",
        "openat2 is Linux only; its flags are the kernel's and are read at call time",
    ),
    (_DURABLE, "dir-fd"): (9, "EW2", "directory-descriptor fsync walk, POSIX arm lands in EW2"),
    (_DURABLE, "geteuid"): (1, "EW2", "the chain owner walk is skipped on win32 by EW2"),
    (_LOCAL, "fchmod"): (2, "EW4", "owner-only creation moves to create_owner_only_file in EW4"),
    (_OUTPUT, "dir-fd"): (
        22,
        "EW3",
        "the dir_fd stage and publication paths get a win32 arm in EW3",
    ),
    (_OUTPUT, "fchmod"): (3, "EW3", "private-file creation gets a win32 arm in EW3 and EW4"),
    (_PROTECTED, "geteuid"): (
        2,
        "EW4",
        "the POSIX owner check is the non-Windows arm; EW4 scopes it",
    ),
    (_SCRATCH, "dir-fd"): (5, "EW5", "ScratchArena gets its Windows arm in EW5"),
    (_SCRATCH, "posix-import"): (
        1,
        "EW2",
        "the fcntl import is guarded by a platform test; EW2 moves locks into _oslock",
    ),
    (_QUARANTINE, "fchmod"): (1, "EW4", "the quarantine stage gets its win32 arm in EW4"),
    (_QUARANTINE, "os-flag"): (8, "EW4", "the quarantine stage opens move to _osflags in EW4"),
    (_OOC, "fchmod"): (1, "EW5", "out-of-core scratch routes through the arena in EW5"),
    (_OOC, "os-flag"): (5, "EW5", "out-of-core scratch routes through the arena in EW5"),
}


def engine_findings(src: Path = SRC) -> list[Finding]:
    out: list[Finding] = []
    for rel, tree in engine_trees(src).items():
        out.extend(scan_tree(tree, rel))
    return out


def table_drift(
    found: list[Finding], table: dict[tuple[str, str], tuple[int, str, str]]
) -> list[str]:
    counts: dict[tuple[str, str], int] = {}
    for f in found:
        counts[(f.rel, f.rule)] = counts.get((f.rel, f.rule), 0) + 1
    out = []
    for key in sorted(counts.keys() | table.keys()):
        want = table[key][0] if key in table else 0
        if counts.get(key, 0) != want:
            out.append(f"{key[0]} {key[1]}: table {want}, observed {counts.get(key, 0)}")
    return out


def test_engine_surface_matches_the_exception_table() -> None:
    bad = table_drift(engine_findings(), EXCEPTIONS)
    assert not bad, "a POSIX-only name outside `_osflags` and the exception table:\n" + "\n".join(
        bad
    )


def test_every_exception_names_an_owner_and_a_reason() -> None:
    for key, (count, owner, reason) in EXCEPTIONS.items():
        assert count > 0 and owner in OWNERS and len(reason) > 20, key


def test_only_the_ml_stack_module_imports_lightgbm() -> None:
    """The sklearn-before-lightgbm order lives in one helper; nothing else imports lightgbm."""
    owner = "decoy_engine/profiling/model_pack/_mlstack.py"
    for rel, tree in engine_trees(SRC).items():
        for node in ast.walk(tree):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom) and node.level == 0
                else []
            )
            assert rel == owner or not any(n.split(".")[0] == "lightgbm" for n in names), rel


SEEDS = {
    "function_scope_flag": (
        "import os\n\n\ndef f(p):\n    return os.open(p, os.O_NOFOLLOW)\n",
        "os-flag",
    ),
    "module_scope_flag": ("import os\n\nFLAGS = os.O_DIRECTORY\n", "os-flag"),
    "aliased_os": ("import os as o\n\n\ndef f():\n    return o.O_CLOEXEC\n", "os-flag"),
    "from_import_flag": ("from os import O_DIRECTORY\n", "os-flag"),
    "aliased_fcntl": ("import fcntl as f\n", "posix-import"),
    "from_resource": ("from resource import RLIMIT_AS\n", "posix-import"),
    "fchmod": ("import os\n\n\ndef f(fd):\n    os.fchmod(fd, 0o600)\n", "fchmod"),
    "geteuid": ("import os\n\n\ndef f():\n    return os.geteuid()\n", "geteuid"),
    "dir_fd": (
        "import os\n\n\ndef f(p, flags, d):\n    return os.open(p, flags, dir_fd=d)\n",
        "dir-fd",
    ),
    "sigkill": ("import signal\n\n\ndef f():\n    return signal.SIGKILL\n", "signal"),
    "from_signal": ("from signal import SIGKILL\n", "signal"),
}


@pytest.mark.parametrize("seed", sorted(SEEDS))
def test_seeded_case_is_caught(seed: str) -> None:
    source, rule = SEEDS[seed]
    assert {f.rule for f in scan_source(source, "decoy_engine/seeded.py")} == {rule}


CONTROLS = {
    "guarded_import": "try:\n    import fcntl\nexcept ImportError:\n    fcntl = None\n",
    "function_scope_import": "def f():\n    import fcntl\n    return fcntl\n",
    "windows_signal": "import signal\n\n\ndef f():\n    return signal.SIGTERM\n",
    "signal_defaults": (
        "import signal\n\n\ndef f():\n    return (signal.SIG_DFL, signal.SIG_IGN)\n"
    ),
    "string_probe": 'import os\n\n\ndef f():\n    return hasattr(os, "O_NOFOLLOW")\n',
    "if_not_windows": (
        "import os\n"
        "from decoy_engine.fileaccess import _osflags\n\n\n"
        "def f(fd):\n"
        "    if not _osflags.WINDOWS:\n"
        "        os.fchmod(fd, 0o600)\n"
    ),
    "if_not_windows_relative_from_import": (
        "import os\n"
        "from ._osflags import WINDOWS\n\n\n"
        "def f(fd):\n"
        "    if not WINDOWS:\n"
        "        os.fchmod(fd, 0o600)\n"
    ),
    "if_not_windows_relative_module_import": (
        "import os\n"
        "from . import _osflags\n\n\n"
        "def f(fd):\n"
        "    if not _osflags.WINDOWS:\n"
        "        os.fchmod(fd, 0o600)\n"
    ),
    "if_not_windows_from_import": (
        "import os\n"
        "from decoy_engine.fileaccess._osflags import WINDOWS as W\n\n\n"
        "def f(p, d):\n"
        "    if not W:\n"
        "        return os.open(p, 0, dir_fd=d)\n"
    ),
}


@pytest.mark.parametrize("control", sorted(CONTROLS))
def test_seeded_control_passes(control: str) -> None:
    assert scan_source(CONTROLS[control], "decoy_engine/fileaccess/seeded.py") == []


def test_a_posix_name_in_the_windows_branch_is_still_caught() -> None:
    source = (
        "import os\n"
        "from decoy_engine.fileaccess import _osflags\n\n\n"
        "def f(fd):\n"
        "    if _osflags.WINDOWS:\n"
        "        os.fchmod(fd, 0o600)\n"
    )
    assert [f.rule for f in scan_source(source, "decoy_engine/seeded.py")] == ["fchmod"]


def test_osflags_itself_may_read_os_flags() -> None:
    assert scan_source("import os\nX = os.O_NOFOLLOW\n", OSFLAGS_REL) == []
