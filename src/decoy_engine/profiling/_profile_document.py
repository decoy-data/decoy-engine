"""The plain profile writer: `profile_document` and `redact_profile_dict`.

`ColumnProfile.to_dict()` stays the raw form (the platform persists and rebuilds it). Anything
that writes a profile for a person to read or commit goes through `profile_document`, and
anything that reads a saved profile back for display goes through `redact_profile_dict`. Which
fields hold cell values, and how a value is removed, come from the one registry in
`_value_redaction.py`; this module only walks a document and applies it, as `_snapshot_values.py`
does for the fit snapshot.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from decoy_engine.profiling._distributions import (
    CATEGORICAL_TOP_LABELS,
    OTHER_LABEL,
    SHARE_ROUNDING_MARGIN,
)
from decoy_engine.profiling._snapshot_values import labels_read_as_sentences, release_ranges_at_k
from decoy_engine.profiling._value_redaction import (
    MIN_RELEASE_COUNT,
    REDACTED,
    PlaceholderAt,
    Rule,
    _apply,
    _conforms,
    _containers,
    _redact_field,
    _sensitive_entries,
    _shape_keep,
    _shapes,
    profile_floor_slots,
    profile_types,
    stamp_value_policy,
)
from decoy_engine.profiling.sentinels import is_table_sentinel
from decoy_engine.profiling.types import NULL_CELL_TEXT, ColumnProfile

_DECADE_LABEL: Final = re.compile(r"(\d{4})s(?:-(\d{4})s)?")
_Range = tuple[int, int, int | float]


def _detached(root: Mapping[str, Any]) -> dict[str, Any]:
    """Copy of a JSON object without recursion, so a deeply nested file cannot crash the redactor."""
    out: dict[str, Any] = {}
    stack: list[tuple[Any, Any]] = [(root, out)]
    while stack:
        src, dst = stack.pop()
        for key, value in src.items() if isinstance(src, Mapping) else enumerate(src):
            child = value
            if isinstance(value, (Mapping, list, tuple)):
                child = {} if isinstance(value, Mapping) else []
                stack.append((value, child))
            if isinstance(dst, dict):
                dst[key] = child
            else:
                dst.append(child)
    return out


def _count(value: Any) -> int | None:
    """A row, null or top-value count; a bool, string, float or negative proves nothing."""
    return value if _conforms(value, int) and value >= 0 else None


def _bin_count(value: Any) -> float | None:
    """A date bin count, which the profiler writes as a whole-number float."""
    return value if _conforms(value, float) and value >= 0 and value.is_integer() else None


def _held(value: Any) -> bool:
    """True for a top-value count of at least K rows."""
    count = _count(value)
    return count is not None and count >= MIN_RELEASE_COUNT


def _share_bound(share: Any, row_count: int | None) -> Decimal | None:
    """Least row count a rounded categorical share allows, read from the share's own index."""
    if row_count is None or not _conforms(share, float) or share < 0:
        return None
    return (Decimal(repr(float(share))) - SHARE_ROUNDING_MARGIN) * row_count / 100


def _kept_labels(
    dist: Mapping[str, Any], proven: Mapping[str, int], rows: int | None
) -> list[bool] | None:
    """Per categorical label, whether a count proves K rows hold it; None when none can be read."""
    labels, data = dist.get("labels"), dist.get("data")
    if type(labels) is not list or type(data) is not list or len(labels) != len(data):
        return None
    kept = []
    for i, label in enumerate(labels):
        bound = _share_bound(data[i], rows)
        if not isinstance(label, str):
            kept.append(False)
        elif i == CATEGORICAL_TOP_LABELS == len(labels) - 1 and label == OTHER_LABEL:
            kept.append(True)  # the aggregate of the labels past the top ones
        elif label in proven:
            kept.append(proven[label] >= MIN_RELEASE_COUNT)
        else:
            kept.append(bound is not None and bound >= MIN_RELEASE_COUNT)
    return kept


def _folded_decades(dist: Mapping[str, Any]) -> list[_Range] | None:
    """The date distribution's decades, coded at the K-th row and folded; None when nothing may be released."""
    labels, data = dist.get("labels"), dist.get("data")
    if type(labels) is not list or type(data) is not list or len(labels) != len(data):
        return None
    ranges: list[_Range] = []
    for label, count in zip(labels, data, strict=True):
        match = _DECADE_LABEL.fullmatch(label) if isinstance(label, str) else None
        whole = _bin_count(count)
        if match is None or whole is None:
            return None
        start = int(match[1])
        end = int(match[2] or match[1]) + 9
        if end < start + 9 or (ranges and start <= ranges[-1][1]):
            return None
        ranges.append((start, end, whole))
    return release_ranges_at_k(ranges) or None


