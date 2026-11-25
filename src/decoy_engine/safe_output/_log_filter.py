"""The log-record filter: exception text never reaches a handler's formatter.

Pattern source: the stdlib logging cookbook ("Using Filters to impart contextual information")
and the OWASP Logging Cheat Sheet, which says to sanitize at the logging layer rather than at
each call. A `logging.Filter` on a handler runs before that handler's formatter, so it sees the
record while it can still change what is printed. The closed type table follows the Sentry SDK
serializer (walk the types you know, send everything else through one fallback) with a fixed
placeholder as the fallback, because `repr` is caller code.

What the filter rewrites, in place on the record:

- every value it writes back comes from one function, `_safe_value`, which decides by exact
  type and runs no caller code. An exception becomes its closed type label
  (`safe_error_type`). Any mapping that is not an exact `dict` (a `dict` subclass, `OrderedDict`,
  `Counter`, `defaultdict`, `UserDict`, `mappingproxy`, `ChainMap`, a `ConfigParser` section, a
  caller `Mapping`) becomes the placeholder `<mapping>`, clean or not, so no lookup, factory or
  order of a caller type can be reached. A `dict` with a key that is not an exact `str`, `int`,
  `float`, `bool` or `None` is the placeholder too: keys are never rewritten. Plain containers
  (`list`, `tuple`, `set`, `frozenset` and their subclasses, `dict`) are opened one level deep
  in `msg` and two in `args`; a changed one is a new plain container, an unchanged one is
  returned as is;
- one function, `_safe_pairs`, reads the items of a `dict` (`dict.items(store)` and nothing
  else, so no stored key is compared or hashed by caller code). Row 6, the named values and the
  display of a lone mapping all take its result, so their depth cannot differ;
- a lone mapping argument (`LogRecord` makes `args` the mapping itself) becomes a `_NamedArgs`:
  a new `dict` of the exact-`str` keys with their scanned values, a value-free default for a
  missing name, a truthy `bool`, and a display that is computed only when `%s`, `%r` or a
  brace `{args}` asks for it. A second filter pass keeps it unchanged;
- live `exc_info` becomes a traceback of labels and `file:line, in function` frames, with no
  exception text, no source lines and no frame locals; `exc_info` is then cleared so the
  formatter cannot render the raw one;
- a cached `exc_text` with no live traceback is dropped unless this filter wrote it, so text a
  host formatter cached earlier never passes, while a second filtered handler prints the same
  safe traceback as the first.

`stack_info` holds code locations and engine source lines (code, not data) and is kept.

Gaps, each pinned by a strict xfail cell in `tests/unit/safe_output/test_log_filter.py`; the
call-site guard `tests/sentry/test_log_interpolation.py` covers them instead:

- text already formatted into `msg` (an f-string, or `str(exc)` passed as an argument), which
  cannot be told apart from any other text here;
- `exc.args` (or any part of an exception) passed as an argument, since it is plain data;
- an arbitrary wrapper object whose `__str__` or `__repr__` calls `str(exc)`;
- an exception nested deeper than the scan depth.
"""

from __future__ import annotations

import logging
from collections import Counter, UserDict, defaultdict
from collections.abc import Mapping, Sequence
from types import TracebackType

from decoy_engine.safe_output._exception import safe_error_type

# The record attribute that holds the traceback text this filter wrote.
_SAFE_EXC_TEXT = "_decoy_safe_exc_text"
# Bounds the cause/context walk; links past it are not printed.
_MAX_CHAIN = 16
_UNRENDERABLE = "log record could not be made safe"
# `args` holds the arguments themselves, so it is scanned one container level deeper than `msg`.
_ARGS_DEPTH = 2
# Each base type with its unbound iterator, so a subclass `__iter__` never runs.
_SEQUENCES = (
    (list, list.__iter__),
    (tuple, tuple.__iter__),
    (set, set.__iter__),
    (frozenset, frozenset.__iter__),
)
_PLAIN_VALUE_TYPES = (str, bytes, int, float, complex, bool, type(None))
_PLAIN_KEY_TYPES = (str, int, float, bool, type(None))
# Factories that build an empty builtin: a missing name on such a defaultdict has a safe default.
_EMPTY_FACTORIES = (int, float, complex, bool, str, bytes, list, tuple, dict, set, frozenset)


class _Label(str):
    """A text that prints the same under `%s` and `%r`."""

    __slots__ = ()

    def __repr__(self) -> str:
        return str.__str__(self)


_MAPPING_PLACEHOLDER = _Label("<mapping>")


def _label(exc: BaseException) -> _Label:
    return _Label(safe_error_type(exc).value)


def _is_exact(value: object, types: tuple[type, ...]) -> bool:
    kind = type(value)
    return any(kind is t for t in types)


def _safe_pairs(
    store: dict[object, object], depth: int
) -> tuple[list[tuple[object, object]], bool, bool]:
    """The one reader of mapping items: `(pairs, plain, changed)` from a single traversal.

    `pairs` holds each admitted key (exact plain type) with its value scanned once at
    `depth - 1`. `plain` is true when every key was admitted. `changed` is true when a scanned
    value is not the stored one.
    """
    pairs: list[tuple[object, object]] = []
    plain = True
    changed = False
    for key, value in dict.items(store):
        if not _is_exact(key, _PLAIN_KEY_TYPES):
            plain = False
            continue
        scanned = _safe_value(value, depth - 1)
        if scanned is not value:
            changed = True
        pairs.append((key, scanned))
    return pairs, plain, changed


