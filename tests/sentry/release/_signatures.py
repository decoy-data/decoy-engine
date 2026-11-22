"""Signature sentry helper: public API breaks against the last release tag, joined to Breaking lines.

Griffe says what broke (`find_breaking_changes` over two static trees). The stability registry says
which names are public. `stamp_release` says what a Breaking line is. This module only joins them;
`test_public_signatures.py` holds the rules and the acceptance tests. Types and constant values are
out of scope (plan N1, N2). The base tree is a `git archive` extract, never `griffe.load_git`, so a
run writes nothing into the shared `.git`.
"""

from __future__ import annotations

import ast
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import griffe
from griffe import BreakageKind as K
from scripts.release import stamp_release as sr

FROZEN, EXPERIMENTAL, INTERNAL = "frozen", "experimental", "internal"
IN_SCOPE_TIERS = frozenset({FROZEN, EXPERIMENTAL})

IN_SCOPE_KINDS = frozenset(
    {
        K.PARAMETER_MOVED,
        K.PARAMETER_REMOVED,
        K.PARAMETER_CHANGED_KIND,
        K.PARAMETER_CHANGED_DEFAULT,
        K.PARAMETER_CHANGED_REQUIRED,
        K.PARAMETER_ADDED_REQUIRED,
        K.OBJECT_REMOVED,
        K.OBJECT_CHANGED_KIND,
        K.CLASS_REMOVED_BASE,
    }
)
# Annotation text and constant values: owned by other gates (plan N1, N2).
EXCLUDED_KINDS = frozenset(
    {K.RETURN_CHANGED_TYPE, K.ATTRIBUTE_CHANGED_TYPE, K.ATTRIBUTE_CHANGED_VALUE}
)

NO_TAG_MESSAGE = "signature sentry needs the release tags: fetch with tags"
_TAG_GLOB = "v[0-9]*.[0-9]*.[0-9]*"
_TICKED = re.compile(r"`([^`\n]+)`")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_H2 = re.compile(r"^## \[", re.M)

Tiers = dict[tuple[str, str], str]


@dataclass(frozen=True)
class Break:
    public_names: tuple[str, ...]
    kind: K
    parameters: tuple[str, ...]
    path: str
    also: tuple[str, ...] = ()  # the other half of a rename: naming either announces both

    def line(self) -> str:
        params = f" ({', '.join(self.parameters)})" if self.parameters else ""
        return f"{self.public_names[0]}: {self.kind.value}{params}"


@dataclass(frozen=True)
class Exemption:
    """A reviewed false break (plan B8). Inert once the base tag differs from `base_tag`."""

    base_tag: str
    path: str
    kind: str  # BreakageKind name
    parameter: str
    reason: str


# Starts empty. Each row is a reviewed diff in the PR that adds it, removed after the next tag.
SIGNATURE_EXEMPTIONS: tuple[Exemption, ...] = ()


@dataclass
class Scope:
    paths: dict[str, set[str]] = field(default_factory=dict)  # griffe path -> bare public names
    unresolved: list[str] = field(default_factory=list)
    mapped: int = 0  # in-scope census names that resolved


