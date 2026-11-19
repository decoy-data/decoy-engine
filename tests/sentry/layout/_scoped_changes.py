"""Function-scoped permission for a file the physical-seam sentry otherwise forbids changing.

`test_physical_seam_disconnection` lists whole files under `execution/` that may differ from the
branch point. A scoped entry replaces a whole-file entry: the file may change only in the
top-level units named here, each with the reason (owner decision Q13 of the Windows plan,
2026-11-18). A unit is an import group, a function or class, an assignment, or an `if` at
module level keyed by its test. Any other changed unit fails. The (file, unit) pairs are
registered in the shrink-only `physical-seam-scoped` baseline, so the table cannot grow.
"""

from __future__ import annotations

import ast

_ISOLATED_COMMON = "src/decoy_engine/execution/_isolated_common.py"
_WHY = (
    "owns the POSIX `resource` import or a signal read that Windows lacks; EW1 of the Windows "
    "plan routes it through `_osflags` so the engine imports there"
)

# (file, unit) -> reason. Shrink-only through the `physical-seam-scoped` baseline.
SCOPED_EXCEPTIONS: dict[tuple[str, str], str] = {
    (_ISOLATED_COMMON, "imports"): _WHY,
    (_ISOLATED_COMMON, "RLIMIT_KINDS"): _WHY,
    (_ISOLATED_COMMON, "if:not _osflags.WINDOWS"): _WHY,
    (_ISOLATED_COMMON, "peak_rss_mb"): _WHY,
    (_ISOLATED_COMMON, "apply_mem_cap"): _WHY,
    (_ISOLATED_COMMON, "abnormal_exit_reason"): _WHY,
    (_ISOLATED_COMMON, "classify_abnormal_exit"): _WHY,
}


def scoped_units() -> dict[str, frozenset[str]]:
    """The permitted changed units of each scoped file."""
    out: dict[str, set[str]] = {}
    for rel, unit in SCOPED_EXCEPTIONS:
        out.setdefault(rel, set()).add(unit)
    return {rel: frozenset(units) for rel, units in out.items()}


def _is_import_only(stmt: ast.stmt) -> bool:
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        return True
    return isinstance(stmt, ast.Try) and all(
        isinstance(s, (ast.Import, ast.ImportFrom)) for s in stmt.body
    )


def _units(source: str) -> dict[str, str]:
    units: dict[str, list[str]] = {}
    for n, stmt in enumerate(ast.parse(source).body):
        if _is_import_only(stmt):
            key = "imports"
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            key = stmt.name
        elif isinstance(stmt, ast.Assign):
            key = ",".join(ast.unparse(t) for t in stmt.targets)
        elif isinstance(stmt, ast.AnnAssign):
            key = ast.unparse(stmt.target)
        elif isinstance(stmt, ast.If):
            key = f"if:{ast.unparse(stmt.test)}"
        else:
            key = f"stmt:{n}"
        units.setdefault(key, []).append(ast.dump(stmt))
    return {key: "\n".join(dumps) for key, dumps in units.items()}


def changed_units(old: str, new: str) -> set[str]:
    """Top-level units that differ, appear or disappear between two versions of a module."""
    before, after = _units(old), _units(new)
    return {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
