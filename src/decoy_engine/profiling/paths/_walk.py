"""The walk of one parsed JSON cell, and the bounded state that decides which keys are names.

A path pattern is a tuple of segments: an object key that passed the key rule, `*` for any other
key, and `[*]` for an array item. Pass 1 (`Levels.scout`) reads every cell once and keeps, per
level (an object's own pattern), only the keys that passed rules 1 and 2, with the number of cells
each appears in. A level with more than `SCAN_MAP_KEYS` keys collapses on the spot and drops its
keys, so pass-1 state never exceeds `SCAN_MAX_PATHS * (SCAN_MAP_KEYS + 1)` keys of at most 64
characters. `Levels.finalize` applies rule 3 (appearance). Pass 2 (`Levels.settle`, `Tally`) walks
again with every decision made and counts the paths.

A key that fails a rule is counted under `*` and its text is never stored.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any, Final

import pandas as pd

from decoy_engine._canonical import (
    SCAN_ARRAY_ITEMS,
    SCAN_KEY_APPEARANCE,
    SCAN_LEAF_SAMPLE,
    SCAN_MAP_KEYS,
    SCAN_MAX_DEPTH,
    SCAN_MAX_PATHS,
)
from decoy_engine.detection.detectors import run_all_detectors

Pattern = tuple[str, ...]
Pair = tuple[str, Any]

WILD: Final = "*"
ITEM: Final = "[*]"
OBJECT: Final = "object"
ARRAY: Final = "array"

# Key rule 1. `fullmatch` anchors at the true end of the text, so a trailing newline fails.
_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_VERDICTS: Final = 1024
# A scalar leaf is kept for detection up to this many characters, so a few huge leaves cannot hold
# `SCAN_LEAF_SAMPLE` megabytes per path. A detector matches short values, so the cut loses nothing.
_LEAF_CHARS: Final = 4096


def path_text(pattern: Pattern) -> str:
    """`$.user.email`, `$.items[*].sku`, `$.*`."""
    return "$" + "".join(seg if seg == ITEM else f".{seg}" for seg in pattern)


def name_hint(pattern: Pattern) -> str:
    """The last named segment, for the detectors' column-name hint. Empty for `*` and the root."""
    for seg in reversed(pattern):
        if seg == ITEM:
            continue
        return "" if seg == WILD else seg
    return ""


def kind_of(value: Any) -> str | None:
    """The JSON kind of a non-null value, or `None` for a Python type JSON has no kind for."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return OBJECT
    if isinstance(value, (list, tuple)):
        return ARRAY
    return None


class _Level:
    __slots__ = ("cells", "collapsed", "counts", "kept", "last", "last_cell", "runs")

    def __init__(self) -> None:
        self.cells = 0  # cells in which an object with this pattern appears
        self.runs = 0  # detector runs on this level's keys: stored and rejected keys both count
        self.last_cell = -1
        self.counts: dict[str, int] = {}  # key -> cells it appears in
        self.last: dict[str, int] = {}  # key -> last cell counted, so a cell counts once
        self.collapsed = False
        self.kept: frozenset[str] = frozenset()


class Levels:
    """Pass-1 state, then the frozen key decisions for pass 2."""

    def __init__(self) -> None:
        self._levels: dict[Pattern, _Level] = {}
        self._verdicts: dict[str, bool] = {}
        self.key_total = 0
        self.cell = 0
        self.truncated = False
        self.suspect = 0

    # -- pass 1 ---------------------------------------------------------------------------------

    def scout(self, pattern: Pattern, mapping: dict[Any, Any]) -> list[Pair]:
        """The segment of every key of one object, noting keys that pass rules 1 and 2."""
        level = self._levels.get(pattern)
        if level is None:
            if len(self._levels) >= SCAN_MAX_PATHS:
                self.truncated = True
                return [(WILD, child) for child in mapping.values()]
            level = self._levels[pattern] = _Level()
        if level.last_cell != self.cell:
            level.last_cell = self.cell
            level.cells += 1
        if level.collapsed:
            return [(WILD, child) for child in mapping.values()]
        pairs = [(self._admit(pattern, level, key), child) for key, child in mapping.items()]
        if level.collapsed:  # it collapsed while this object was read: no key keeps a name
            return [(WILD, child) for _, child in pairs]
        return pairs

    def _admit(self, pattern: Pattern, level: _Level, key: Any) -> str:
        if key in level.counts:
            if level.last[key] != self.cell:
                level.last[key] = self.cell
                level.counts[key] += 1
            return str(key)
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            return WILD
        data = self._is_data(level, key)
        if not data:
            self.add(level, key)
        # Keys rejected as data count toward the level's budget too, so an object of endless
        # distinct data-like keys collapses instead of running a detector on every one.
        if len(level.counts) > SCAN_MAP_KEYS or level.runs > SCAN_MAP_KEYS:
            self._collapse(pattern, level)
            return WILD
        return WILD if data else key

    def add(self, level: _Level, key: str) -> None:
        """Store a key that passed rules 1 and 2. The only place a key text enters the state."""
        level.counts[key] = 1
        level.last[key] = self.cell
        self.key_total += 1

    def _collapse(self, pattern: Pattern, level: _Level) -> None:
        """Drop the level's keys and every level below one of them: the level is now `*`."""
        self.key_total -= len(level.counts)
        level.counts, level.last = {}, {}
        level.collapsed = True
        depth = len(pattern)
        for below in [
            p for p in self._levels if len(p) > depth and p[:depth] == pattern and p[depth] != WILD
        ]:
            self.key_total -= len(self._levels.pop(below).counts)

    def _is_data(self, level: _Level, key: str) -> bool:
        """Key rule 2: a detector hit on the key text. A detector run (not a cached answer) is
        charged to the level; the cache is bounded, so no more than a few keys are kept."""
        verdict = self._verdicts.get(key)
        if verdict is None:
            if len(self._verdicts) >= _VERDICTS:
                self._verdicts.clear()
            level.runs += 1
            verdict = bool(run_all_detectors(pd.Series([key], dtype=object), ""))
            self._verdicts[key] = verdict
        return verdict

    def finalize(self) -> None:
        """Key rule 3: a key needs at least 2 cells and `SCAN_KEY_APPEARANCE` of its parent's."""
        for level in self._levels.values():
            level.kept = frozenset(
                key
                for key, count in level.counts.items()
                if count >= 2 and count / level.cells >= SCAN_KEY_APPEARANCE
            )

    @property
    def map_collapsed(self) -> int:
        return sum(1 for level in self._levels.values() if level.collapsed)

    # -- pass 2 ---------------------------------------------------------------------------------

    def settle(self, pattern: Pattern, mapping: dict[Any, Any]) -> list[Pair]:
        """The final segment of every key of one object; counts the keys written as `*`."""
        level = self._levels.get(pattern)
        if level is None or level.collapsed:
            return [(WILD, child) for child in mapping.values()]
        pairs: list[Pair] = []
        for key, child in mapping.items():
            if key in level.kept:
                pairs.append((key, child))
            else:
                self.suspect += 1
                pairs.append((WILD, child))
        return pairs


