"""The one grammar of a `nested` target: a closed subset of RFC 9535 JSONPath.

The target is frozen config, so the engine does not hand it to a parser whose accepted set moves
with a library release. A target is `$` followed by segments: `.name`, `.*`, `['name']`,
`["name"]`, `[*]`, `[index]` and `[start:end:step]` (RFC 9535 sections 2.2 to 2.5.1, 2.3.1 to
2.3.4). Descendant segments, filters, function extensions, unions and every jsonpath-ng extension
are refused. A quoted name `*` is refused too: jsonpath-ng reads it as a wildcard.

`parse_target` scans the text itself, and `TargetPath.find` evaluates it with our own code, so
neither the accepted set nor what a selector matches depends on a jsonpath-ng release (1.8 coerced
an array selector on an object, 1.16 does not). `tests/sentry/defects/test_nested_target_choke_point.py`
fails on a module that imports a jsonpath-ng parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Literal

__all__ = ["Match", "MatchPath", "Segment", "TargetPath", "TargetRefusal", "parse_target"]

# RFC 9535 section 2.1.1: the I-JSON integer range.
_MAX_INDEX: Final = 2**53 - 1
_INT: Final = re.compile(r"-?(?:0|[1-9][0-9]*)")
_ESCAPES: Final = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "/": "/", "\\": "\\"}
_HEX4: Final = re.compile(r"[0-9a-fA-F]{4}")

SegmentKind = Literal["name", "all_members", "all_items", "index", "slice"]


@dataclass(frozen=True)
class Segment:
    """One step of a target. `value` is the name, the index or the `(start, end, step)` triple."""

    kind: SegmentKind
    value: Any = None


@dataclass(frozen=True)
class MatchPath:
    """Where a match sits: the keys from the root, each a member name or an array position."""

    keys: tuple[str | int, ...]

    def update(self, root: Any, value: Any) -> Any:
        """The root with the value written at this path (the root itself for the empty path)."""
        if not self.keys:
            return value
        node = root
        for key in self.keys[:-1]:
            node = node[key]
        node[self.keys[-1]] = value
        return root

    def __str__(self) -> str:
        return ".".join(f"[{k}]" if isinstance(k, int) else k for k in self.keys)


@dataclass(frozen=True)
class Match:
    value: Any
    full_path: MatchPath


@dataclass(frozen=True)
class TargetPath:
    segments: tuple[Segment, ...]

    def find(self, root: Any) -> list[Match]:
        """Every value the target selects in one parsed cell.

        Rules, decided here and not left to a library: a name selects a member of an object; `.*`
        selects the members of an object or the items of an array (RFC 9535 2.3.2); `[*]`, an index
        and a slice select items of an array only. Applied to an object or a scalar they raise
        `TypeError` (the handler maps it to `nested_target_unwritable_container`), because a
        write-back could not replace what they would select there. A null selects nothing. An index
        outside the array selects nothing for that branch only. A name on a non-object selects
        nothing.
        """
        found = [Match(root, MatchPath(()))]
        for segment in self.segments:
            found = [hit for match in found for hit in _step(segment, match)]
        return found


def _step(segment: Segment, match: Match) -> list[Match]:
    value, keys = match.value, match.full_path.keys

    def at(key: str | int) -> Match:
        return Match(value[key], MatchPath((*keys, key)))

    if segment.kind == "name":
        return [at(segment.value)] if isinstance(value, dict) and segment.value in value else []
    if segment.kind == "all_members":
        if isinstance(value, dict):
            return [at(k) for k in value]
        return [at(i) for i in range(len(value))] if isinstance(value, list) else []
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("array selector on a value that is not an array")
    if segment.kind == "all_items":
        return [at(i) for i in range(len(value))]
    if segment.kind == "index":
        position = segment.value + len(value) if segment.value < 0 else segment.value
        return [at(position)] if 0 <= position < len(value) else []
    start, end, step = segment.value
    return [at(i) for i in range(*slice(start, end, step).indices(len(value)))]


@dataclass(frozen=True)
class TargetRefusal:
    """The target is outside the subset. `form` is a fixed phrase and never holds target text."""

    position: int
    form: str

    def __str__(self) -> str:
        return f"{self.form} at position {self.position}"


def _is_wide(ch: str) -> bool:
    return "\u0080" <= ch <= "\ud7ff" or "\ue000" <= ch <= "\U0010ffff"


def _is_name_first(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ch == "_" or _is_wide(ch)


def _stray(text: str, pos: int) -> TargetRefusal:
    """The refusal for a character no rule accepts at `pos`."""
    return TargetRefusal(pos, "blank space" if text[pos].isspace() else "unexpected character")


def parse_target(text: object) -> TargetPath | TargetRefusal:
    """The target as segments, or the `TargetRefusal` (position and form) of the first fault.

    Refusals are returned, not raised: the two callers turn one into their own coded error.
    """
    if not isinstance(text, str):
        return TargetRefusal(0, "target is not text")
    if not text.startswith("$"):
        return TargetRefusal(0, "missing root '$'")
    segments: list[Segment] = []
    pos = 1
    while pos < len(text):
        if text[pos] == ".":
            found = _dot_segment(text, pos)
        elif text[pos] == "[":
            found = _bracket_segment(text, pos)
        else:
            return _stray(text, pos)
        if isinstance(found, TargetRefusal):
            return found
        segment, pos = found
        segments.append(segment)
    return TargetPath(tuple(segments))


def _dot_segment(text: str, pos: int) -> tuple[Segment, int] | TargetRefusal:
    nxt = pos + 1
    if text.startswith("..", pos):
        return TargetRefusal(pos, "descendant segment")
    if nxt >= len(text):
        return TargetRefusal(nxt, "member name missing")
    if text[nxt] == "*":
        return Segment("all_members"), nxt + 1
    if text[nxt] in "'\"":
        return TargetRefusal(nxt, "quoted name after '.' (use brackets)")
    if not _is_name_first(text[nxt]):
        return TargetRefusal(nxt, "invalid member name")
    end = nxt + 1
    while end < len(text) and (_is_name_first(text[end]) or "0" <= text[end] <= "9"):
        end += 1
    return Segment("name", text[nxt:end]), end


def _bracket_segment(text: str, pos: int) -> tuple[Segment, int] | TargetRefusal:
    at = pos + 1
    if at >= len(text):
        return TargetRefusal(at, "unclosed bracket")
    ch = text[at]
    found: tuple[Segment, int] | TargetRefusal
    if ch == "*":
        found = Segment("all_items"), at + 1
    elif ch in "'\"":
        found = _quoted_segment(text, at, pos)
    elif ch == "?":
        return TargetRefusal(at, "filter selector")
    elif ch in "-0123456789:":
        found = _index_or_slice(text, at)
    else:
        return _stray(text, at)
    if isinstance(found, TargetRefusal):
        return found
    segment, at = found
    if at >= len(text):
        return TargetRefusal(at, "unclosed bracket")
    if text[at] == ",":
        return TargetRefusal(at, "multiple selectors in one bracket")
    if text[at] != "]":
        return _stray(text, at)
    return segment, at + 1


def _quoted_segment(text: str, at: int, bracket: int) -> tuple[Segment, int] | TargetRefusal:
    named = _quoted_name(text, at)
    if isinstance(named, TargetRefusal):
        return named
    name, end = named
    if name == "*":
        return TargetRefusal(bracket + 1, "quoted name '*' (a wildcard in jsonpath-ng)")
    return Segment("name", name), end


def _quoted_name(text: str, pos: int) -> tuple[str, int] | TargetRefusal:
    """A quoted name per RFC 9535 section 2.3.1.2, from the opening quote at `pos`."""
    quote = text[pos]
    out: list[str] = []
    at = pos + 1
    while at < len(text):
        ch = text[at]
        if ch == quote:
            return "".join(out), at + 1
        if ch == "\\":
            piece = _escape(text, at, quote)
            if isinstance(piece, TargetRefusal):
                return piece
            char, at = piece
            out.append(char)
        elif ch < " ":
            return TargetRefusal(at, "control character in name")
        else:
            out.append(ch)
            at += 1
    return TargetRefusal(len(text), "unclosed quoted name")


def _escape(text: str, pos: int, quote: str) -> tuple[str, int] | TargetRefusal:
    """The character one escape stands for and the position after it."""
    kind = text[pos + 1 : pos + 2]
    if kind == quote:
        return quote, pos + 2
    if kind in _ESCAPES:
        return _ESCAPES[kind], pos + 2
    if kind != "u":
        return TargetRefusal(pos, "invalid escape")
    unit = _hex4(text, pos + 2)
    if unit is None:
        return TargetRefusal(pos, "invalid unicode escape")
    code, after = unit
    if 0xDC00 <= code <= 0xDFFF:
        return TargetRefusal(pos, "unpaired surrogate escape")
    if not 0xD800 <= code <= 0xDBFF:
        return chr(code), after
    low_unit = _hex4(text, after + 2) if text[after : after + 2] == "\\u" else None
    if low_unit is None or not 0xDC00 <= low_unit[0] <= 0xDFFF:
        return TargetRefusal(pos, "unpaired surrogate escape")
    low, after = low_unit
    return chr(0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)), after


def _hex4(text: str, pos: int) -> tuple[int, int] | None:
    if not _HEX4.fullmatch(text, pos, pos + 4):
        return None
    return int(text[pos : pos + 4], 16), pos + 4


def _int(text: str, pos: int) -> tuple[int | None, int] | TargetRefusal:
    """An optional index-form integer at `pos`: no leading zero, not `-0`, within 2^53 - 1."""
    if pos >= len(text) or text[pos] not in "-0123456789":
        return None, pos
    found = _INT.match(text, pos)
    if found is None or found.group() == "-0":
        return TargetRefusal(pos, "invalid integer")
    end = found.end()
    if end < len(text) and "0" <= text[end] <= "9":
        return TargetRefusal(pos, "leading zero in integer")
    value = int(found.group())
    if abs(value) > _MAX_INDEX:
        return TargetRefusal(pos, "integer outside the 2^53 - 1 range")
    return value, end


def _index_or_slice(text: str, pos: int) -> tuple[Segment, int] | TargetRefusal:
    first = _int(text, pos)
    if isinstance(first, TargetRefusal):
        return first
    start, at = first
    if at < len(text) and text[at] == ":":
        return _slice_rest(text, start, at + 1)
    if start is None:
        return TargetRefusal(at, "unclosed bracket")
    return Segment("index", start), at


def _slice_rest(text: str, start: int | None, pos: int) -> tuple[Segment, int] | TargetRefusal:
    """The end and the optional step of a slice whose first colon is just before `pos`."""
    second = _int(text, pos)
    if isinstance(second, TargetRefusal):
        return second
    end, at = second
    step: int | None = None
    if at < len(text) and text[at] == ":":
        third = _int(text, at + 1)
        if isinstance(third, TargetRefusal):
            return third
        step, after = third
        if step is not None and step < 1:
            return TargetRefusal(at + 1, "slice step must be 1 or more")
        at = after
    return Segment("slice", (start, end, step)), at
