"""Resolves a draw-site catalogue reference of the form `path::qualified_function[#n]`.

A reference names a module under `src/decoy_engine`, a function in it (`Class.method` for a
method) and, when more than one catalogued draw lives in one function, the ordinal `#n` of the
draw token in that function's body. Resolution reads the source with `ast`, so a moved line
changes nothing and a renamed or deleted function fails. Messages carry module paths and
function names only.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

# RNG constructors, Faker.seed_instance, the whole-column numpy ops, and the Mimesis Generic()
# seeded constructor. Prose is stripped before matching (see strip_prose) so a docstring mention
# of `derive(...)` does not count.
DRAW_TOKEN = re.compile(
    r"np\.random\.default_rng\(|np\.random\.RandomState\(|random\.Random\(|"
    r"\.seed_instance\(|\.permutation\(|\.shuffle\(|\.choices\(|"
    r"derive_index\(|derive_value\(|\bderive\(|Generic\("
)

# A catalogued function may reach the keyed primitive through an alias or a helper (a
# `derive_func` parameter, `DeriveContext.derive_sources`, `hmac_hex`, a batch kernel), so the
# per-entry check also counts those spellings. The tree-wide scan keeps the narrower DRAW_TOKEN.
ENTRY_DRAW_TOKEN = re.compile(
    DRAW_TOKEN.pattern
    + r"|\bderive_sources?\(|\bderive_func\(|\bhmac_hex\(|\w*hmac\w*\.new\(|"
    + r"derive_index_batch\(|\bpositional_pool_indices\(|\.sample\(|\.integers\(|\.random\("
)

_TRIPLE_QUOTED = re.compile(r"(\"\"\".*?\"\"\"|'''.*?''')", re.DOTALL)
_REFERENCE = re.compile(r"(?P<path>[\w/]+\.py)::(?P<qual>\w+(?:\.\w+)*)(?:#(?P<n>[1-9]\d*))?\Z")


def strip_prose(text: str) -> str:
    """Remove triple-quoted blocks and line comments so the scan matches code.

    Bare `derive(` also appears in docstrings and comments describing the keyed primitive;
    stripping prose keeps the scan matching real call sites, not documentation. Single-line
    string literals are intentionally left in (a handful are handled by the allowlist), since
    removing them reliably needs a real tokenizer.
    """
    without_docstrings = _TRIPLE_QUOTED.sub("", text)
    return "\n".join(re.sub(r"#.*$", "", line) for line in without_docstrings.splitlines())


class Reference(NamedTuple):
    path: str
    qualified: str
    ordinal: int | None

    @property
    def base(self) -> str:
        return f"{self.path}::{self.qualified}"


def parse(reference: str) -> Reference:
    match = _REFERENCE.match(reference)
    if match is None:
        raise ValueError(f"call site {reference!r} is not path::function[#n]")
    n = match.group("n")
    return Reference(match.group("path"), match.group("qual"), int(n) if n else None)


def _functions(tree: ast.AST) -> Iterable[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    def walk(node: ast.AST, prefix: tuple[str, ...]) -> Iterable[tuple[str, ast.AST]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names = (*prefix, child.name)
                if not isinstance(child, ast.ClassDef):
                    yield ".".join(names), child
                yield from walk(child, names)
            else:
                yield from walk(child, prefix)

    return walk(tree, ())  # type: ignore[return-value]


def body_token_count(package_dir: Path, ref: Reference) -> int:
    """Draw tokens in the referenced function's body. Raises LookupError if it is missing."""
    path = package_dir / ref.path
    if not path.is_file():
        raise LookupError(f"module {ref.path} does not exist")
    text = path.read_text(encoding="utf-8")
    for qualified, node in _functions(ast.parse(text)):
        if qualified == ref.qualified:
            lines = text.splitlines()[node.lineno - 1 : node.end_lineno]
            return len(ENTRY_DRAW_TOKEN.findall(strip_prose("\n".join(lines))))
    raise LookupError(f"function {ref.qualified} does not exist in {ref.path}")


def function_source(package_dir: Path, ref: Reference) -> str:
    """The referenced function's source text (for tests that look for a call in it)."""
    text = (package_dir / ref.path).read_text(encoding="utf-8")
    for qualified, node in _functions(ast.parse(text)):
        if qualified == ref.qualified:
            return "\n".join(text.splitlines()[node.lineno - 1 : node.end_lineno])
    raise LookupError(f"function {ref.qualified} does not exist in {ref.path}")


def problems(package_dir: Path, sites: Iterable[object]) -> list[str]:
    """Every defect in the catalogue's references, as `draw_site_id: reason` lines."""
    found: list[str] = []
    claimed: dict[str, dict[str, set[int | None]]] = defaultdict(lambda: defaultdict(set))
    for site in sites:
        sid = site.draw_site_id  # type: ignore[attr-defined]
        refs = (site.call_site, *site.mirror_call_sites)  # type: ignore[attr-defined]
        drawing = False
        for raw in refs:
            try:
                ref = parse(raw)
                count = body_token_count(package_dir, ref)
            except (ValueError, LookupError) as exc:
                found.append(f"{sid}: {exc}")
                continue
            claimed[ref.base][sid].add(ref.ordinal)
            if ref.ordinal is not None and count < ref.ordinal:
                found.append(f"{sid}: {ref.base}#{ref.ordinal} has only {count} draw tokens")
            elif count:
                drawing = True
        if not drawing:
            found.append(f"{sid}: no referenced function holds a draw token")
    for base, by_site in claimed.items():
        if len(by_site) > 1:
            ordinals = [o for ords in by_site.values() for o in ords]
            if None in ordinals or len(ordinals) != len(set(ordinals)):
                found.append(f"{base}: shared by {sorted(by_site)} without distinct #n")
    return found
