"""AST scan for the source-read boundary: every Arrow-to-pandas conversion and pandas file read.

A site is any reference (a call, or a value handed on) to `<anything>.to_pandas`, to a
`pandas.read_*` function however it was imported or aliased, or to the file-access adapter's
`read_parquet`. The conversion choke point (`internal/pandas_compat.py`) is exempt by exact
`(path, function)`; every other site must be in `allowlist.toml` with a reason and a count.
No pytest import, so a script can run it.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from tests.sentry._retry_scan import (
    PKG,
    canonical,
    dotted,
    import_bindings,
    package_of,
    rel,
    walk_with_scope,
)

_PANDAS_READ = re.compile(r"^pandas(\.io(\.\w+)*)?\.read_\w+$")
ADAPTER_READ_PARQUET = "decoy_engine.fileaccess.adapters.pandas.read_parquet"
TO_PANDAS = "<arrow>.to_pandas"

CHOKE_POINT = frozenset(
    {
        ("internal/pandas_compat.py", "arrow_to_frame"),
        ("internal/pandas_compat.py", "arrow_to_series"),
    }
)


@dataclass(frozen=True)
class Hit:
    path: str
    function: str
    target: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.path, self.function, self.target)


def scan_source(source: str, relpath: str) -> list[Hit]:
    """The sites in one module, the choke point's own functions left out."""
    tree = ast.parse(source)
    bindings = import_bindings(tree, package_of(relpath))
    hits: list[Hit] = []
    for node, scope, _parents in walk_with_scope(tree):
        target = None
        if isinstance(node, ast.Attribute) and node.attr == "to_pandas":
            target = TO_PANDAS
        elif isinstance(node, (ast.Attribute, ast.Name)):
            name = dotted(node)
            resolved = canonical(name, bindings) if name else ""
            if resolved.endswith(".to_pandas") or resolved == "to_pandas":
                target = TO_PANDAS
            elif _PANDAS_READ.match(resolved) or resolved == ADAPTER_READ_PARQUET:
                target = resolved
        if target is not None and (relpath, scope) not in CHOKE_POINT:
            hits.append(Hit(relpath, scope, target))
    return hits


def scan_tree() -> list[Hit]:
    hits: list[Hit] = []
    for path in sorted(PKG.rglob("*.py")):
        hits.extend(scan_source(path.read_text(encoding="utf-8"), rel(path)))
    return hits


def problems(hits: list[Hit], allowed: Counter[tuple[str, str, str]]) -> list[str]:
    """Site keys that are not allowed, or whose count differs. A key names code, never data."""
    found = Counter(hit.key for hit in hits)
    out = [f"unlisted site {'::'.join(k)} x{n}" for k, n in found.items() if k not in allowed]
    out += [
        f"allowlist count differs {'::'.join(k)}: allowed {n}, found {found.get(k, 0)}"
        for k, n in allowed.items()
        if found.get(k, 0) != n
    ]
    return sorted(out)


def package_path(relpath: str) -> Path:
    return PKG / relpath
