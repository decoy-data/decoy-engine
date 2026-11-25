"""Shared helpers for the `SafeRecordFilter` tests (F31 AE3). It keeps exception text out of every engine log handler.

Plan: docs/plans/2026-11-24-f31-audit.md, Behavior 4 and acceptance test 2. The canary is built
at run time in most cells, so a stock traceback's source lines cannot carry it by accident; the
one cell that writes it as a literal checks that the filter prints no source lines either.
"""

from __future__ import annotations

import gc
import io
import itertools
import logging
import pathlib
import sys
import types

import pytest

from decoy_engine.internal import logging as engine_logging
from decoy_engine.internal.logging import _new_engine_handler

_CANARY = "".join(("DECOY_CANARY", "_F31_7Q4Z"))
_FMT = logging.Formatter("%(levelname)s %(message)s")


def _engine_handler() -> tuple[logging.Handler, io.StringIO]:
    buf = io.StringIO()
    return _new_engine_handler(lambda: logging.StreamHandler(buf), _FMT), buf


def _host_handler() -> tuple[logging.Handler, io.StringIO]:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(_FMT)
    return handler, buf


def _raise_canary() -> None:
    secret = f"bad cell {_CANARY}"
    raise ValueError(secret)


def _record(
    msg: object = "step failed", args: object = (), *, exc: bool = True
) -> logging.LogRecord:
    exc_info = None
    if exc:
        try:
            _raise_canary()
        except ValueError:
            exc_info = sys.exc_info()
    return logging.LogRecord(
        "decoy_engine",
        logging.ERROR,
        __file__,
        1,
        msg,
        args,  # type: ignore[arg-type]
        exc_info,
    )


def _caught_record(exc_type: type[BaseException], make) -> logging.LogRecord:  # type: ignore[no-untyped-def]
    try:
        make()
    except exc_type:
        return logging.LogRecord(
            "decoy_engine", logging.ERROR, __file__, 1, "x", (), sys.exc_info()
        )
    raise AssertionError("no exception raised")


def _reachable(root: object) -> list[object]:
    """Objects reachable from `root` by reference, not entering types, modules or code."""
    stop = (type, types.ModuleType, types.FunctionType, types.CodeType, types.BuiltinFunctionType)
    seen: dict[int, object] = {}
    todo = [root]
    while todo:
        obj = todo.pop()
        if id(obj) in seen or isinstance(obj, stop):
            continue
        seen[id(obj)] = obj
        todo.extend(gc.get_referents(obj))
    return list(seen.values())


_FILE_COUNTER = itertools.count()


def _ret(value: object) -> object:
    return value


def _message_only(path: pathlib.Path) -> tuple[logging.Handler, logging.Handler, io.StringIO]:
    """An engine stream handler and an engine file handler, both printing only the message."""
    fmt = logging.Formatter("%(message)s")
    buf = io.StringIO()
    stream = _new_engine_handler(lambda: logging.StreamHandler(buf), fmt)
    file = _new_engine_handler(lambda: logging.FileHandler(path, encoding="utf-8"), fmt)
    return stream, file, buf


def _lone(msg: object, mapping: object) -> logging.LogRecord:
    """A record whose only argument is `mapping`; `LogRecord` makes `args` the mapping itself."""
    return _record(msg, (mapping,), exc=False)


def _both(record: logging.LogRecord, tmp_path: pathlib.Path) -> tuple[str, str]:
    path = tmp_path / f"out{next(_FILE_COUNTER)}.log"
    stream, file, buf = _message_only(path)
    stream.handle(record)
    file.handle(record)
    file.flush()
    file.close()
    return buf.getvalue(), path.read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def fresh_engine_logger():  # type: ignore[no-untyped-def]
    logger = logging.getLogger("decoy_engine")
    handlers, level, instance = list(logger.handlers), logger.level, engine_logging._LOGGER_INSTANCE
    logger.handlers = [h for h in handlers if isinstance(h, logging.NullHandler)]
    yield
    logger.handlers = handlers
    logger.setLevel(level)
    engine_logging._LOGGER_INSTANCE = instance