@dataclass(frozen=True)
class _Evidence:
    """What the counts of one unflagged column prove, read before any slot changes."""

    non_null: int | None
    proven: Mapping[str, int]  # text -> rows the top values say hold it
    labels_kept: list[bool] | None  # per categorical label
    free_text: bool
    exempt: bool  # a bool column keeps its two values
    decades: list[_Range] | None
    # Non-null rows no released top value covers. A mean beside released exact values and 1 to K-1
    # leftover rows would let a reader subtract the values and read the leftovers.
    uncovered: int | None


def _numeric_sentinels(field: Mapping[str, Any]) -> dict[str, int]:
    """Row count by value text for each numeric sentinel flag `sentinels.py` keeps as table text."""
    flags = field.get("sentinels")
    out: dict[str, int] = {}
    for flag in flags if isinstance(flags, list) else ():
        if not isinstance(flag, Mapping):
            continue
        kind, value, note, raw_count = (flag.get(k) for k in ("kind", "value", "note", "count"))
        count = _count(raw_count)
        if (
            kind == "numeric_sentinel"
            and isinstance(value, str)
            and count is not None
            and is_table_sentinel(kind, value, note, raw_count)
        ):
            out[value] = max(out.get(value, 0), count)
    return out


def _evidence(field: Mapping[str, Any]) -> _Evidence:
    rows, nulls = _count(field.get("row_count")), _count(field.get("null_count"))
    proven: dict[str, int] = {}
    kept_texts: set[str] = set()
    tops = field.get("top_values")
    for top in tops if isinstance(tops, list) else ():
        value, count = (
            (top.get("value"), _count(top.get("count")))
            if isinstance(top, Mapping)
            else (None, None)
        )
        if isinstance(value, str) and count is not None and value not in (REDACTED, NULL_CELL_TEXT):
            proven[value] = max(proven.get(value, 0), count)
            if count >= MIN_RELEASE_COUNT:
                kept_texts.add(value)
    dist = field.get("distribution")
    dist = dist if isinstance(dist, Mapping) else {}
    labels_kept = _kept_labels(dist, proven, rows) if dist.get("kind") == "categorical" else None
    if labels_kept is not None:
        labels = dist["labels"]
        kept_texts |= {
            label
            for label, kept in zip(labels, labels_kept, strict=True)
            if kept
            and isinstance(label, str)
            and label not in (REDACTED, NULL_CELL_TEXT, OTHER_LABEL)
        }
    exempt = field.get("inferred_type") == "boolean"
    decades = _folded_decades(dist) if dist.get("kind") == "date" else None
    non_null = None if rows is None or nulls is None or nulls > rows else rows - nulls
    free_text = not exempt and labels_read_as_sentences(kept_texts)
    held = {} if free_text else {t: c for t, c in proven.items() if c >= MIN_RELEASE_COUNT}
    # A kept numeric sentinel flag also names a value and its row count, so it covers rows too.
    for text, count in _numeric_sentinels(field).items():
        held[text] = max(held.get(text, 0), count)
    released = sum(held.values())
    return _Evidence(
        non_null=non_null,
        proven=proven,
        labels_kept=labels_kept,
        free_text=free_text,
        exempt=exempt,
        decades=decades,
        uncovered=None if non_null is None or released > non_null else non_null - released,
    )


def _decade_edge(ev: _Evidence, rule: Rule, whole_instant: bool) -> str | None:
    if ev.decades is None:
        return None
    if rule is Rule.DECADE_START:
        return f"{ev.decades[0][0]:04d}-01-01" + ("T00:00:00" if whole_instant else "")
    return f"{ev.decades[-1][1]:04d}-12-31" + ("T23:59:59.999999" if whole_instant else "")


