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
from collections.abc import Callable, Iterable, Iterator
from itertools import islice
from typing import Any, Final

import numpy as np
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
# Key rule 1b: a run of four digits reads as an id, a date or a phone or zip fragment, so the key
# is a wildcard. Short runs (`line1`, `v2`, `sha256`) stay names.
_DIGITS = re.compile(r"\d{4}")
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


def _union(left: int, right: int) -> int:
    """The union of two sets of cell numbers, each kept as a bit mask."""
    return left | right


class _Level:
    __slots__ = ("cells", "collapsed", "kept", "last", "last_cell", "rejected", "seen")

    def __init__(self) -> None:
        self.cells = 0  # the cells in which an object with this pattern appears, as a bit mask
        self.seen: dict[str, int] = {}  # key -> the cells it appears in, as a bit mask
        self.last: dict[str, int] = {}  # key -> last cell counted, so a cell counts it once
        self.last_cell = -1  # last cell counted in `cells`
        # Keys a detector rejected, as hashes: the text is never kept. They count toward the key
        # limit like the keys in `seen`, and they fold with the level like every other field.
        self.rejected: set[int] = set()
        self.collapsed = False
        self.kept: frozenset[str] = frozenset()


class Levels:
    """Pass-1 state, then the frozen key decisions for pass 2."""

    def __init__(self) -> None:
        self._levels: dict[Pattern, _Level] = {}
        self._verdicts: dict[str, bool] = {}
        self.key_total = 0
        self._cell = 0
        self._bit = 1
        self.truncated = False
        self.suspect = 0

    @property
    def cell(self) -> int:
        return self._cell

    @cell.setter
    def cell(self, value: int) -> None:
        self._cell = value
        self._bit = 1 << value  # built once per cell, not once per key

    # -- pass 1 ---------------------------------------------------------------------------------

    def scout(self, pattern: Pattern, mapping: dict[Any, Any]) -> Iterator[Pair]:
        """The segment of every key of one object, noting keys that pass rules 1 and 2. The pairs
        come one at a time, so a mapping of any size holds no list of them."""
        level = self._levels.get(pattern)
        if level is None:
            if len(self._levels) >= SCAN_MAX_PATHS:
                self.truncated = True
                return _wild(mapping)
            level = self._levels[pattern] = _Level()
        if level.last_cell != self._cell:
            level.last_cell = self._cell
            level.cells |= self._bit
        if level.collapsed:
            return _wild(mapping)
        return self._scouted(pattern, level, mapping)

    def _scouted(self, pattern: Pattern, level: _Level, mapping: dict[Any, Any]) -> Iterator[Pair]:
        for key, child in mapping.items():
            yield self._admit(pattern, level, key), child

    def _admit(self, pattern: Pattern, level: _Level, key: Any) -> str:
        if level.collapsed:  # it collapsed earlier in this object: no more detector runs
            return WILD
        if key in level.seen:
            if level.last[key] != self._cell:
                level.last[key] = self._cell
                level.seen[key] |= self._bit
            return str(key)
        if not isinstance(key, str) or not _KEY.fullmatch(key) or _DIGITS.search(key):
            return WILD
        data = self._is_data(level, key)
        if not data:
            self.add(level, key)
        # Keys rejected as data count toward the level's budget too, so an object of endless
        # distinct data-like keys collapses instead of running a detector on every one.
        if len(level.seen) > SCAN_MAP_KEYS or len(level.rejected) > SCAN_MAP_KEYS:
            self._collapse(pattern, level)
            return WILD
        return WILD if data else key

    def add(self, level: _Level, key: str) -> None:
        """Store a key that passed rules 1 and 2. The only place a key text enters the state."""
        level.seen[key] = self._bit
        level.last[key] = self._cell
        self.key_total += 1

    def _collapse(self, pattern: Pattern, level: _Level) -> None:
        """The level is now `*`: drop its keys and fold every level below one of them into the
        level below `*`, so the wildcard level is judged on all the cells, not the later ones."""
        self.key_total -= len(level.seen)
        level.seen = {}
        level.last = {}
        level.collapsed = True
        depth = len(pattern)
        named = {
            p[depth]
            for p in self._levels
            if len(p) > depth and p[:depth] == pattern and p[depth] != WILD
        }
        for key in named:
            self._fold((*pattern, key), (*pattern, WILD))

    def _is_data(self, level: _Level, key: str) -> bool:
        """Key rule 2: a detector hit on the key text. A rejected key is charged to the level
        whether the detector ran or the cache answered, and a level never runs a detector twice on
        one key. The cache is bounded, so no more than a few verdicts are kept."""
        mark = hash(key)
        if mark in level.rejected:
            return True
        verdict = self._verdicts.get(key)
        if verdict is None:
            if len(self._verdicts) >= _VERDICTS:
                self._verdicts.clear()
            verdict = bool(run_all_detectors(pd.Series([key], dtype=object), ""))
            self._verdicts[key] = verdict
        if verdict:
            level.rejected.add(mark)
        return verdict

    def finalize(self) -> None:
        """Key rule 3: a key needs at least 2 cells and `SCAN_KEY_APPEARANCE` of its parent's.

        A dropped key is `*` in pass 2, so the levels pass 1 tracked below it fold into the levels
        below `*` first. Levels run from the root down, so a level has every fold into it before its
        own keys are judged."""
        for depth in range(max((len(p) for p in self._levels), default=0) + 1):
            for pattern in [p for p in self._levels if len(p) == depth]:
                level = self._levels.get(pattern)
                if level is None or level.collapsed:
                    continue
                cells = level.cells.bit_count()
                level.kept = frozenset(
                    key
                    for key, mask in level.seen.items()
                    if mask.bit_count() >= 2 and mask.bit_count() / cells >= SCAN_KEY_APPEARANCE
                )
                for key in level.seen.keys() - level.kept:
                    self._fold((*pattern, key), (*pattern, WILD))

    def _fold(self, source: Pattern, target: Pattern) -> None:
        """Move every level at or below `source` to the same place below `target`, merging them
        into a level that is already there. Cells are unioned, so one cell that holds several
        dropped siblings counts once. No key text is added: only keys already stored move. A key
        that would land below a collapsed level is `*` there, so no level is ever made below one.
        Upper levels move first, so a level sees every collapse above it."""
        size = len(source)
        for pattern in sorted((p for p in self._levels if p[:size] == source), key=len):
            level = self._levels.pop(pattern, None)
            if level is None:
                continue
            self.key_total -= len(level.seen)
            destination = self._below_collapsed((*target, *pattern[size:]))
            held = self._levels.get(destination)
            if held is None:
                self._levels[destination] = level
                self.key_total += len(level.seen)
                continue
            held.cells = _union(held.cells, level.cells)
            held.last_cell = max(held.last_cell, level.last_cell)
            if held.collapsed:
                continue
            if level.collapsed:
                self._collapse(destination, held)
                continue
            held.rejected |= level.rejected
            for key, mask in level.seen.items():
                if key not in held.seen:
                    self.key_total += 1
                held.seen[key] = _union(held.seen.get(key, 0), mask)
                held.last[key] = max(held.last.get(key, -1), level.last.get(key, -1))
            if len(held.seen) > SCAN_MAP_KEYS or len(held.rejected) > SCAN_MAP_KEYS:
                self._collapse(destination, held)

    def _below_collapsed(self, pattern: Pattern) -> Pattern:
        """`pattern` with each key that sits directly below a collapsed level written as `*`."""
        parts = list(pattern)
        for i, part in enumerate(parts):
            if part not in (WILD, ITEM):
                above = self._levels.get(tuple(parts[:i]))
                if above is not None and above.collapsed:
                    parts[i] = WILD
        return tuple(parts)

    @property
    def map_collapsed(self) -> int:
        return sum(1 for level in self._levels.values() if level.collapsed)

    # -- pass 2 ---------------------------------------------------------------------------------

    def settle(self, pattern: Pattern, mapping: dict[Any, Any]) -> Iterator[Pair]:
        """The final segment of every key of one object; counts the keys written as `*`."""
        level = self._levels.get(pattern)
        if level is None or level.collapsed:
            return _wild(mapping)
        # A name is kept only for a cell pass 1 counted at this level, so a level that exists only
        # because folds made it (the level cap kept pass 1 from tracking this cell) names no key.
        return self._settled(level, mapping, bool((level.cells >> self._cell) & 1))

    def _settled(self, level: _Level, mapping: dict[Any, Any], counted: bool) -> Iterator[Pair]:
        for key, child in mapping.items():
            if counted and key in level.kept:
                yield key, child
            else:
                self.suspect += 1
                yield WILD, child