class _Row:
    __slots__ = ("kinds", "last", "leaves", "null", "null_last", "present")

    def __init__(self) -> None:
        self.present = 0
        self.null = 0
        self.last = -1
        self.null_last = -1
        self.kinds: set[str] = set()
        self.leaves: list[str] = []


class Tally:
    """Pass-2 counts per path pattern. A pattern counts once per cell, however often it repeats."""

    def __init__(self) -> None:
        self.rows: dict[Pattern, _Row] = {}
        self.cell = 0
        self.truncated = False

    def record(self, pattern: Pattern, value: Any) -> bool:
        """Count one node. False when the node is not to be entered (path cap reached)."""
        row = self.rows.get(pattern)
        if row is None:
            if len(self.rows) >= SCAN_MAX_PATHS:
                self.truncated = True
                return False
            row = self.rows[pattern] = _Row()
        if row.last != self.cell:
            row.last = self.cell
            row.present += 1
        if value is None:
            if row.null_last != self.cell:
                row.null_last = self.cell
                row.null += 1
            return False
        kind = kind_of(value)
        if kind is not None:
            row.kinds.add(kind)
        if kind not in (OBJECT, ARRAY) and len(row.leaves) < SCAN_LEAF_SAMPLE:
            row.leaves.append(str(value)[:_LEAF_CHARS])
        return True


def walk(
    root: Any,
    expand: Callable[[Pattern, dict[Any, Any]], Sequence[Pair]],
    record: Callable[[Pattern, Any], bool],
) -> tuple[bool, int]:
    """Walk one cell without recursion, in document order. Returns whether a container sat deeper
    than `SCAN_MAX_DEPTH` (it is counted, not entered) and how many arrays had items past
    `SCAN_ARRAY_ITEMS`. `expand` names the children of an object; `record` sees every node below
    the root and may refuse to enter it."""
    too_deep = False
    long_arrays = 0
    stack: list[tuple[Any, Pattern, int]] = [(root, (), 1)]
    while stack:
        value, pattern, depth = stack.pop()
        if pattern and not record(pattern, value):
            continue
        if isinstance(value, dict):
            if depth > SCAN_MAX_DEPTH:
                too_deep = True
                continue
            pairs = expand(pattern, value)
            stack.extend((child, (*pattern, seg), depth + 1) for seg, child in reversed(pairs))
        elif isinstance(value, (list, tuple)):
            if depth > SCAN_MAX_DEPTH:
                too_deep = True
                continue
            if len(value) > SCAN_ARRAY_ITEMS:
                long_arrays += 1
            below = (*pattern, ITEM)
            stack.extend((child, below, depth + 1) for child in reversed(value[:SCAN_ARRAY_ITEMS]))
    return too_deep, long_arrays
