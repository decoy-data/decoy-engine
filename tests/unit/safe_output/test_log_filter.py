"""F31 AE3: `SafeRecordFilter` keeps exception text out of every engine log handler.

Plan: docs/plans/2026-11-24-f31-audit.md, Behavior 4 and acceptance test 2. The canary is built
at run time in most cells, so a stock traceback's source lines cannot carry it by accident; the
one cell that writes it as a literal checks that the filter prints no source lines either.
"""

from __future__ import annotations

import io
import logging
import sys

import pytest

from decoy_engine.internal import logging as engine_logging
from decoy_engine.internal.logging import _configure_logger, _new_engine_handler
from decoy_engine.safe_output import SafeRecordFilter

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


@pytest.fixture(autouse=True)
def _fresh_engine_logger():  # type: ignore[no-untyped-def]
    logger = logging.getLogger("decoy_engine")
    handlers, level, instance = list(logger.handlers), logger.level, engine_logging._LOGGER_INSTANCE
    logger.handlers = [h for h in handlers if isinstance(h, logging.NullHandler)]
    yield
    logger.handlers = handlers
    logger.setLevel(level)
    engine_logging._LOGGER_INSTANCE = instance


def test_host_cache_is_replaced_by_the_engine_handler() -> None:
    host, host_buf = _host_handler()
    engine, engine_buf = _engine_handler()
    record = _record()
    host.handle(record)
    # Positive control: the unfiltered host formatter cached the raw traceback text.
    assert _CANARY in (record.exc_text or "")
    assert _CANARY in host_buf.getvalue()
    engine.handle(record)
    out = engine_buf.getvalue()
    assert "ValueError" in out
    assert "_raise_canary" in out
    assert _CANARY not in out


def test_cache_only_record_is_discarded() -> None:
    host, _ = _host_handler()
    engine, engine_buf = _engine_handler()
    record = _record()
    host.handle(record)
    record.exc_info = None
    engine.handle(record)
    assert "step failed" in engine_buf.getvalue()
    assert _CANARY not in engine_buf.getvalue()


def test_two_filtered_handlers_print_the_same_safe_frames() -> None:
    console, console_buf = _engine_handler()
    file_like, file_buf = _engine_handler()
    record = _record()
    console.handle(record)
    file_like.handle(record)
    first, second = console_buf.getvalue(), file_buf.getvalue()
    assert first == second
    assert "ValueError" in first
    assert f'{__file__}", line' in first
    assert _CANARY not in first


def _raise_literal() -> None:
    raise RuntimeError("DECOY_CANARY_F31_7Q4Z")


def test_literal_canary_in_source_line_is_not_printed() -> None:
    engine, buf = _engine_handler()
    engine.handle(_caught_record(RuntimeError, _raise_literal))
    assert "RuntimeError" in buf.getvalue()
    assert _CANARY not in buf.getvalue()


def _raise_chained() -> None:
    try:
        _raise_canary()
    except ValueError as inner:
        raise KeyError(_CANARY) from inner


def test_chained_cause_prints_labels_only() -> None:
    engine, buf = _engine_handler()
    engine.handle(_caught_record(KeyError, _raise_chained))
    out = buf.getvalue()
    assert "ValueError" in out
    assert "KeyError" in out
    assert _CANARY not in out


@pytest.mark.parametrize("fmt", ["x %r", "x %s"])
def test_exception_arg_becomes_its_label(fmt: str) -> None:
    engine, buf = _engine_handler()
    engine.handle(_record(fmt, (ValueError(_CANARY),), exc=False))
    assert buf.getvalue().strip() == "ERROR x ValueError"


def test_mapping_arg_and_exception_msg_become_labels() -> None:
    engine, buf = _engine_handler()
    record = _record("x %(e)s", (), exc=False)
    record.args = {"e": OSError(_CANARY)}
    engine.handle(record)
    engine.handle(_record(KeyError(_CANARY), (), exc=False))
    out = buf.getvalue()
    assert "x OSError" in out
    assert "KeyError" in out
    assert _CANARY not in out


def test_unlisted_exception_class_is_labelled_exception() -> None:
    engine, buf = _engine_handler()
    hostile = type("CanaryNamed_" + _CANARY, (Exception,), {})
    engine.handle(_record("x %s", (hostile(_CANARY),), exc=False))
    assert buf.getvalue().strip() == "ERROR x Exception"


def test_stack_info_is_kept() -> None:
    engine, buf = _engine_handler()
    record = _record(exc=False)
    record.stack_info = 'Stack (most recent call last):\n  File "m.py", line 3, in f'
    engine.handle(record)
    assert 'File "m.py", line 3, in f' in buf.getvalue()


class _ExplodingArgs(dict):  # type: ignore[type-arg]
    def items(self):  # type: ignore[no-untyped-def,override]
        raise RuntimeError(_CANARY)

    def values(self):  # type: ignore[no-untyped-def,override]
        raise RuntimeError(_CANARY)


def test_filter_never_raises() -> None:
    record = _record("x %(e)s", (), exc=False)
    record.args = _ExplodingArgs(e=ValueError(_CANARY))
    assert SafeRecordFilter().filter(record) is True
    assert _CANARY not in _FMT.format(record)


def test_every_engine_handler_carries_the_filter() -> None:
    logger = logging.getLogger("decoy_engine")
    _configure_logger(logger, {"console": True})
    owned = [h for h in logger.handlers if getattr(h, engine_logging._OWNED_ATTR, False)]
    assert owned
    for handler in owned:
        assert any(isinstance(f, SafeRecordFilter) for f in handler.filters)


def test_configured_engine_logger_drops_exception_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logger = logging.getLogger("decoy_engine")
    _configure_logger(logger, {"console": True})
    try:
        _raise_canary()
    except ValueError as exc:
        logger.exception("step failed: %s", exc)
    err = capsys.readouterr().err
    assert "step failed: ValueError" in err
    assert _CANARY not in err


@pytest.mark.xfail(strict=True, reason="guarded by test_log_interpolation")
@pytest.mark.parametrize("shape", ["fstring", "str_arg"])
def test_documented_gap_preformatted_text(shape: str) -> None:
    engine, buf = _engine_handler()
    exc = ValueError(_CANARY)
    if shape == "fstring":
        record = _record(f"x {exc}", (), exc=False)
    else:
        record = _record("%s", (str(exc),), exc=False)
    engine.handle(record)
    assert _CANARY not in buf.getvalue()
