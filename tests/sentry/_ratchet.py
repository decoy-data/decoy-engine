"""Shared shrink-only ratchet logic for sentry baselines (stdlib plus tomllib).

A baseline is a JSON file ``{"sentry_id", "created_in", "entries": {key: {"reason"}}}``
under ``tests/sentry/baselines/``. ``scripts/dev/sentry_registry.toml`` binds each sentry id to
exactly one baseline path. ``check`` compares the working tree with a base commit and returns
findings; an empty list means the ratchet holds. Baseline keys compare exactly, except the
``permitted::<file>::<site>::<digest>`` keys of the sentries in ``REKEY_PER_SITE``, which
compare by count per site (see ``growth``). An entry that carries a numeric ``max`` may keep
or lower it, never raise or drop it; one that carries a ``min`` may keep or raise it (see
``bound_loosened``); an owner-approved raise names the key in a fresh ``approved_growth`` row.
The keys of a ``GUARD_KEYS`` baseline are guards: dropping one needs the same approval
(see ``ratchet/_bounds.py``). A key of the form
``<file>.py::<qualname>::<name>`` key of a ``REHOME_BY_BINDING`` sentry may also move 1:1 to a new
entry that declares ``moved_from`` when the old site is gone from the source (see ``_rehome.rehomes``).
Messages carry ids, paths and keys only.
"""

from __future__ import annotations

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
# Baselines whose keys are guards (scalar caps and floors), not debts: a lost key loosens the
# check, a new key tightens it. They flip the growth rule (``ratchet/_bounds.py``).
GUARD_KEYS = frozenset({"sentry-limits"})
_HELPERS: dict[Path, ModuleType] = {}


