"""The log-record filter: exception text never reaches a handler's formatter.

Pattern source: the stdlib logging cookbook ("Using Filters to impart contextual information")
and the OWASP Logging Cheat Sheet, which says to sanitize at the logging layer rather than at
each call. A `logging.Filter` on a handler runs before that handler's formatter, so it sees the
record while it can still change what is printed.

What the filter rewrites, in place on the record:

- an exception in `msg` or in `args` (a tuple item or a mapping value) becomes its closed type
  label (`safe_error_type`), so `%s` and `%r` print the label. The same holds one level inside
  a list, tuple, set, frozenset, dict or `UserDict` (keys and values) used as an argument or as
  `msg`. A lone mapping argument is `args` itself and follows the same rule (`_scan_mapping`);
- live `exc_info` becomes a traceback of labels and `file:line, in function` frames, with no
  exception text, no source lines and no frame locals; `exc_info` is then cleared so the
  formatter cannot render the raw one;
- a cached `exc_text` with no live traceback is dropped unless this filter wrote it, so text a
  host formatter cached earlier never passes, while a second filtered handler prints the same
  safe traceback as the first.

The scan reads containers through their builtin base type only, so it runs no caller code: no
overridden `items` or `__iter__`, no `default_factory`, no lazy mapping such as a
`ConfigParser` section. A container with nothing to replace is returned as is, identity
included. One that changes is rebuilt as a new builtin of the same kind and keeps no reference
to the caller's object, so no formatter field (`{args.x[y]}`) can reach an original value, and
the caller's data is never changed. A mapping whose missing-key lookup the filter cannot
vouch for is rebuilt even when its items are clean (`_Lookup`).

`stack_info` holds code locations and engine source lines (code, not data) and is kept.

Gaps, each pinned by a strict xfail cell in `tests/unit/safe_output/test_log_filter.py`; the
call-site guard `tests/sentry/test_log_interpolation.py` covers them instead:

- text already formatted into `msg` (an f-string, or `str(exc)` passed as an argument), which
  cannot be told apart from any other text here;
- `exc.args` (or any part of an exception) passed as an argument, since it is plain data;
- an arbitrary wrapper object whose `__str__` or `__repr__` calls `str(exc)`, including a
  mapping type other than dict and `UserDict`, which the scan does not open;
- an exception nested deeper than one container level.
"""

from __future__ import annotations

import logging
from collections import Counter, OrderedDict, UserDict, defaultdict
from collections.abc import Callable
from enum import Enum
from types import TracebackType
from typing import Any, cast

from decoy_engine.safe_output._exception import safe_error_type

# The record attribute that holds the traceback text this filter wrote.
_SAFE_EXC_TEXT = "_decoy_safe_exc_text"
# Bounds the cause/context walk; links past it are not printed.
_MAX_CHAIN = 16
_UNRENDERABLE = "log record could not be made safe"
# `args` holds the arguments themselves, so it is scanned one container level deeper than `msg`.
_ARGS_DEPTH = 2
_SEQUENCES = (list, tuple, set, frozenset)
# Factories that build an empty builtin: a defaultdict using one keeps its identity.
_EMPTY_FACTORIES = (int, float, complex, bool, str, bytes, list, tuple, dict, set, frozenset)
_FACTORY_FAILED = "default factory failed"
_NO_VALUE = object()


class _Label(str):
    """A type label that prints the same under `%s` and `%r`."""

    __slots__ = ()

    def __repr__(self) -> str:
        return str.__str__(self)


def _label(exc: BaseException) -> _Label:
    return _Label(safe_error_type(exc).value)


class _Lookup(Enum):
    """What a missing-key lookup on a mapping does, read from its type alone."""

    BUILTIN = "builtin"  # KeyError, Counter's 0, or a factory from `_EMPTY_FACTORIES`
    FACTORY = "factory"  # defaultdict: calls a caller's `default_factory`
    CALLER = "caller"  # a `__getitem__` or `__missing__` the caller wrote


def _factory_of(value: dict[object, object]) -> Callable[[], object] | None:
    # The C slot `defaultdict.__missing__` reads, not an attribute a subclass may override.
    slot: Any = vars(defaultdict)["default_factory"]
    return cast("Callable[[], object] | None", slot.__get__(value))


