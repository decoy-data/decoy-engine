"""One canonical JSON owner for every digest, signature and seed fingerprint.

Both forms sort keys, use compact separators, refuse NaN and Infinity and write UTF-8. They differ
in one argument, ``ensure_ascii``:

* ``canonical_json_bytes`` writes text as-is. This is the records rule (and the platform's), so a
  record id and the CLI evidence manifest hash agree on bytes. Every digest uses it.
* ``seed_fingerprint_bytes`` escapes non-ASCII text. Two seed inputs were hashed that way before
  this module existed, so their bytes are frozen under ``SEED_PROTOCOL_VERSION``: changing them
  would move every generated column for a non-ASCII config.

The encoder never converts silently. A ``date`` and a timezone-aware ``datetime`` become
``isoformat()``; a naive ``datetime`` is refused because reading it as host time would make the
bytes depend on the machine; every other non-JSON type is refused. An unpaired surrogate in a
string or an object key is refused before encoding: the ASCII form would otherwise escape it and
the UTF-8 form would crash on it with codec text.

``strict_json_loads`` is the matching strict reader: it refuses a duplicate key, NaN or Infinity and
an over-long integer, and names the defect as a closed token, never as input text.
``strict_json_read`` is the same reader with bounds (bytes, depth) and a number-lexeme mode for the
nested strategy; ``strict_json_write`` writes such a tree back without changing a number.

Every refusal is raised after the encoder or the walk has returned, outside any ``except`` block,
so the error holds no ``__context__`` and no text of the value.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from decoy_engine import reasons
from decoy_engine._error_base import DecoyError

__all__ = [
    "MASK_CELL_BYTES",
    "MASK_MAX_DEPTH",
    "STRICT_JSON_TOKENS",
    "CanonicalJsonError",
    "CanonicalStringError",
    "JsonNumber",
    "StrictJsonError",
    "canonical_json_bytes",
    "seed_fingerprint_bytes",
    "strict_json_loads",
    "strict_json_plain",
    "strict_json_read",
    "strict_json_write",
]

# Bounds for one nested-mask cell. A cell over either bound is refused with a closed token before
# any rule runs, so a hostile or broken cell cannot exhaust memory or the parser stack.
MASK_CELL_BYTES: Final = 16 * 1024 * 1024
MASK_MAX_DEPTH: Final = 64

# A number the lexeme reader may have to keep: an exponent, a trailing zero, a long run of digits,
# a leading `.0000` (Python prints those as an exponent) or `-0`. It over-matches on purpose: text
# inside a string also sends a cell to the hook path, which is slower and always correct.
_LOSSY_HINT = re.compile(r"[eE]|\.\d*0(?!\d)|\.0000|\d{16}|-0(?![.\d])")
_SURROGATE = re.compile("[\ud800-\udfff]")
# A lone surrogate written by the ASCII encoder is always `\ud8xx` to `\udfxx`. A literal
# backslash-u in data is written `\\u`, which also matches here, so a hit only asks for the walk.
_ESCAPED_SURROGATE = re.compile(r"\\u[dD][89a-fA-F][0-9a-fA-F]{2}")


class CanonicalJsonError(DecoyError, ValueError):
    """A value cannot be written in canonical JSON. Value-free: it names a type at most.

    It is a ``ValueError`` so the records codec's ``except ValueError`` arms turn it into the
    coded ``record_invalid``.
    """

    code = reasons.config.CONFIG_VALUE_NOT_JSON

    def __init__(self, message: str, type_name: str | None = None) -> None:
        super().__init__(message, type_name)
        self.message = message
        self.type_name = type_name

    def __str__(self) -> str:
        return self.message


class CanonicalStringError(CanonicalJsonError):
    """A string or object key holds an unpaired surrogate, so it has no UTF-8 form."""

    code = reasons.config.CANONICAL_JSON_INVALID_STRING

    def __init__(self) -> None:
        super().__init__(_summary(self.code))

    def __reduce__(self) -> tuple[type[CanonicalStringError], tuple[()]]:
        return (type(self), ())


def _summary(code: str) -> str:
    return reasons.REASONS[("config", code)].summary


def _has_surrogate(value: Any) -> bool:
    """Whether any string value or object key holds a code point in the surrogate range."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if _SURROGATE.search(item):
                return True
        elif isinstance(item, dict):
            for key, child in item.items():
                if isinstance(key, str) and _SURROGATE.search(key):
                    return True
                stack.append(child)
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
    return False


def _encode(value: object, *, ensure_ascii: bool) -> bytes:
    refused: list[str] = []

    def default(item: object) -> str:
        if isinstance(item, dt.datetime):
            if item.utcoffset() is not None:
                return item.isoformat()
        elif isinstance(item, dt.date):
            return item.isoformat()
        refused.append(type(item).__name__)
        raise TypeError

    text: str | None = None
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=ensure_ascii,
            default=default,
        )
    except (TypeError, ValueError, RecursionError):
        pass
    if text is None:
        if refused:
            raise CanonicalJsonError(
                f"Canonical JSON cannot encode a value of type {refused[0]}.", refused[0]
            )
        raise CanonicalJsonError(
            "Canonical JSON cannot encode a non-finite number, a circular value "
            "or object keys of mixed types."
        )
    hint = _ESCAPED_SURROGATE if ensure_ascii else _SURROGATE
    if hint.search(text) and _has_surrogate(value):
        raise CanonicalStringError()
    return text.encode("utf-8")