def _floor_slot(
    type_name: str, slot: str, rule: Rule, container: dict[str, Any], ev: _Evidence
) -> Rule | PlaceholderAt | None:
    """The `_apply` rule for one slot of an unflagged column, or None to keep it as it is."""
    current = container.get(slot)
    if current is None:
        return Rule.NULL  # `_apply` leaves an absent or null slot as it is
    if rule is Rule.HELD_BY_K:
        if ev.exempt:
            return None
        proven = isinstance(current, str) and ev.proven.get(current, 0) >= MIN_RELEASE_COUNT
        return None if proven and not ev.free_text else Rule.NULL
    if rule is Rule.AGGREGATE_2K:
        ok = ev.non_null is not None and ev.non_null >= 2 * MIN_RELEASE_COUNT
        ok = ok and ev.uncovered is not None and not 0 < ev.uncovered < MIN_RELEASE_COUNT
        return None if ok and isinstance(current, (str, int, float)) else Rule.NULL
    if rule is Rule.UNDER_K_PLACEHOLDER and type_name == "TopValue":
        held = _held(container.get("count")) and isinstance(current, str)
        return None if ev.exempt or (held and not ev.free_text) else Rule.PLACEHOLDER
    if rule is Rule.UNDER_K_PLACEHOLDER:
        if ev.exempt:
            return None
        if ev.free_text or ev.labels_kept is None:
            return Rule.PLACEHOLDER_EACH
        return PlaceholderAt(frozenset(i for i, kept in enumerate(ev.labels_kept) if not kept))
    if rule is Rule.FOLD_DECADES:
        if ev.decades is None:
            return Rule.PLACEHOLDER_EACH
        container["labels"] = [_decade_label(s, e) for s, e, _ in ev.decades]
        container["data"] = [float(c) for _, _, c in ev.decades]
        return None
    if rule in (Rule.DECADE_START, Rule.DECADE_END):
        edge = _decade_edge(ev, rule, type_name == "FieldStats")
        if edge is None:
            return Rule.NULL
        container[slot] = edge
        return None
    if rule is Rule.SENTINEL_TABLE:
        table = is_table_sentinel(
            container.get("kind"),
            container.get("value"),
            container.get("note"),
            container.get("count"),
        )
        return None if table or _held(container.get("count")) else Rule.PLACEHOLDER
    return rule


def _decade_label(start: int, end: int) -> str:
    return f"{start}s" if end == start + 9 else f"{start}s-{end - 9}s"


def _floor_keep(shapes: Mapping[str, Any], kept: frozenset[str]) -> Callable[[str, Any], bool]:
    """Keep test for a floored container: a slot the floor kept, or a value-free slot of its type."""
    shape_keep = _shape_keep(shapes)
    return lambda name, value: name in kept or shape_keep(name, value)


def _floor_field(fields: list[Any], index: int) -> None:
    """Floor one column the profiler did not flag: each value slot is kept only on proof of K rows.

    The decision for every slot is read from a copy taken before any change, and every
    replacement goes through `_apply`; the folded decade labels and bounds are the only values
    this function assigns.
    """
    ev = _evidence(_detached(fields[index]))
    for path, cls in profile_types().items():
        if path[:2] != ("fields", "*"):
            continue
        shapes = _shapes(cls)
        for container in _containers(fields[index], path[2:], fields, index):
            rules, kept = profile_floor_slots(cls.__name__, container.get("kind"))
            plan = {
                slot: rule
                for slot, base in rules.items()
                if (rule := _floor_slot(cls.__name__, slot, base, container, ev)) is not None
            }
            _apply(container, plan, _floor_keep(shapes, kept | rules.keys() - plan.keys()))


def redact_profile_dict(doc: Mapping[str, Any], *, include_values: bool = False) -> dict[str, Any]:
    """A copy of a profile document with the value-sensitive columns' cell values removed.

    Never mutates `doc` and never trusts its `value_policy` marker, so a second pass is a
    no-op and a forged or legacy file is still redacted. A key no profile type declares, or a
    value-free key holding a value of the wrong type, is replaced at the root and inside a
    value-sensitive column, since a newer or hand-edited file may keep a cell there. `include_values=True` keeps every value and adds a `raw`
    policy only when the document has none.
    """
    if not isinstance(doc, Mapping):
        raise TypeError(f"a profile document is a JSON object, not {type(doc).__name__}")
    if type(include_values) is not bool:
        raise TypeError(f"include_values must be a bool, not {type(include_values).__name__}")
    out = _detached(doc)
    if not include_values:
        # The two marker keys are rewritten below, so their loaded values never survive.
        _apply(out, {}, _shape_keep(_shapes(ColumnProfile)))
    fields: Any = out.get("fields")
    entries = _sensitive_entries(fields)
    if not include_values:
        flagged = {index for index, _ in entries}
        for i in range(len(fields)) if isinstance(fields, list) else ():
            if i not in flagged:
                _floor_field(fields, i)
        for index, _ in entries:
            if index is None:
                _apply(out, {"fields": Rule.PLACEHOLDER}, lambda *_: True)
            else:
                _redact_field(fields, index)
    return stamp_value_policy(out, [name for _, name in entries], include_values=include_values)


def profile_document(profile: ColumnProfile, *, include_values: bool = False) -> dict[str, Any]:
    """The JSON document to write for a profile: `to_dict()` passed through the redactor."""
    return redact_profile_dict(profile.to_dict(), include_values=include_values)