def _safe_value(value: object, depth: int) -> object:
    """`value` as it may be written back: the one closed type table (module docstring).

    Rows run in order and the first match wins. Rows 1 and 2 come before the depth check, so an
    exception or a non-plain mapping is replaced at every position the scan reaches.
    """
    kind = type(value)
    if issubclass(kind, BaseException):
        return _label(value)  # type: ignore[arg-type]
    if kind is not dict and (issubclass(kind, Mapping) or issubclass(kind, UserDict)):
        return _MAPPING_PLACEHOLDER
    if depth == 0 or _is_exact(value, _PLAIN_VALUE_TYPES):
        return value
    for base, iterate in _SEQUENCES:
        if issubclass(kind, base):
            items: list[object] = list(iterate(value))  # type: ignore[arg-type]
            new = [_safe_value(v, depth - 1) for v in items]
            if all(n is o for n, o in zip(new, items, strict=True)):
                return value
            return base(new)
    if kind is dict:
        pairs, plain, changed = _safe_pairs(value, depth)  # type: ignore[arg-type]
        if not plain:
            return _MAPPING_PLACEHOLDER
        return dict(pairs) if changed else value
    return value


class _NamedArgs(dict[object, object]):
    """`record.args` for a lone mapping: safe named values, no caller object, lazy display."""

    __slots__ = ("_default", "_display")

    def __init__(
        self,
        pairs: Sequence[tuple[object, object]],
        default: object,
        display: dict[object, object] | None,
    ) -> None:
        super().__init__(pairs)
        self._default = default
        self._display = display

    def __missing__(self, key: object) -> object:
        return self._default

    def __bool__(self) -> bool:
        # `LogRecord.getMessage` formats only when `args` is truthy, so `%%` needs this.
        return True

    def __repr__(self) -> str:
        # Computed on use: an unused value that cannot be printed must not drop the record.
        if self._display is None:
            return str(_MAPPING_PLACEHOLDER)
        try:
            return repr(self._display)
        except Exception:
            return str(_MAPPING_PLACEHOLDER)

    __str__ = __repr__


def _default_for(mapping: object) -> object:
    """The value-free result for a missing name, chosen once from the mapping's exact type."""
    kind = type(mapping)
    if kind is Counter:
        return 0
    if kind is defaultdict:
        # The C slot `defaultdict.__missing__` reads, not an attribute a subclass may override.
        factory = vars(defaultdict)["default_factory"].__get__(mapping)
        if any(factory is f for f in _EMPTY_FACTORIES):
            return factory()
    return _MAPPING_PLACEHOLDER


def _named_args(mapping: object) -> _NamedArgs:
    kind = type(mapping)
    store: dict[object, object] | None = None
    if issubclass(kind, dict):
        store = mapping  # type: ignore[assignment]
    elif issubclass(kind, UserDict):
        try:
            data = vars(mapping)["data"]
        except (KeyError, TypeError):
            data = None
        if type(data) is dict:
            store = data
    pairs: list[tuple[object, object]] = []
    plain = False
    if store is not None:
        pairs, plain, _ = _safe_pairs(store, _ARGS_DEPTH)
    display = dict(pairs) if kind is dict and plain else None
    named = [(k, v) for k, v in pairs if type(k) is str]
    return _NamedArgs(named, _default_for(mapping), display)


def _frames(tb: TracebackType | None) -> list[str]:
    lines = []
    while tb is not None:
        code = tb.tb_frame.f_code
        lines.append(f'  File "{code.co_filename}", line {tb.tb_lineno}, in {code.co_name}')
        tb = tb.tb_next
    return lines


def _chain(exc: BaseException) -> list[BaseException]:
    """`exc` and its causes, oldest first, the order a stock traceback prints them."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < _MAX_CHAIN:
        seen.add(id(current))
        chain.append(current)
        cause = current.__cause__
        if cause is None and not current.__suppress_context__:
            cause = current.__context__
        current = cause
    return chain[::-1]


def _safe_traceback(exc: BaseException) -> str:
    parts: list[str] = []
    for exc_link in _chain(exc):
        if parts:
            parts.append("The above exception led to the following exception:")
        parts.append("Traceback (most recent call last):")
        parts.extend(_frames(exc_link.__traceback__))
        parts.append(_label(exc_link))
    return "\n".join(parts)


def _scrub(record: logging.LogRecord) -> None:
    record.msg = _safe_value(record.msg, 1)
    args: object = record.args
    if type(args) is _NamedArgs:
        # A second filter pass: the keys and values already came from one pass.
        pass
    elif issubclass(type(args), Mapping) or issubclass(type(args), UserDict):
        # `LogRecord.__init__` makes `args` the mapping itself for a lone non-empty mapping.
        record.args = _named_args(args)  # type: ignore[assignment]
    else:
        record.args = _safe_value(args, _ARGS_DEPTH)  # type: ignore[assignment]

    exc = record.exc_info[1] if record.exc_info else None
    if exc is not None:
        text = _safe_traceback(exc)
        setattr(record, _SAFE_EXC_TEXT, text)
        record.exc_text = text
    elif record.exc_text != getattr(record, _SAFE_EXC_TEXT, None):
        record.exc_text = None
    record.exc_info = None


class SafeRecordFilter(logging.Filter):
    """Rewrites each record so its handler prints no exception text (module docstring).

    Public so a host program attaches it to its own handlers; the engine attaches it to every
    handler it builds.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            _scrub(record)
        except Exception:
            # A failure here must not raise inside logging or let the raw record through.
            record.msg, record.args = _UNRENDERABLE, ()
            record.exc_info = record.exc_text = None
        return True