def canonical_json_bytes(value: object) -> bytes:
    """The digest form: sorted, compact, UTF-8 text written as-is. Raises ``CanonicalJsonError``."""
    return _encode(value, ensure_ascii=False)


def seed_fingerprint_bytes(value: object) -> bytes:
    """The frozen seed form: as ``canonical_json_bytes`` but non-ASCII text is ``\\uXXXX`` escaped.

    Callable only from ``strategy_config_fingerprint`` and the pool ``_config_hash``; a sentry
    holds that list. Changing a byte this writes is a seed protocol change.
    """
    return _encode(value, ensure_ascii=True)


STRICT_JSON_TOKENS = (
    "not_json",
    "duplicate_key",
    "non_finite",
    "out_of_range",
    "oversized",
    "too_deep",
    "negative_zero",
    "float",
    "invalid_unicode",
)


class StrictJsonError(CanonicalJsonError):
    """Strict JSON was refused. ``token`` is one of ``STRICT_JSON_TOKENS``; no input text.

    It sits under ``CanonicalJsonError`` so it is a ``DecoyError`` and a ``ValueError`` in the
    registered config family, with no new exception family to classify.
    """

    def __init__(self, token: str) -> None:
        super().__init__(token)
        self.token = token

    def __reduce__(self) -> tuple[type[StrictJsonError], tuple[str]]:
        return (type(self), (self.token,))


@dataclass(frozen=True)
class JsonNumber:
    """A JSON number with its source text. ``value`` is ``None`` for an integer too long for ``int``.

    Lexeme mode returns one only for a number that ``json.dumps`` would print differently (``1.10``,
    ``1e400``, ``-0``, a long decimal), so an unselected number is written back exactly as read.
    A number that prints as read stays a plain ``int`` or ``float``.
    """

    value: int | float | None
    lexeme: str = field(repr=False)


def _oversized(text: str, max_bytes: int) -> bool:
    """Whether the UTF-8 length of ``text`` is over ``max_bytes``. Never raises, whatever the text."""
    if len(text) > max_bytes:
        return True  # every character is at least one byte
    if len(text) * 4 <= max_bytes:
        return False  # no character is more than four bytes
    return len(text.encode("utf-8", "surrogatepass")) > max_bytes


def _deeper_than(parsed: Any, max_depth: int) -> bool:
    """Whether containers nest more than ``max_depth`` levels. Iterative, so it cannot recurse."""
    stack: list[tuple[Any, int]] = [(parsed, 0)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, dict):
            children: Any = item.values()
        elif isinstance(item, list):
            children = item
        else:
            continue
        if depth + 1 > max_depth:
            return True
        stack.extend((child, depth + 1) for child in children)
    return False