def _lookup_of(value: dict[object, object] | UserDict[object, object]) -> _Lookup:
    kind = type(value)
    # Identity checks only: `in` or `==` would call a caller's `__eq__`.
    getitem = kind.__getitem__
    if getitem is not dict.__getitem__ and getitem is not UserDict.__getitem__:
        return _Lookup.CALLER
    missing = getattr(kind, "__missing__", None)
    if missing is None or missing is Counter.__missing__:
        return _Lookup.BUILTIN
    if missing is defaultdict.__missing__:
        factory = _factory_of(value)  # type: ignore[arg-type]
        if factory is None or any(factory is f for f in _EMPTY_FACTORIES):
            return _Lookup.BUILTIN
        return _Lookup.FACTORY
    return _Lookup.CALLER


class _ScannedFactory:
    """A copy's `default_factory`: the caller's factory, with its result scanned.

    Holds the factory only. A formatter field cannot call it, so no value it builds is
    reachable from the record; `repr` is the factory's, so the copy prints like the original.
    """

    __slots__ = ("_depth", "_factory")

    def __init__(self, factory: Callable[[], object], depth: int) -> None:
        self._factory = factory
        self._depth = depth

    def __call__(self) -> object:
        value = _NO_VALUE
        try:
            value = _scan(self._factory(), self._depth)
        except Exception:
            # The factory's own error text is not carried over.
            pass
        if value is _NO_VALUE:
            raise LookupError(_FACTORY_FAILED)
        return value

    def __repr__(self) -> str:
        return repr(self._factory)


def _store_of(value: object) -> dict[object, object] | None:
    """The builtin dict holding a mapping's items, or None for a type the scan does not open."""
    # `issubclass(type(...))`, not `isinstance`, which falls back to a caller's `__class__`.
    if issubclass(type(value), dict):
        return value  # type: ignore[return-value]
    if issubclass(type(value), UserDict):
        data = vars(value).get("data")
        return data if issubclass(type(data), dict) else None
    return None


def _scan_pairs(store: dict[object, object], depth: int) -> list[tuple[object, object]] | None:
    """`store`'s items with keys and values scanned, or None when none of them change.

    The one key/value scan: every mapping, the lone mapping argument included, goes through it.
    """
    pairs = list(dict.items(store))
    scanned = [(_scan(k, depth), _scan(v, depth)) for k, v in pairs]
    if all(nk is k and nv is v for (k, v), (nk, nv) in zip(pairs, scanned, strict=True)):
        return None
    return scanned


def _scan_mapping(value: object, store: dict[object, object], depth: int) -> object:
    lookup = _lookup_of(value)  # type: ignore[arg-type]
    scanned = _scan_pairs(store, depth - 1)
    if scanned is None and lookup is _Lookup.BUILTIN:
        return value
    pairs = scanned if scanned is not None else list(dict.items(store))
    if lookup is _Lookup.CALLER:
        # The caller's lookup cannot be reused, so a missing key raises a plain KeyError.
        return dict(pairs)
    kind = type(value)
    if issubclass(kind, defaultdict):
        factory = _factory_of(value)  # type: ignore[arg-type]
        if factory is not None and lookup is _Lookup.FACTORY:
            factory = _ScannedFactory(factory, depth - 1)
        return defaultdict(factory, pairs)
    if issubclass(kind, Counter):
        return Counter(dict(pairs))
    if issubclass(kind, OrderedDict):
        return OrderedDict(pairs)
    return dict(pairs)


def _scan(value: object, depth: int) -> object:
    """`value` with exceptions swapped for labels, `depth` container levels down.

    Dispatches on `type(value)` and reads containers through their builtin base, so no caller
    code runs. Returns `value` itself when nothing in it changes.
    """
    kind = type(value)
    if issubclass(kind, BaseException):
        return _label(value)  # type: ignore[arg-type]
    if depth == 0:
        return value
    for base in _SEQUENCES:
        if issubclass(kind, base):
            items: list[object] = list(cast("Any", base).__iter__(value))
            new = [_scan(v, depth - 1) for v in items]
            if all(n is o for n, o in zip(new, items, strict=True)):
                return value
            return base(new)
    store = _store_of(value)
    if store is None:
        return value
    return _scan_mapping(value, store, depth)


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
    record.msg = _scan(record.msg, 1)
    # `args` is the positional tuple or, when the only argument is a non-empty mapping, that
    # mapping itself (`LogRecord.__init__`). A lone mapping gets no wrapper of its own: like any
    # mapping, it is replaced only when `_scan_mapping` must replace it.
    record.args = _scan(record.args, _ARGS_DEPTH)  # type: ignore[assignment]

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