def _helper(name: str) -> ModuleType:
    """A helper module beside this file, loaded by path so an extracted copy of the checker uses
    its own helpers and never the head's."""
    path = Path(__file__).resolve().parent / "ratchet" / f"{name}.py"
    if path not in _HELPERS:
        spec = importlib.util.spec_from_file_location(f"_ratchet{name}_{len(_HELPERS)}", path)
        if spec is None or spec.loader is None:
            raise ImportError(path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        _HELPERS[path] = mod
    return _HELPERS[path]


def _integrity() -> ModuleType:
    return _helper("_integrity")


def _bounds() -> ModuleType:
    return _helper("_bounds")


@dataclass(frozen=True)
class Registry:
    """A registry that passed ``load_side``; ``_check`` reads only these validated fields."""

    paths: dict[str, str]
    approvals: dict[str, dict[str, str]]
    retired_growth: dict[str, dict[str, str]]
    baselines: dict[str, Baseline]
    rows: int
    decisions: dict[str, dict[str, str]]
    names: dict[str, set[str]]
    report: list[str]


@dataclass(frozen=True)
class Baseline:
    sentry_id: str
    created_in: str
    keys: frozenset[str]
    reasons: dict[str, object]


def parse_registry(doc: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """``{id: path}`` and findings for duplicate ids, shared paths or unsafe paths.

    Every row's path is checked, including the row of a duplicated id, so a duplicate cannot
    hide an unsafe path. ``doc`` must have passed ``validate_registry``.
    """
    out: dict[str, str] = {}
    by_path: dict[str, list[str]] = {}
    findings: list[str] = []
    for row in doc.get("sentry", []):
        sid, path = row["id"], row["baseline"]
        if sid in out:
            findings.append(f"registry: sentry id {sid} appears twice")
        out[sid] = path
        by_path.setdefault(path, []).append(sid)
    for path in sorted(by_path):
        ids = sorted(set(by_path[path]))
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


def _approval_rows(
    sid: str, items: object, label: str, out: dict[str, dict[str, str]]
) -> list[str]:
    """Parse one id's ``{ key, decision }`` rows into ``out``; the one parser for both locations
    (``approved_growth`` and ``[retired_growth]``). Returns findings for bad rows."""
    findings: list[str] = []
    for item in items if isinstance(items, list) else []:
        key = item.get("key") if isinstance(item, dict) else None
        decision = item.get("decision") if isinstance(item, dict) else None
        if not isinstance(key, str) or not key:
            findings.append(f"{sid}: {label} row has no key")
        elif _GLOB_CHARS & set(key):
            findings.append(f"{sid}: {label} key {key} is a pattern; list exact keys")
        elif decision_problem(decision):
            findings.append(
                f"{sid}: {label} for {key} needs a decision "
                f"'owner YYYY-MM-DD <reason of {MIN_REASON}+ chars>'"
            )
        elif key in out.get(sid, {}):
            findings.append(f"{sid}: {label} key {key} appears twice")
        else:
            out.setdefault(sid, {})[key] = str(decision)
    return findings


def parse_approvals(doc: dict[str, Any]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """``{sentry id: {key: decision}}`` from ``approved_growth`` rows, and findings for bad rows.

    A row is ``{ key, decision }``; the key compares exactly (no glob or prefix) and the decision
    must name a dated owner decision. Growth of a baseline passes only through a row here.
    """
    out: dict[str, dict[str, str]] = {}
    findings: list[str] = []
    for row in doc.get("sentry", []):
        findings += _approval_rows(
            row.get("id", ""), row.get("approved_growth", []), "approved_growth", out
        )
    return out, findings


def parse_retired_growth(doc: dict[str, Any]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """``{old id: {key: decision}}`` from the ``[retired_growth]`` table, rows as in ``approved_growth``."""
    table = doc.get("retired_growth", {})
    if not isinstance(table, dict):
        return {}, ["registry: [retired_growth] must be a table of arrays of { key, decision }"]
    out: dict[str, dict[str, str]] = {}
    findings: list[str] = []
    for sid, items in sorted(table.items()):
        if not isinstance(items, list):
            findings.append(f"{sid}: retired_growth must be an array of {{ key, decision }}")
        else:
            findings += _approval_rows(sid, items, "retired_growth", out)
    return out, findings


def decision_problem(decision: object) -> str | None:
    """Why ``decision`` is not an acceptable owner decision, or ``None`` when it is."""
    if not _decision_ok(decision):
        return f"needs a decision 'owner YYYY-MM-DD <reason of {MIN_REASON}+ chars>'"
    if weak_reason(str(decision).split(" ", 2)[2]):
        return f"reason is empty, a placeholder or under {MIN_REASON} chars"
    return None


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def parse_baseline(text: str) -> Baseline:
    """A baseline document with exact types and no coercion; any deviation raises ``ValueError``.

    An object with a string ``sentry_id`` and an ``entries`` object whose values are objects with a
    string ``reason``; optional ``category`` and ``moved_from`` are strings, ``max`` and ``min`` are
    exact integers (a boolean is not one), and ``created_in``, when present, is a string. A
    duplicate JSON key at any depth is refused.
    """
    data = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    if not isinstance(data, dict):
        raise ValueError("not a baseline document")
    sentry_id, entries, created = (
        data.get("sentry_id"),
        data.get("entries"),
        data.get("created_in", ""),
    )
    if (
        not isinstance(sentry_id, str)
        or not isinstance(entries, dict)
        or not isinstance(created, str)
    ):
        raise ValueError("wrong type in a baseline header")
    for entry in entries.values():
        if not isinstance(entry, dict) or not isinstance(entry.get("reason"), str):
            raise ValueError("an entry needs a string reason")
        if any(f in entry and not isinstance(entry[f], str) for f in ("category", "moved_from")):
            raise ValueError("category and moved_from are strings")
        if any(f in entry and type(entry[f]) is not int for f in ("max", "min")):
            raise ValueError("max and min are integers")
    return Baseline(sentry_id, created, frozenset(entries), entries)


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


def _max_of(entry: object) -> int | None:
    value = entry.get("max") if isinstance(entry, dict) else None
    return value if isinstance(value, int) else None


def bound_loosened(head: object, base: object) -> bool:
    """True when ``head`` loosens a ``max`` or ``min`` its base entry carries."""
    return bool(_bounds().loosened_fields(head, base))


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
    except Exception:
        return ["cannot complete the check: the registry or a baseline holds unexpected input"], []


def load_side(
    side: Any,
    helper: ModuleType,
    base_names: dict[str, set[str]] | None = None,
    waivers: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[Registry | None, list[str]]:
    """The one loader for the HEAD and the BASE registry: the only place a side's input is read
    and validated, and it never collapses or overwrites an input silently.

    ``side`` is a ``helper.Side``. Both sides enumerate the baseline folder and open the registry
    and every row's baseline through the same ``helper`` functions, then check shape, duplicate
    ids and paths, closed row keys, decision tables, approvals, each baseline (exact types, the
    ``sentry_id`` matching its row, reasons of real length), approvals against that side's own
    inventory, and orphan baseline files. A present empty registry fails on either side. Any
    finding on the base raises ``BaseReadError``, because a base that is not a clean registry
    cannot anchor a comparison; on HEAD the findings are reported.
    """
    is_base = side.name == "base"

    def unreadable(path: str, message: str) -> list[str]:
        if is_base:
            raise helper.BaseReadError(path)
        return [message]

    try:
        text = helper.open_input(side, REGISTRY)
    except helper.InputReadError:
        return None, unreadable(
            REGISTRY, f"registry: {REGISTRY} cannot be read as UTF-8 text (a regular file)"
        )
    if text is not None and not text.strip():
        return None, unreadable(REGISTRY, f"registry: {REGISTRY} is empty")
    if text is None and not is_base:
        return None, [f"registry: {REGISTRY} is missing"]
    doc, problems = helper.validate_registry(text or "")
    if problems:
        unreadable(REGISTRY, "")  # raises on the base
        return None, [f"registry: {REGISTRY} {p}" for p in problems]
    paths, findings = parse_registry(doc)
    approvals, approval_findings = parse_approvals(doc)
    retired_growth, retired_growth_findings = parse_retired_growth(doc)
    findings += approval_findings + retired_growth_findings
    dec = helper.decisions(doc)
    fresh_fields = (
        helper.fresh(dec["checker_change"], base_names["checker_change"], decision_problem)
        if base_names is not None
        else set()
    )
    usable = frozenset(w for w in waivers if w[1] in fresh_fields)
    schema, report = helper.closed_keys(doc, ROW_KEYS, decision_problem, usable)
    findings += schema
    try:
        listed: set[str] | None = set(helper.list_entries(side, BASELINE_DIR))
    except helper.InputReadError as exc:
        listed = None
        findings += unreadable(
            exc.what, f"{exc.what} cannot be listed or is a link or special file ({side.name})"
        )
    blame = REGISTRY if findings else None  # the path a base failure names
    baselines: dict[str, Baseline] = {}
    for row in doc.get("sentry", []):  # every row, so a duplicate id cannot hide a diagnostic
        sid, path = row["id"], row["baseline"]
        if not helper.safe_path(path, BASELINE_DIR):
            continue
        broken = f"{sid}: baseline {path} cannot be read or is not a baseline file"
        try:
            got = helper.open_input(side, path)
            if got is None and listed is not None and path in listed:
                raise helper.InputReadError(path, side.name)  # listed, then gone
            if got is not None:
                parsed = parse_baseline(got)
        except (helper.InputReadError, ValueError, RecursionError):
            findings += unreadable(path, broken)
            continue
        before = len(findings)
        if got is None:
            findings.append(f"{sid}: registry points at {path} but there is no baseline file")
        else:
            baselines[sid] = parsed
            if parsed.sentry_id != sid:
                findings.append(
                    f"{path}: sentry_id {parsed.sentry_id!r} does not match registry id {sid}"
                )
            findings += reason_findings(path, parsed)
            if sid not in GUARD_KEYS:  # a guard's lost keys are judged by ``_bounds``
                findings += [
                    f"{sid}: stale approved_growth, {key} is not in {path}"
                    for key in sorted(set(approvals.get(sid, {})) - parsed.keys)
                ]
        if len(findings) > before and blame is None:
            blame = path
    registered = {row["baseline"] for row in doc.get("sentry", [])}
    orphans = sorted((listed or set()) - registered)
    findings += [f"{path}: baseline file is not registered in {REGISTRY}" for path in orphans]
    if findings and is_base:
        raise helper.BaseReadError(blame or orphans[0])
    rows = len(doc.get("sentry", []))
    registry = Registry(
        paths, approvals, retired_growth, baselines, rows, dec, helper.table_names(doc), report
    )
    return registry, findings


def _check(
    root: Path, tree: Any, helper: ModuleType, waiver_input: str | None
) -> tuple[list[str], list[str]]:
    base_reg_loaded, _ = load_side(helper.Side("base", root, tree), helper)
    assert base_reg_loaded is not None  # a base problem raised
    waived, waiver_findings = schema_waivers(waiver_input)
    head_side = helper.Side("head", root)
    head_reg, findings = load_side(head_side, helper, base_reg_loaded.names, waived)
    findings += waiver_findings
    if head_reg is None:
        return findings, []
    head, approvals, loaded = head_reg.paths, head_reg.approvals, head_reg.baselines
    base_reg = base_reg_loaded.paths
    bounds = _bounds()
    base_all = bounds.merged(base_reg_loaded.approvals, base_reg_loaded.retired_growth)
    findings += helper.registry_present(base_reg_loaded.rows, head_reg.rows)
    fresh = {
        t: helper.fresh(head_reg.decisions[t], base_reg_loaded.names[t], decision_problem)
        for t in head_reg.decisions
    }
    report: list[str] = helper.new_decisions(
        head_reg.decisions, base_reg_loaded.names, approvals, base_all
    )
    report += [
        f"decision retired_growth {sid} {key}: {text}"
        for sid, rows in sorted(head_reg.retired_growth.items())
        for key, text in sorted(bounds.fresh(rows, base_all.get(sid, {})).items())
    ]
    report += head_reg.report

    findings += helper.new_baseline_findings(
        tree, {head[s]: b.created_in for s, b in loaded.items()}
    )

    removed = set(base_reg) - set(head)
    # Every base baseline, retired ids included, was already read by ``load_side``.
    donors = {s: base_reg_loaded.baselines[s].reasons for s in sorted(removed - fresh["retired"])}
    successors: dict[str, dict[str, object]] = {}
    for sid, base in sorted(loaded.items()):
        path = head[sid]
        report.append(f"{sid}: {len(base.keys)} key(s) in {path}")
        if sid in GUARD_KEYS and sid not in base_reg:  # a fresh approval needs a key to guard
            findings += bounds.guard_findings(sid, path, (), base.keys, approvals.get(sid, {}), {})[
                0
            ]
        if sid in base_reg:
            if base_reg[sid] != path:
                findings.append(f"{sid}: baseline moved from {base_reg[sid]} to {path}")
                continue
            old = base_reg_loaded.baselines[sid].reasons
            grown, rekeyed = growth(base.keys, frozenset(old), sid in REKEY_PER_SITE)
            if sid in GUARD_KEYS:  # a new guard key tightens the check; it is not growth
                grown = frozenset()
                lost, lost_report = bounds.guard_findings(
                    sid, path, old, base.keys, approvals.get(sid, {}), base_all.get(sid, {})
                )
                findings += lost
                report += lost_report
            report += [
                f"{sid}: re-keyed permitted site {site} (review the message)" for site in rekeyed
            ]
            if grown and sid in REHOME_BY_BINDING:
                lost = {k: e for k, e in old.items() if k not in base.keys}
                grown, moved = _helper("_rehome").rehomes(
                    tree,
                    grown,
                    base.reasons,
                    lost,
                    _max_of,
                    lambda p: helper.open_input(head_side, p),
                )
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
            loose, approved_raises = bounds.loosened_findings(
                sid, base.reasons, old, approvals.get(sid, {}), base_all.get(sid, {})
            )
            findings += loose
            report += approved_raises
        elif removed:
            successors[sid] = base.reasons
        else:
            # Newly registered in this diff: the one way a first inventory is admitted.
            report.append(f"{sid}: first inventory, {len(base.keys)} key(s), review required")
    retired, retired_report = bounds.retired_guards_findings(
        removed & GUARD_KEYS,
        {gid: base_reg_loaded.baselines[gid].reasons for gid in removed & GUARD_KEYS},
        [b.reasons for sid, b in loaded.items() if sid in GUARD_KEYS and sid not in base_reg],
        (head_reg.retired_growth, base_all),
        fresh["retired"],
        bound_loosened,
    )
    findings += retired
    report += retired_report
    only_rekey = (set(donors) | set(successors)) <= REKEY_PER_SITE
    transfer, rekeyed_report = helper.transfer_findings(
        sys.modules[__name__], donors, successors, only_rekey, removed
    )
    findings += transfer
    report += rekeyed_report
    findings += helper.sentry_file_findings(root, tree, fresh["retired_files"])
    return findings, report