def strict_json_read(
    data: bytes | str,
    *,
    max_bytes: int | None = None,
    max_depth: int | None = None,
    non_finite: Literal["refuse", "keep"] = "refuse",
    keep_lexemes: bool = False,
    max_int_digits: int | None = 20,
    forbid_float: bool = False,
    forbid_negative_zero: bool = False,
    forbid_lone_surrogate: bool = False,
) -> Any:
    """Parse JSON under bounds, refusing a duplicate key and a lone surrogate in the text.

        ``max_bytes`` and ``max_depth`` bound the cell (``oversized``, ``too_deep``); ``None`` sets no
        bound. ``non_finite="keep"`` accepts ``NaN``, ``Infinity`` and ``-Infinity`` as floats and
        ``"refuse"`` names them ``non_finite``. ``keep_lexemes`` returns every number as a
        ``JsonNumber``; an integer too long for ``int`` then has ``value=None`` instead of failing.

        Two opt-in options serve profiles with no float and no ``-0``: ``forbid_float`` records
        ``float`` for any fraction or exponent number and ``forbid_negative_zero`` records
        ``negative_zero`` for the integer text ``-0``. ``forbid_lone_surrogate`` records
    ``invalid_unicode`` for an escaped lone surrogate (``"\\ud800"``) in a string or key; a raw one is
    always refused. All default off, so the defaults read as before.

        The hooks only record a defect and parsing goes on, so nothing raises inside the handler. The
        error is raised after it, with no ``__context__`` and no input text. Raises ``StrictJsonError``.
    """
    found: list[str] = []

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        members = dict(items)
        if len(members) != len(items):
            found.append("duplicate_key")
        return members

    def constant(name: str) -> float | None:
        if non_finite == "keep":
            return float(name)
        found.append("non_finite")
        return None

    def integer(text: str) -> Any:
        if forbid_negative_zero and text == "-0":
            found.append("negative_zero")
            return None
        if max_int_digits is not None and len(text.lstrip("-")) > max_int_digits:
            found.append("out_of_range")
            return None
        if not keep_lexemes:
            return int(text)
        try:
            number = int(text)
        except ValueError:  # past CPython's integer string limit: keep the lexeme only
            return JsonNumber(None, text)
        return number if str(number) == text else JsonNumber(number, text)

    def real(text: str) -> Any:
        if forbid_float:
            found.append("float")
        number = float(text)
        if not keep_lexemes:
            return number
        return number if json.dumps(number) == text else JsonNumber(number, text)

    parsed: Any = None
    malformed = False
    too_big = False
    too_deep = False
    walk_depth = True
    try:
        if max_bytes is not None and isinstance(data, bytes) and len(data) > max_bytes:
            too_big = True
        else:
            text = data.decode("utf-8") if isinstance(data, bytes) else data
            if max_bytes is not None and _oversized(text, max_bytes):
                too_big = True
            else:
                if not text.isascii():
                    text.encode("utf-8")  # a raw lone surrogate is not RFC 8259 text
                # Containers open with one bracket each, so a text with few of them cannot be deep.
                walk_depth = max_depth is not None and (
                    text.count("[") + text.count("{") > max_depth
                )
                # No number can be lossy in most cells, so the C parser reads them with no hook.
                lexemes = keep_lexemes and (
                    max_int_digits is not None or bool(_LOSSY_HINT.search(text))
                )
                hooked = lexemes or forbid_float or forbid_negative_zero
                parsed = json.loads(
                    text,
                    object_pairs_hook=pairs,
                    parse_constant=constant,
                    parse_int=integer if hooked or not keep_lexemes else None,
                    parse_float=real if hooked else None,
                )
    except (UnicodeError, ValueError):
        malformed = True
    except RecursionError:
        too_deep = max_depth is not None
        malformed = not too_deep
    if too_big:
        raise StrictJsonError("oversized")
    if malformed:
        raise StrictJsonError("not_json")
    if too_deep or (walk_depth and max_depth is not None and _deeper_than(parsed, max_depth)):
        raise StrictJsonError("too_deep")
    if forbid_lone_surrogate and _has_surrogate(parsed):
        found.append("invalid_unicode")
    if found:
        raise StrictJsonError(found[0])
    return parsed


def strict_json_loads(
    data: bytes | str,
    *,
    max_int_digits: int | None = 20,
    forbid_float: bool = False,
    forbid_negative_zero: bool = False,
    forbid_lone_surrogate: bool = False,
) -> Any:
    """Parse JSON, refusing a duplicate key, a non-finite number, a raw lone surrogate in the text
    and an integer longer than ``max_int_digits`` digits (``None`` sets no digit limit).
    Raises ``StrictJsonError``.
    """
    return strict_json_read(
        data,
        max_int_digits=max_int_digits,
        forbid_float=forbid_float,
        forbid_negative_zero=forbid_negative_zero,
        forbid_lone_surrogate=forbid_lone_surrogate,
    )


_SCALARS = frozenset({str, int, float, bool, type(None)})


def strict_json_plain(value: Any) -> Any:
    """``value`` with every ``JsonNumber`` replaced by its plain ``int`` or ``float``.

    Raises ``StrictJsonError("out_of_range")`` for a number that has no plain value.
    """
    if type(value) in _SCALARS:
        return value
    refused = False

    def walk(item: Any) -> Any:
        nonlocal refused
        if isinstance(item, JsonNumber):
            if item.value is None:
                refused = True
            return item.value
        if isinstance(item, dict):
            return {key: walk(child) for key, child in item.items()}
        if isinstance(item, list):
            return [walk(child) for child in item]
        return item

    plain = walk(value)
    if refused:
        raise StrictJsonError("out_of_range")
    return plain


def _key_text(key: Any) -> str:
    """The quoted member name exactly as ``json.dumps`` writes it, including its key coercions."""
    return json.dumps({key: 0})[1:-4]


def _write_lexemes(value: Any) -> str:
    """The ``json.dumps`` form, with each ``JsonNumber`` written as its source text."""
    if isinstance(value, JsonNumber):
        return value.lexeme
    if isinstance(value, dict):
        members = (f"{_key_text(key)}: {_write_lexemes(child)}" for key, child in value.items())
        return "{" + ", ".join(members) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_write_lexemes(child) for child in value) + "]"
    return json.dumps(value)


def _has_number(value: Any) -> bool:
    """Whether ``value`` holds a ``JsonNumber``. Only a lossy number is one, so most cells hold none."""
    if type(value) is JsonNumber:
        return True
    if type(value) is not dict and type(value) is not list:
        return False
    stack = [value]
    while stack:
        item = stack.pop()
        for child in item.values() if type(item) is dict else item:
            kind = type(child)
            if kind is JsonNumber:
                return True
            if kind is dict or kind is list:
                stack.append(child)
    return False


def strict_json_write(value: Any) -> str:
    """Write a tree read with ``keep_lexemes`` back as JSON text, never changing a number.

    A tree with no ``JsonNumber`` is exactly ``json.dumps`` of it, so the bytes equal what the
    strategy wrote before lexemes were kept.
    """
    return _write_lexemes(value) if _has_number(value) else json.dumps(value)
