"""The log-record filter: exception text never reaches a handler's formatter.

Pattern source: the stdlib logging cookbook ("Using Filters to impart contextual information")
and the OWASP Logging Cheat Sheet, which says to sanitize at the logging layer rather than at
each call. A `logging.Filter` on a handler runs before that handler's formatter, so it sees the
record while it can still change what is printed.

What the filter rewrites, in place on the record:

- an exception in `msg` or in `args` (a tuple item or a mapping value) becomes its closed type
  label (`safe_error_type`), so `%s` and `%r` print the label;
- live `exc_info` becomes a traceback of labels and `file:line, in function` frames, with no
  exception text, no source lines and no frame locals; `exc_info` is then cleared so the
  formatter cannot render the raw one;
- a cached `exc_text` with no live traceback is dropped unless this filter wrote it, so text a
  host formatter cached earlier never passes, while a second filtered handler prints the same
  safe traceback as the first.

`stack_info` holds only code locations and is kept. Text already formatted into `msg` (an
f-string, or `str(exc)` passed as an argument) cannot be told apart from any other text here;
`tests/sentry/test_log_interpolation.py` guards those call sites instead.
"""

from __future__ import annotations

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


def _safe(value: object) -> object:
    return _label(value) if isinstance(value, BaseException) else value


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
    record.msg = _safe(record.msg)
    args = record.args
    if isinstance(args, tuple):
        record.args = tuple(_safe(a) for a in args)
    elif isinstance(args, Mapping):
        record.args = {k: _safe(v) for k, v in args.items()}

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
