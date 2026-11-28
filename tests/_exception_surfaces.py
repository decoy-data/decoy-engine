"""Every text form of one exception, in one place (F31 AE6).

`rendered_surfaces(exc)` is the single choke point for "what can a reader see of this error".
It covers the exception's `str`, `repr` and `args`, the formatted traceback, and, for every
exception in the cause and context chain, its message, `repr(vars(e))` (the instance
attributes, where a value hides when a constructor stores it) and its `records`. A log record
rendered with `exc_info` joins the set, and so does anything pytest's `caplog` captured.

The helpers here carry no data or config values. Surface names are fixed strings.
"""

from __future__ import annotations

import logging
import traceback
import uuid

import pytest


def exception_chain(exc: BaseException) -> list[BaseException]:
    """`exc` and everything reachable through `__cause__` and `__context__`, each once."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending:
        link = pending.pop(0)
        if id(link) in seen:
            continue
        seen.add(id(link))
        chain.append(link)
        pending.extend(x for x in (link.__cause__, link.__context__) if x is not None)
    return chain


def _logged(exc: BaseException) -> str:
    """The text a stock formatter writes for `log.error(..., exc_info=exc)`."""
    log = logging.getLogger(f"surfaces.{uuid.uuid4().hex}")
    lines: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(logging.Formatter().format(record))

    log.addHandler(Capture())
    log.propagate = False
    log.error("failed", exc_info=exc)
    return "\n".join(lines)


def rendered_surfaces(
    exc: BaseException, caplog: pytest.LogCaptureFixture | None = None
) -> dict[str, str]:
    """Every surface of `exc`, by name, so a failure can say which one carried the value."""
    chain = exception_chain(exc)
    surfaces = {
        "exc.str": str(exc),
        "exc.repr": repr(exc),
        "exc.args": repr(exc.args),
        "exc.traceback": "".join(traceback.format_exception(exc)),
        "exc.chain": "\n".join(f"{type(e).__name__}: {e!s} | {e!r}" for e in chain),
        "exc.attrs": "\n".join(repr(vars(e)) for e in chain),
        "exc.records": "\n".join(repr(getattr(e, "records", None)) for e in chain),
        "exc.logged": _logged(exc),
    }
    if caplog is not None:
        formatter = logging.Formatter()
        surfaces["caplog"] = "\n".join(formatter.format(r) for r in caplog.records)
    return surfaces


def rendered(exc: BaseException, caplog: pytest.LogCaptureFixture | None = None) -> list[str]:
    """`rendered_surfaces` as a list of texts, for callers that check every text the same way."""
    return list(rendered_surfaces(exc, caplog).values())
