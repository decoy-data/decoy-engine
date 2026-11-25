"""The log-record filter: exception text never reaches a handler's formatter.

Pattern source: the stdlib logging cookbook ("Using Filters to impart contextual information")
and the OWASP Logging Cheat Sheet, which says to sanitize at the logging layer rather than at
each call. A `logging.Filter` on a handler runs before that handler's formatter, so it sees the
record while it can still change what is printed.

What the filter rewrites, in place on the record:

- an exception in `msg` or in `args` (a tuple item or a mapping value) becomes its closed type
  label (`safe_error_type`), so `%s` and `%r` print the label. The same holds one level inside
  a list, tuple, set, frozenset or mapping (keys and values; a mapping that needs no change is
  left as is, and one that does keeps its type and `__missing__`) used as an argument or as `msg`;
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
- an exception nested deeper than one container level.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping
from types import TracebackType

from decoy_engine.safe_output._exception import safe_error_type

# The record attribute that holds the traceback text this filter wrote.
_SAFE_EXC_TEXT = "_decoy_safe_exc_text"
# Bounds the cause/context walk; links past it are not printed.
_MAX_CHAIN = 16
_UNRENDERABLE = "log record could not be made safe"


class _Label(str):
    """A type label that prints the same under `%s` and `%r`."""

    __slots__ = ()

    def __repr__(self) -> str:
        return str.__str__(self)


def _label(exc: BaseException) -> _Label:
    return _Label(safe_error_type(exc).value)


def _scan(value: object, depth: int) -> object:
    """`value` with exceptions swapped for labels, `depth` container levels down.

    Returns `value` itself when nothing in it changes, so a mapping with its own lookup
    behavior (a `Counter`, a `defaultdict`) is never swapped for a plain copy needlessly.
    """
    if isinstance(value, BaseException):
        return _label(value)
    if depth == 0:
        return value
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        new = [_scan(v, depth - 1) for v in items]
        if all(n is o for n, o in zip(new, items, strict=True)):
            return value
        if isinstance(value, list):
            return new
        if isinstance(value, tuple):
            return tuple(new)
        return set(new) if isinstance(value, set) else frozenset(new)
    if isinstance(value, Mapping):
        pairs = [(k, v, _scan(k, depth - 1), _scan(v, depth - 1)) for k, v in value.items()]
        if all(nk is k and nv is v for k, v, nk, nv in pairs):
            return value
        return _rebuild_mapping(value, [(nk, nv) for _, _, nk, nv in pairs])
    return value


def _rebuild_mapping(
    original: Mapping[object, object], pairs: list[tuple[object, object]]
) -> object:
    """A mapping of the same type as `original` (keeping `__missing__`) holding `pairs`."""
    try:
        clone = copy.copy(original)
        clone.clear()  # type: ignore[attr-defined]
        clone.update(pairs)  # type: ignore[attr-defined]
        return clone
    except Exception:
        return dict(pairs)


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
    args = record.args
    if isinstance(args, tuple):
        record.args = tuple(_scan(a, 1) for a in args)
    elif isinstance(args, Mapping):
        record.args = _scan(
            args, 2
        )  # the mapping itself is the argument list  # type: ignore[assignment]

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
