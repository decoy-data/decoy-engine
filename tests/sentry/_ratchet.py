"""Shared shrink-only ratchet logic for sentry baselines (stdlib plus tomllib).

A baseline is a JSON file ``{"sentry_id", "created_in", "entries": {key: {"reason"}}}``
under ``tests/sentry/baselines/``. ``scripts/dev/sentry_registry.toml`` binds each sentry id to
exactly one baseline path. ``check`` compares the working tree with a base commit and returns
findings; an empty list means the ratchet holds. Baseline keys compare exactly, except the
``permitted::<file>::<site>::<digest>`` keys of the sentries in ``REKEY_PER_SITE``, which
compare by count per site (see ``growth``). An entry that carries a numeric ``max`` may keep
or lower it, never raise or drop it (see ``max_raised``). A key of the form
``<file>.py::<qualname>::<name>`` key of a ``REHOME_BY_BINDING`` sentry may also move 1:1 to a new
entry that declares ``moved_from`` when the old site is gone from the source (see ``rehomes``).
Messages carry ids, paths and keys only.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

REGISTRY = "scripts/dev/sentry_registry.toml"
BASELINE_DIR = "tests/sentry/baselines"
MIN_REASON = 15
DECISION = re.compile(r"^owner \d{4}-\d{2}-\d{2} .{10,}$")
_GLOB_CHARS = frozenset("*?[]")
PLACEHOLDERS = frozenset({"todo", "tbd", "fixme", "xxx", "n/a", "none"})
# Only sentries whose last key segment is a message digest may re-key; for any other sentry a
# changed last segment can mean a different permitted thing, so it compares exactly.
REKEY_PER_SITE = frozenset({"validation-name-messages"})
# Only these sentries may move a key to a new home, and only by a declared ``moved_from``. Their
# keys are ``<file under src/>::<qualname>::<name>``, optionally followed by ``::<ordinal>`` (the
# call sites of one method in one function); other sentries use other key shapes (src-relative
# paths) for which "the old site is gone" cannot be proven.
REHOME_BY_BINDING = frozenset({"secret-material-census", "gcs-call-kwargs"})


# The registry row schema of this repo; a key outside it fails (``closed_keys``).
ROW_KEYS = frozenset({"id", "baseline", "approved_growth"})
_HELPERS: dict[Path, ModuleType] = {}


def _integrity() -> ModuleType:
    """The integrity helpers beside this file, loaded by path so an extracted copy of the checker
    uses its own helpers and never the head's."""
    path = Path(__file__).resolve().parent / "ratchet" / "_integrity.py"
    if path not in _HELPERS:
        spec = importlib.util.spec_from_file_location(f"_ratchet_integrity_{len(_HELPERS)}", path)
        if spec is None or spec.loader is None:
            raise ImportError(path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        _HELPERS[path] = mod
    return _HELPERS[path]


@dataclass(frozen=True)
class Registry:
    """A registry that passed ``load_side``: the document, ``{id: path}`` and the approvals."""

    doc: dict[str, Any]
    paths: dict[str, str]
    approvals: dict[str, dict[str, str]]


@dataclass(frozen=True)
class Baseline:
    sentry_id: str
    created_in: str
    keys: frozenset[str]
    reasons: dict[str, object]


def parse_registry(doc: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """``{id: path}`` and findings for duplicate ids or shared paths, from a validated registry."""
    rows = doc.get("sentry", [])
    out: dict[str, str] = {}
    findings: list[str] = []
    for row in rows:
        sid, path = row["id"], row["baseline"]
        if sid in out:
            findings.append(f"registry: sentry id {sid} appears twice")
        out[sid] = path
    for path in sorted({p for p in out.values()}):
        ids = sorted(i for i, p in out.items() if p == path)
        if len(ids) > 1:
            findings.append(f"registry: two sentries ({', '.join(ids)}) share baseline {path}")
        if not _integrity().safe_path(path, BASELINE_DIR):
            findings.append(
                f"registry: baseline {path} is outside {BASELINE_DIR}/ or not a plain relative path"
            )
    return out, findings


def _decision_ok(decision: object) -> bool:
    """A dated owner decision: the whole string matches and the date is a real calendar day."""
    if not isinstance(decision, str) or not DECISION.fullmatch(decision):
        return False
    try:
        date.fromisoformat(decision.split(" ", 2)[1])
    except ValueError:
        return False
    return True


def parse_approvals(doc: dict[str, Any]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """``{sentry id: {key: decision}}`` from ``approved_growth`` rows, and findings for bad rows.

    A row is ``{ key, decision }``; the key compares exactly (no glob or prefix) and the decision
    must name a dated owner decision. Growth of a baseline passes only through a row here.
    """
    out: dict[str, dict[str, str]] = {}
    findings: list[str] = []
    for row in doc.get("sentry", []):
        sid = row.get("id", "")
        for item in row.get("approved_growth", []):
            key = item.get("key") if isinstance(item, dict) else None
            decision = item.get("decision") if isinstance(item, dict) else None
            if not isinstance(key, str) or not key:
                findings.append(f"{sid}: approved_growth row has no key")
            elif _GLOB_CHARS & set(key):
                findings.append(f"{sid}: approved_growth key {key} is a pattern; list exact keys")
            elif decision_problem(decision):
                findings.append(
                    f"{sid}: approved_growth for {key} needs a decision "
                    f"'owner YYYY-MM-DD <reason of {MIN_REASON}+ chars>'"
                )
            else:
                out.setdefault(sid, {})[key] = decision
    return out, findings


def decision_problem(decision: object) -> str | None:
    """Why ``decision`` is not an acceptable owner decision, or ``None`` when it is."""
    if not _decision_ok(decision):
        return f"needs a decision 'owner YYYY-MM-DD <reason of {MIN_REASON}+ chars>'"
    if weak_reason(str(decision).split(" ", 2)[2]):
        return f"reason is empty, a placeholder or under {MIN_REASON} chars"
    return None


def parse_baseline(text: str) -> Baseline:
    data = json.loads(text)
    entries = data.get("entries", {})
    created = data.get("created_in")
    return Baseline(
        str(data.get("sentry_id", "")),
        created if isinstance(created, str) else "",
        frozenset(entries),
        entries,
    )


def weak_reason(text: str) -> bool:
    """True when a reason is empty, a placeholder or under ``MIN_REASON`` chars (one predicate)."""
    text = text.strip()
    return len(text) < MIN_REASON or text.lower().strip(".!") in PLACEHOLDERS


def reason_findings(path: str, base: Baseline) -> list[str]:
    out = []
    for key in sorted(base.keys):
        entry = base.reasons[key]
        reason = entry.get("reason") if isinstance(entry, dict) else None
        if weak_reason(reason if isinstance(reason, str) else ""):
            out.append(
                f"{path}: reason for {key} is empty, a placeholder or under {MIN_REASON} chars"
            )
    return out


def _git_show(root: Path, ref: str, rel: str) -> str | None:
    res = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(root), "show", f"{ref}:{rel}"],  # noqa: S607
        capture_output=True,
        text=True,
    )
    return res.stdout if res.returncode == 0 else None


def _base_entries(tree: Any, path: str) -> dict[str, object]:
    """Entries of a baseline the base registry lists; it must exist and parse."""
    try:
        return parse_baseline(tree.require(path)).reasons
    except ValueError:
        raise _integrity().BaseReadError(path) from None


def _max_of(entry: object) -> int | None:
    value = entry.get("max") if isinstance(entry, dict) else None
    return value if isinstance(value, int) else None


def max_raised(head: object, base: object) -> bool:
    """True when a numeric ``max`` rose, or was dropped, against the base entry."""
    old, new = _max_of(base), _max_of(head)
    return old is not None and (new is None or new > old)


def permit_site(key: str) -> str | None:
    """``<file>::<site>`` of a ``permitted::<file>::<site>::<digest>`` key, else ``None``."""
    kind, _, rest = key.partition("::")
    site, sep, digest = rest.rpartition("::")
    return site if kind == "permitted" and sep and digest and "::" in site else None


def growth(
    head: frozenset[str], base: frozenset[str], per_site: bool = True
) -> tuple[frozenset[str], list[str]]:
    """Keys that count as growth over ``base``, and permit sites that were only re-keyed.

    A permitted key embeds a digest of its message, so any edit to a permitted site moves the
    key. For those keys growth is per site: a site absent from ``base`` or holding more keys than
    it did there is growth; the same count under new digests is a re-key, reported for review.
    The sentry still decides what is permitted. Every other key kind, and every key when
    ``per_site`` is false, compares exactly.
    """
    if not per_site:
        return frozenset(head - base), []

    def by_site(keys: frozenset[str]) -> dict[str, list[str]]:
        sites: dict[str, list[str]] = {}
        for key in keys:
            site = permit_site(key)
            if site is not None:
                sites.setdefault(site, []).append(key)
        return sites

    head_sites, base_sites = by_site(head), by_site(base)
    grown = {k for k in head - base if permit_site(k) is None}
    rekeyed: list[str] = []
    for site, keys in sorted(head_sites.items()):
        old = base_sites.get(site, [])
        if len(keys) > len(old):
            grown |= set(keys) - base
        elif set(keys) - base:
            rekeyed.append(site)
    return frozenset(grown), rekeyed


def _find_defs(node: ast.AST, part: str) -> list[ast.AST]:
    """Every def or class named ``part`` under ``node``, looking inside if/try/with/for blocks."""
    found: list[ast.AST] = []
    todo = list(ast.iter_child_nodes(node))
    while todo:
        child = todo.pop(0)
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if child.name == part:
                found.append(child)
            continue
        todo.extend(ast.iter_child_nodes(child))
    return found


def _qualname_nodes(tree: ast.AST, qualname: str) -> list[ast.AST]:
    nodes: list[ast.AST] = [tree]
    for part in qualname.split("."):
        nodes = [d for n in nodes for d in _find_defs(n, part)]
    return nodes


def _mentions(n: ast.AST, name: str) -> bool:
    """True when ``n`` binds or reads ``name``: a closure that only reads it still holds the site."""
    if isinstance(n, ast.arg):
        return n.arg == name
    if isinstance(n, ast.Name):
        return n.id == name
    if isinstance(n, ast.Attribute):
        return n.attr == name
    if isinstance(n, ast.alias):
        return (n.asname or n.name.partition(".")[0]) == name
    if isinstance(n, ast.MatchMapping):
        return n.rest == name
    # def, class, except-as, match capture, type-param and any later form that names itself.
    return getattr(n, "name", None) == name


def _site_parts(key: str) -> tuple[str, str, str] | None:
    """Split ``<file>::<qualname>::<name>`` with an optional all-digit ``::<ordinal>`` suffix."""
    parts = key.split("::")
    if len(parts) == 4 and parts[3].isdigit():
        parts = parts[:3]
    return (parts[0], parts[1], parts[2]) if len(parts) == 3 else None


def site_gone(root: Path, key: str, tree: Any) -> bool:
    """True when ``<file>.py::<qualname>::<name>`` is proven absent from the source tree.

    ``<file>`` is relative to ``src/``. Proof by AST: the qualified def or class is missing, or it
    is present but neither binds nor reads ``name`` (``_mentions``) in any same-named def. A
    qualname part that is not an identifier (``<lambda>``) is never proven. A missing file proves it only
    when the file existed at the base. A key of another shape, an unresolvable path, or a
    file that never existed is "not proven" and returns false.
    """
    parts = _site_parts(key)
    if parts is None or not parts[0].endswith(".py") or not parts[2].isidentifier():
        return False
    file, qualname, name = parts
    if not all(q.isidentifier() for q in qualname.split(".")):
        return False
    path = root / "src" / file
    if not path.is_file():
        return tree.has_file(f"src/{file}")
    nodes = _qualname_nodes(ast.parse(path.read_text(encoding="utf-8")), qualname)
    return not any(_mentions(n, name) for node in nodes for n in ast.walk(node))


def rehomes(
    root: Path,
    tree: Any,
    grown: frozenset[str],
    head_entries: dict[str, object],
    lost: dict[str, object],
) -> tuple[frozenset[str], list[str]]:
    """Split ``grown`` into declared 1:1 moves of ``lost`` keys, and the rest.

    A grown key is a move only when its entry names the old key in ``moved_from`` and that old
    key was lost from this baseline, is proven gone (``site_gone``), carries no numeric ``max``,
    ends in the same bound name, and is named by no other entry. Anything else stays growth.
    """
    claims: dict[str, list[str]] = {}
    for key in grown:
        entry = head_entries.get(key)
        old = entry.get("moved_from") if isinstance(entry, dict) else None
        if isinstance(old, str):
            claims.setdefault(old, []).append(key)
    remaining = set(grown)
    report: list[str] = []
    for old, keys in sorted(claims.items()):
        old_parts, new_parts = _site_parts(old), _site_parts(keys[0])
        same_name = old_parts is not None and new_parts is not None and old_parts[2] == new_parts[2]
        if len(keys) != 1 or not same_name or old not in lost or _max_of(lost[old]) is not None:
            continue
        if site_gone(root, old, tree):
            remaining.discard(keys[0])
            report.append(f"re-homed {old} -> {keys[0]} (declared in moved_from; old site gone)")
    return frozenset(remaining), report


def _fmt(keys: frozenset[str]) -> str:
    return ", ".join(sorted(keys))


def schema_waivers(raw: str | None) -> tuple[frozenset[tuple[str, str]], list[str]]:
    """Exact ``(id, field)`` pairs from a JSON list of pairs; ``None`` means no waiver input.

    Only ``ratchet_check.py --schema-waiver-env`` (the extracted base checker) passes the
    ``RATCHET_SCHEMA_WAIVER`` value here; the head run never reads the environment.
    """
    if raw is None:
        return frozenset(), []
    try:
        pairs = json.loads(raw)
        if isinstance(pairs, list) and all(
            isinstance(p, list) and len(p) == 2 and all(isinstance(x, str) for x in p)
            for p in pairs
        ):
            return frozenset((p[0], p[1]) for p in pairs), []
    except ValueError:
        pass
    return frozenset(), ["RATCHET_SCHEMA_WAIVER is not a JSON list of [id, field] pairs"]


def check(
    root: Path, base_ref: str, waiver_input: str | None = None
) -> tuple[list[str], list[str]]:
    """Return ``(findings, report_lines)`` for the tree at ``root`` against ``base_ref``."""
    helper = _integrity()
    sha = helper.resolve_commit(root, base_ref)
    if sha is None:
        return [f"base commit not found: {base_ref}"], []
    try:
        return _check(root, helper.BaseTree(root, sha), helper, waiver_input)
    except helper.BaseReadError as exc:
        return [f"cannot read {exc.what} from the {exc.side} commit"], []


def load_side(text: str, side: str, helper: ModuleType) -> tuple[Registry | None, list[str]]:
    """The one loader for the HEAD and the BASE registry; nothing else reads a raw document.

    Returns ``(None, findings)`` when the shape is unusable, otherwise the validated registry and
    the findings of its rows (duplicate ids, shared or unsafe paths, bad approvals). Any finding on
    the base raises ``BaseReadError``, because a base that is not a clean registry cannot anchor a
    comparison; on HEAD the findings are reported.
    """
    doc, problems = helper.validate_registry(text)
    if problems:
        if side == "base":
            raise helper.BaseReadError(REGISTRY)
        return None, [f"registry: {REGISTRY} {p}" for p in problems]
    paths, findings = parse_registry(doc)
    approvals, approval_findings = parse_approvals(doc)
    findings += approval_findings
    if findings and side == "base":
        raise helper.BaseReadError(REGISTRY)
    return Registry(doc, paths, approvals), findings


def _check(
    root: Path, tree: Any, helper: ModuleType, waiver_input: str | None
) -> tuple[list[str], list[str]]:
    reg_file = root / REGISTRY
    head_text = reg_file.read_text(encoding="utf-8") if reg_file.is_file() else ""
    base_text = tree.read(REGISTRY) or ""
    head_reg, findings = load_side(head_text, "head", helper)
    if head_reg is None:
        return findings, []
    base_reg_loaded, _ = load_side(base_text, "base", helper)
    assert base_reg_loaded is not None  # a base problem raised
    head_doc, head, approvals = head_reg.doc, head_reg.paths, head_reg.approvals
    base_doc, base_reg = base_reg_loaded.doc, base_reg_loaded.paths
    findings += helper.registry_present(
        len(base_doc.get("sentry", [])), reg_file.is_file(), len(head_doc.get("sentry", []))
    )
    head_dec, base_names = helper.decisions(head_doc), helper.table_names(base_doc)
    fresh = {t: helper.fresh(head_dec[t], base_names[t], decision_problem) for t in head_dec}
    waived, waiver_findings = schema_waivers(waiver_input)
    findings += waiver_findings
    # A waiver only counts for a field that carries a fresh [checker_change] decision.
    usable = frozenset(w for w in waived if w[1] in fresh["checker_change"])
    schema, waiver_report = helper.closed_keys(head_doc, ROW_KEYS, decision_problem, usable)
    findings += schema
    report: list[str] = helper.new_decisions(
        head_dec, base_names, approvals, base_reg_loaded.approvals
    )
    report += waiver_report
    safe = {sid: p for sid, p in head.items() if helper.safe_path(p, BASELINE_DIR)}

    on_disk = {p.relative_to(root).as_posix() for p in (root / BASELINE_DIR).glob("*.json")}
    for path in sorted(on_disk - set(head.values())):
        findings.append(f"{path}: baseline file is not registered in {REGISTRY}")

    loaded: dict[str, Baseline] = {}
    for sid, path in sorted(safe.items()):
        file = root / path
        if not file.exists():
            findings.append(f"{sid}: registry points at {path} but there is no baseline file")
            continue
        loaded[sid] = base = parse_baseline(file.read_text(encoding="utf-8"))
        if base.sentry_id != sid:
            findings.append(
                f"{path}: sentry_id {base.sentry_id!r} does not match registry id {sid}"
            )
        findings += reason_findings(path, base)
        findings += [
            f"{sid}: stale approved_growth, {key} is not in {path}"
            for key in sorted(set(approvals.get(sid, {})) - base.keys)
        ]
    findings += helper.new_baseline_findings(
        tree, {head[s]: b.created_in for s, b in loaded.items()}
    )

    removed = set(base_reg) - set(head)
    donors = {s: _base_entries(tree, base_reg[s]) for s in sorted(removed - fresh["retired"])}
    for sid in sorted(removed & fresh["retired"]):
        _base_entries(tree, base_reg[sid])  # a retirement still needs a readable base baseline
    successors: dict[str, dict[str, object]] = {}
    for sid, base in sorted(loaded.items()):
        path = head[sid]
        report.append(f"{sid}: {len(base.keys)} key(s) in {path}")
        if sid in base_reg:
            if base_reg[sid] != path:
                findings.append(f"{sid}: baseline moved from {base_reg[sid]} to {path}")
                continue
            old = _base_entries(tree, path)
            grown, rekeyed = growth(base.keys, frozenset(old), sid in REKEY_PER_SITE)
            report += [
                f"{sid}: re-keyed permitted site {site} (review the message)" for site in rekeyed
            ]
            if grown and sid in REHOME_BY_BINDING:
                lost = {k: e for k, e in old.items() if k not in base.keys}
                grown, moved = rehomes(root, tree, grown, base.reasons, lost)
                report += [f"{sid}: {line}" for line in moved]
            approved = grown & frozenset(approvals.get(sid, {}))
            report += [
                f"{sid}: approved growth {k} ({approvals[sid][k]})" for k in sorted(approved)
            ]
            grown -= approved
            if grown:
                findings.append(
                    f"{sid}: baseline gained key(s) not in the merge base: {_fmt(grown)}"
                )
            raised = sorted(
                k for k in base.keys & old.keys() if max_raised(base.reasons[k], old[k])
            )
            if raised:
                findings.append(f"{sid}: max raised or dropped for key(s): {', '.join(raised)}")
        elif removed:
            successors[sid] = base.reasons
        else:
            # Newly registered in this diff: the one way a first inventory is admitted.
            report.append(f"{sid}: first inventory, {len(base.keys)} key(s), review required")
    only_rekey = (set(donors) | set(successors)) <= REKEY_PER_SITE
    transfer, rekeyed_report = helper.transfer_findings(
        sys.modules[__name__], donors, successors, only_rekey, removed
    )
    findings += transfer
    report += rekeyed_report
    findings += helper.sentry_file_findings(root, tree, fresh["retired_files"])
    return findings, report