def _git(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(  # noqa: S603 - fixed git executable, literal arguments
        ["git", "-C", str(repo), *args],  # noqa: S607
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(NO_TAG_MESSAGE if args[0] == "describe" else f"git {args[0]} failed")
    return proc.stdout


def base_tag(repo: Path) -> str:
    """The newest release tag reachable from HEAD. Read once; every later step gets this value."""
    out = _git(repo, "describe", "--tags", "--abbrev=0", "--match", _TAG_GLOB, "HEAD")
    return out.decode().strip()


def extract_base(repo: Path, tag: str, dest: Path) -> Path:
    """`src/` of `tag` extracted under `dest`; returns the directory that holds `src`."""
    dest.mkdir(parents=True, exist_ok=True)
    archive = _git(repo, "archive", tag, "src")
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, check=True)  # noqa: S603, S607
    return dest


def load_tree(src_root: Path, package: str) -> Any:
    return griffe.load(
        package,
        search_paths=[src_root],
        resolve_aliases=True,
        resolve_external=False,
        allow_inspection=False,
    )


# --- tiers read from a stability.py without importing it ---------------------------------------


def _literal(node: ast.expr, names: dict[str, Any]) -> Any:
    """Constants, literal containers and the tier names only; anything else fails closed."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in names:
        return names[node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(_literal(e, names) for e in node.elts)
    if isinstance(node, ast.Dict) and None not in node.keys:
        return {
            _literal(k, names): _literal(v, names)  # type: ignore[arg-type]
            for k, v in zip(node.keys, node.values, strict=True)
        }
    raise ValueError(f"stability registry uses a non-literal expression ({type(node).__name__})")


@dataclass(frozen=True)
class Registry:
    package_tiers: dict[str, str]
    exceptions: dict[tuple[str, str], str]
    experimental_module: str
    experimental_objects: frozenset[tuple[str, str]]


def parse_stability(source: str) -> Registry:
    assigned: dict[str, ast.expr] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if isinstance(target, ast.Name):
            assigned[target.id] = value
    tier_names: dict[str, Any] = {
        n: _literal(assigned[n], {})
        for n in ("FROZEN", "EXPERIMENTAL", "INTERNAL")
        if n in assigned
    }
    wanted = ("PACKAGE_TIERS", "TIER_EXCEPTIONS", "EXPERIMENTAL_MODULE", "EXPERIMENTAL_OBJECTS")
    missing = [n for n in wanted if n not in assigned]
    if missing:
        raise ValueError(f"stability registry lacks {missing}")
    got = {n: _literal(assigned[n], tier_names) for n in wanted}
    return Registry(
        package_tiers=got["PACKAGE_TIERS"],
        exceptions={(m, n): t for m, n, t in got["TIER_EXCEPTIONS"]},
        experimental_module=got["EXPERIMENTAL_MODULE"],
        experimental_objects=frozenset(got["EXPERIMENTAL_OBJECTS"]),
    )


def _public_modules(tree: Any) -> list[Any]:
    out = [tree]

    def walk(mod: Any) -> None:
        for name, member in mod.members.items():
            if name.startswith("_") or member.is_alias or not member.is_module:
                continue
            out.append(member)
            walk(member)

    walk(tree)
    return out


def _target_path(obj: Any) -> str:
    try:
        return obj.final_target.path if obj.is_alias else obj.path
    except Exception:
        return obj.path


def tiers_from_tree(tree: Any, stability_source: str) -> Tiers:
    """`(module, name) -> tier` for a tree that cannot be imported: the census rules, statically."""
    reg = parse_stability(stability_source)
    pkg = tree.path
    always = (pkg, f"{pkg}.sdk", f"{pkg}.providers")
    exports: list[tuple[str, str, str]] = []  # module, name, target path
    for mod in _public_modules(tree):
        if mod.exports is None and mod.path not in always:
            continue
        for raw in mod.exports or ():
            name = str(raw)
            member = mod.members.get(name)
            exports.append(
                (mod.path, name, _target_path(member) if member else f"{mod.path}.{name}")
            )

    def experimental(target: str) -> bool:
        return target.rsplit(".", 1)[0] == reg.experimental_module or any(
            target == f"{m}.{q}" for m, q in reg.experimental_objects
        )

    frozen_targets = {
        t
        for m, n, t in exports
        if not experimental(t)
        and (
            reg.exceptions.get((m, n)) == FROZEN
            or ((m, n) not in reg.exceptions and reg.package_tiers.get(m) == FROZEN)
        )
    }
    out: Tiers = {}
    for module, name, target in exports:
        if (module, name) in reg.exceptions:
            tier = reg.exceptions[(module, name)]
        elif experimental(target):
            tier = EXPERIMENTAL
        elif target in frozen_targets:
            tier = FROZEN
        else:
            tier = reg.package_tiers.get(module, INTERNAL)
        out[(module, name)] = tier
    return out


# --- scope -------------------------------------------------------------------------------------


def _lookup(tree: Any, spelling: str) -> Any:
    rel = spelling.removeprefix(tree.path + ".") if spelling != tree.path else ""
    return tree[rel] if rel else tree


def scope(base_tree: Any, head_tree: Any, base_tiers: Tiers, head_tiers: Tiers) -> Scope:
    """Griffe paths of every name FROZEN or EXPERIMENTAL at the base or at HEAD (B3, B3a)."""
    out = Scope()
    sides = ((base_tree, base_tiers), (head_tree, head_tiers))
    union = {k for _, tiers in sides for k, t in tiers.items() if t in IN_SCOPE_TIERS}
    for module, name in sorted(union):
        spelling = f"{module}.{name}"
        resolved = False
        for tree, tiers in sides:
            in_scope = tiers.get((module, name)) in IN_SCOPE_TIERS
            try:
                paths = {spelling, _target_path(_lookup(tree, spelling))}
            except Exception:
                if in_scope:  # a name in scope on this side must resolve on this side
                    out.unresolved.append(f"{spelling} ({'base' if tree is base_tree else 'head'})")
                continue
            resolved = resolved or in_scope
            for path in paths:
                out.paths.setdefault(path, set()).add(name)
        out.mapped += resolved
    return out


# --- breaks ------------------------------------------------------------------------------------


def _scope_names(path: str, sc: Scope) -> set[str]:
    parts = path.split(".")
    names: set[str] = set()
    for i in range(len(parts), 0, -1):
        names |= sc.paths.get(".".join(parts[:i]), set())
    return names


def _param_names(b: Any) -> tuple[str, ...]:
    if not b.kind.name.startswith("PARAMETER_"):
        return ()
    found: list[str] = []
    for v in (b.old_value, b.new_value):
        name = getattr(v, "name", None)
        if isinstance(name, str) and name not in found:
            found.append(name)
    return tuple(found)


def signature_breaks(base_tree: Any, head_tree: Any, sc: Scope) -> list[Break]:
    seen: set[tuple[str, K, tuple[str, ...]]] = set()
    found: list[Break] = []
    for b in griffe.find_breaking_changes(base_tree, head_tree):
        if b.kind not in IN_SCOPE_KINDS:
            continue
        names = _scope_names(b.obj.path, sc)
        key = (b.obj.path, b.kind, _param_names(b))
        if not names or key in seen:
            continue
        seen.add(key)
        found.append(Break(tuple(sorted(names)), b.kind, key[2], b.obj.path))
    return _pair_renames(found)


def _pair_renames(found: list[Break]) -> list[Break]:
    """One parameter removed and one required parameter added on one object: a rename (L8)."""
    by_path: dict[str, list[Break]] = defaultdict(list)
    for b in found:
        by_path[b.path].append(b)
    out = []
    for b in found:
        removed = [x for x in by_path[b.path] if x.kind is K.PARAMETER_REMOVED]
        added = [x for x in by_path[b.path] if x.kind is K.PARAMETER_ADDED_REQUIRED]
        if len(removed) == 1 and len(added) == 1 and b in (removed[0], added[0]):
            other = added[0] if b is removed[0] else removed[0]
            b = Break(b.public_names, b.kind, b.parameters, b.path, other.parameters)
        out.append(b)
    return out


# --- Breaking text -----------------------------------------------------------------------------


def _bullets(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        if raw.startswith("- "):
            out.append(raw[2:].strip())
        elif raw.strip() and out:
            out[-1] += " " + raw.strip()
    return out


def refuse_unreleased_breaking(changelog: str) -> None:
    """A Breaking list under `[Unreleased]` is never read: fragments are the one pending place."""
    start = changelog.find("## [Unreleased]")
    if start == -1:
        return
    after = start + len("## [Unreleased]")
    nxt = _H2.search(changelog, after)
    if sr.breaking_lists(changelog[after : nxt.start() if nxt else len(changelog)])[1]:
        raise AssertionError(
            "a 'Breaking for consumers' list under [Unreleased]: put the Breaking line in a "
            "changelog.d fragment"
        )


def pending_breaking_lines(root: Path, base_version: str) -> list[str]:
    """One entry per Breaking line: fragments at HEAD, then release sections newer than the base."""
    lines: list[str] = []
    folder = root / sr.FRAGMENT_DIR
    if folder.is_dir():
        for p in sorted(folder.iterdir()):
            if sr.is_fragment_name(p.name):
                frag = sr.parse_fragment(p.read_text(encoding="utf-8"))
                if frag.breaking:
                    lines.append(frag.breaking)
    changelog = root / sr.CHANGELOG
    if changelog.is_file():
        text = changelog.read_text(encoding="utf-8")
        refuse_unreleased_breaking(text)
        for version, section in sr.release_sections(text):
            if version == base_version:
                break
            for block in sr.breaking_lists(section)[1]:
                lines += _bullets(block)
    return lines


def announces(line: str, b: Break) -> bool:
    """One Breaking line names the object and, for a parameter break, the parameter (B5)."""
    ticked = [t.strip() for t in _TICKED.findall(line) if _IDENT.fullmatch(t.strip())]
    if not any(t.rsplit(".", 1)[-1] in b.public_names for t in ticked):
        return False
    params = {*b.parameters, *b.also}
    return not params or bool(params & set(ticked))


def _exempt(b: Break, exemptions: tuple[Exemption, ...], tag: str) -> bool:
    return any(
        e.base_tag == tag
        and e.path == b.path
        and e.kind == b.kind.name
        and (e.parameter == "" or e.parameter in b.parameters)
        for e in exemptions
    )


def unannounced(
    breaks: list[Break], lines: list[str], exemptions: tuple[Exemption, ...], tag: str
) -> list[Break]:
    return [
        b
        for b in breaks
        if not _exempt(b, exemptions, tag) and not any(announces(line, b) for line in lines)
    ]
