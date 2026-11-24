"""Guard rules of the ratchet: a ``GUARD_KEYS`` baseline lists guards, so dropping a key loosens it.

Loaded by path from ``tests/sentry/_ratchet.py`` (an extracted base copy uses its own). Every
function returns finding strings, or ``(findings, report lines)``, and never reads a file. An
approval is *fresh* when its ``(id, key)`` pair is not among the base approvals of either
location (``approved_growth`` or ``[retired_growth]``), so moving or rewording a row never
re-arms it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

CEILING_FIELDS = ("max",)
FLOOR_FIELDS = ("min",)
_VERBS = {"max": "raised", "min": "lowered"}


def loosened_fields(head: object, base: object) -> list[str]:
    """Bound fields that got looser against the base entry: a ceiling rose or was dropped, or a
    floor fell or was dropped. A bound the base entry does not carry cannot loosen."""
    out = []
    for fields, worse in ((CEILING_FIELDS, int.__gt__), (FLOOR_FIELDS, int.__lt__)):
        for field in fields:
            old = base.get(field) if isinstance(base, dict) else None
            new = head.get(field) if isinstance(head, dict) else None
            if isinstance(old, int) and (not isinstance(new, int) or worse(new, old)):
                out.append(field)
    return out


def loosened_findings(
    sid: str,
    head: dict[str, object],
    old: dict[str, object],
    approvals: dict[str, str],
    base_approvals: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Findings for keys in both trees whose bound loosened, minus keys with a fresh approval.

    ``head`` and ``old`` map key to entry. An approved key is reported, not failed.
    """
    new = fresh(approvals, base_approvals)
    findings: list[str] = []
    report: list[str] = []
    for field in (*CEILING_FIELDS, *FLOOR_FIELDS):
        keys = sorted(
            k for k in head.keys() & old.keys() if field in loosened_fields(head[k], old[k])
        )
        report += [f"{sid}: approved raise {k} ({new[k]})" for k in keys if k in new]
        left = [k for k in keys if k not in new]
        if left:
            findings.append(
                f"{sid}: {field} {_VERBS[field]} or dropped for key(s): {', '.join(left)}"
            )
    return findings, report


def merged(*locations: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """``{id: {key: decision}}`` over every approval location of one side."""
    out: dict[str, dict[str, str]] = {}
    for location in locations:
        for sid, rows in location.items():
            out.setdefault(sid, {}).update(rows)
    return out


def fresh(rows: dict[str, str], base: dict[str, str]) -> dict[str, str]:
    """The rows whose key is not in the same id's base approvals."""
    return {k: d for k, d in rows.items() if k not in base}


def guard_findings(
    sid: str,
    path: str,
    old_keys: Iterable[str],
    head_keys: frozenset[str],
    approvals: dict[str, str],
    base_approvals: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Lost keys of a surviving guard id need a fresh approval, and a fresh approval needs a key.

    An approval already on base for a key absent from both trees is the merged record of an
    earlier deletion, so it passes; a fresh one for such a key is a stray row.
    """
    old = frozenset(old_keys)
    new = fresh(approvals, base_approvals)
    findings: list[str] = []
    report: list[str] = []
    for key in sorted(old - head_keys):
        if key in new:
            report.append(f"{sid}: approved guard removal {key} ({new[key]})")
        else:
            findings.append(
                f"{sid}: guard key {key} was dropped without a fresh approved_growth row"
            )
    findings += [
        f"{sid}: stale approved_growth, {key} is not in {path}"
        for key in sorted(new)
        if key not in head_keys and key not in old
    ]
    return findings, report


def retired_guard_findings(
    sid: str,
    old: dict[str, object],
    successors: Iterable[dict[str, object]],
    rows: dict[str, str],
    base_rows: dict[str, str],
    retired_is_fresh: bool,
    loosened: Callable[[object, object], bool],
) -> tuple[list[str], list[str]]:
    """A retired guard id needs a fresh ``[retired]`` decision and, for every old key, either a
    registered guard successor holding it within its bound or a fresh ``[retired_growth]`` row.

    A successor never excuses the retirement itself or another missing key.
    """
    findings: list[str] = []
    report: list[str] = []
    if not retired_is_fresh:
        findings.append(f"{sid}: guard sentry removed without a fresh [retired] decision")
    new = fresh(rows, base_rows)
    heirs = list(successors)
    for key in sorted(old):
        if any(key in heir and not loosened(heir[key], old[key]) for heir in heirs):
            continue
        if key in new:
            report.append(f"{sid}: approved guard removal {key} ({new[key]})")
        else:
            findings.append(
                f"{sid}: guard key {key} was dropped with its retired id without a fresh "
                "[retired_growth] row"
            )
    return findings, report


def stray_retired_rows(
    head_rows: dict[str, dict[str, str]],
    base_rows: dict[str, dict[str, str]],
    retired_guards: Mapping[str, Iterable[str]],
) -> list[str]:
    """Fresh ``[retired_growth]`` rows only for old keys of a guard id retired in this diff."""
    out = []
    for sid, rows in sorted(head_rows.items()):
        allowed = frozenset(retired_guards.get(sid, ()))
        out += [
            f"{sid}: retired_growth row for {sid} {key} is not a lost key of a guard id "
            "retired in this diff"
            for key in sorted(fresh(rows, base_rows.get(sid, {})))
            if key not in allowed
        ]
    return out


def retired_guards_findings(
    retired: Iterable[str],
    olds: dict[str, dict[str, object]],
    heirs: list[dict[str, object]],
    rows: tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]],
    fresh_retired: set[str],
    loosened: Callable[[object, object], bool],
) -> tuple[list[str], list[str]]:
    """Every guard id removed from the registry, plus the ``[retired_growth]`` rows that need one.

    ``rows`` is ``(head [retired_growth], base approvals of both locations)``; ``olds`` holds each
    removed guard's base entries and ``heirs`` the entries of guard ids new at head.
    """
    head_rows, base_rows = rows
    findings: list[str] = []
    report: list[str] = []
    for sid in sorted(retired):
        got, said = retired_guard_findings(
            sid,
            olds[sid],
            heirs,
            head_rows.get(sid, {}),
            base_rows.get(sid, {}),
            sid in fresh_retired,
            loosened,
        )
        findings += got
        report += said
    allowed = {sid: olds[sid] for sid in retired if sid in fresh_retired}
    findings += stray_retired_rows(head_rows, base_rows, allowed)
    return findings, report