def _wild(mapping: dict[Any, Any]) -> Iterator[Pair]:
    return ((WILD, child) for child in mapping.values())


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
    expand: Callable[[Pattern, dict[Any, Any]], Iterable[Pair]],
    record: Callable[[Pattern, Any], bool],
) -> tuple[bool, int]:
    """Walk one cell without recursion, in document order. Returns whether a container sat deeper
    than `SCAN_MAX_DEPTH` (it is counted, not entered) and how many arrays had items past
    `SCAN_ARRAY_ITEMS`. `expand` names the children of an object; `record` sees every node below
    the root and may refuse to enter it.

    Each open container is one iterator frame, so the walk holds at most `SCAN_MAX_DEPTH` frames
    and never a list of the children of a wide object."""
    too_deep = False
    long_arrays = 0
    frames: list[tuple[Iterator[Pair], Pattern, int]] = []
    node: tuple[Any, Pattern, int] | None = (root, (), 1)
    while True:
        if node is None:
            while frames:
                children, parent, depth = frames[-1]
                step = next(children, None)
                if step is not None:
                    node = (step[1], (*parent, step[0]), depth)
                    break
                frames.pop()
            if node is None:
                return too_deep, long_arrays
        value, pattern, depth = node
        node = None
        length = -1
        if isinstance(value, np.ndarray) and value.ndim == 1:
            # A parquet list column reads as a 1-D array. Cut it before converting, so a huge
            # cell is never built as a list; `length` keeps the real size for the item cap.
            length = len(value)
            value = value[:SCAN_ARRAY_ITEMS].tolist()
        if pattern and not record(pattern, value):
            continue
        if isinstance(value, dict):
            if depth > SCAN_MAX_DEPTH:
                too_deep = True
                continue
            frames.append((iter(expand(pattern, value)), pattern, depth + 1))
        elif isinstance(value, (list, tuple)):
            if depth > SCAN_MAX_DEPTH:
                too_deep = True
                continue
            if max(length, len(value)) > SCAN_ARRAY_ITEMS:
                long_arrays += 1
            items = ((ITEM, child) for child in islice(value, SCAN_ARRAY_ITEMS))
            frames.append((items, pattern, depth + 1))
