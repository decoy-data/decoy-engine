"""F31 AE3: `SafeRecordFilter` keeps exception text out of every engine log handler.

Plan: docs/plans/2026-11-24-f31-audit.md, Behavior 4 and acceptance test 2, as amended by
docs/plans/2026-11-25-f31-ae3-plan-amendment.md. The canary is built
at run time in most cells, so a stock traceback's source lines cannot carry it by accident; the
one cell that writes it as a literal checks that the filter prints no source lines either.
"""

from __future__ import annotations

import collections
import collections.abc
import dataclasses
import io
import json
import logging
import pathlib
import types

import pytest

from decoy_engine.internal import logging as engine_logging
from decoy_engine.internal.logging import _configure_logger, _new_engine_handler
from decoy_engine.safe_output import SafeRecordFilter, _log_filter
from tests.unit.safe_output import log_filter_support
from tests.unit.safe_output.log_filter_support import (  # noqa: F401
    _CANARY,
    _FMT,
    _both,
    _caught_record,
    _engine_handler,
    _host_handler,
    _lone,
    _message_only,
    _raise_canary,
    _reachable,
    _record,
    _ret,
    fresh_engine_logger,
)


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
    assert f'{log_filter_support.__file__}", line' in first
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
    # stack_info shows engine source lines: code text, not runtime data, so it is kept.
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


def test_filter_clears_exc_info() -> None:
    record = _record()
    assert record.exc_info is not None
    SafeRecordFilter().filter(record)
    assert record.exc_info is None


class _RawExcInfoFormatter(logging.Formatter):
    """Renders `record.exc_info` itself, like python-json-logger does."""

    def format(self, record: logging.LogRecord) -> str:
        info = record.exc_info
        return f"{record.getMessage()} | {info[1] if info else ''}"


def test_later_handler_rendering_exc_info_sees_no_canary() -> None:
    engine, _ = _engine_handler()
    buf = io.StringIO()
    later = logging.StreamHandler(buf)
    later.setFormatter(_RawExcInfoFormatter())
    record = _record()
    # Positive control: the raw formatter prints the canary from an unfiltered record.
    assert _CANARY in _RawExcInfoFormatter().format(_record())
    engine.handle(record)
    later.handle(record)
    assert buf.getvalue()
    assert _CANARY not in buf.getvalue()


def test_fallback_clears_live_exc_info(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(value: object, depth: int) -> object:
        raise RuntimeError(_CANARY)

    # The scan runs no caller code, so a hostile argument no longer reaches the fallback.
    monkeypatch.setattr(_log_filter, "_safe_value", _boom)
    record = _record("x %(e)s", (), exc=True)
    record.args = {"e": ValueError(_CANARY)}
    assert record.exc_info is not None
    assert SafeRecordFilter().filter(record) is True
    assert record.exc_info is None
    assert record.exc_text is None
    assert _CANARY not in _FMT.format(record)
    assert _CANARY not in _RawExcInfoFormatter().format(record)


def _nested_arg(shape: str) -> object:
    exc = ValueError(_CANARY)
    return {
        "list": [exc],
        "tuple": (exc,),
        "set": {exc},
        "frozenset": frozenset({exc}),
        "dict_value": {"k": exc},
        "dict_key": {exc: "v"},
    }[shape]


@pytest.mark.parametrize("shape", ["list", "tuple", "set", "frozenset", "dict_value", "dict_key"])
def test_exception_inside_container_arg_becomes_label(shape: str) -> None:
    engine, buf = _engine_handler()
    engine.handle(_record("x %s", (_nested_arg(shape),), exc=False))
    out = buf.getvalue()
    # A dict with an exception key is the placeholder (row 7); keys are never rewritten.
    assert ("<mapping>" if shape == "dict_key" else "ValueError") in out
    assert _CANARY not in out


@pytest.mark.parametrize("shape", ["list", "tuple", "dict_value", "dict_key"])
def test_exception_inside_mapping_arg_container_becomes_label(shape: str) -> None:
    engine, buf = _engine_handler()
    record = _record("x %(c)s", (), exc=False)
    record.args = {"c": _nested_arg(shape)}
    engine.handle(record)
    if shape == "dict_key":
        assert buf.getvalue().strip() == "ERROR x <mapping>"
    assert ("<mapping>" if shape == "dict_key" else "ValueError") in buf.getvalue()
    assert _CANARY not in buf.getvalue()


def test_nested_tuple_in_args_becomes_label() -> None:
    engine, buf = _engine_handler()
    engine.handle(_record("x %s %s", ((ValueError(_CANARY),), "y"), exc=False))
    assert _CANARY not in buf.getvalue()
    assert "ValueError" in buf.getvalue()


def test_dict_msg_with_exception_becomes_label() -> None:
    engine, buf = _engine_handler()
    engine.handle(_record({"err": ValueError(_CANARY)}, (), exc=False))
    assert "ValueError" in buf.getvalue()
    assert _CANARY not in buf.getvalue()


def test_tuple_key_in_lone_mapping_arg_is_the_placeholder(isolated_logger) -> None:  # type: ignore[no-untyped-def]
    engine, buf = _engine_handler()
    logger = isolated_logger("f31_ae3_t_key", engine)
    logger.error("failed: %s", {(ValueError(_CANARY),): 1})
    assert buf.getvalue().strip() == "ERROR failed: <mapping>"
    assert _CANARY not in buf.getvalue()


def test_non_dict_mapping_msg_and_arg_are_the_placeholder() -> None:
    engine, buf = _engine_handler()
    engine.handle(_record(collections.UserDict({"e": ValueError(_CANARY)}), (), exc=False))
    engine.handle(_record("x %s", (collections.UserDict({"e": ValueError(_CANARY)}),), exc=False))
    assert buf.getvalue().count("<mapping>") == 2
    assert _CANARY not in buf.getvalue()


def test_valid_record_is_not_dropped_by_the_filter(isolated_logger) -> None:  # type: ignore[no-untyped-def]
    engine, buf = _engine_handler()
    logger = isolated_logger("f31_ae3_t_counter", engine, logging.INFO)
    counter = collections.Counter(existing=2)
    logger.info("found %(missing)d", counter)
    assert buf.getvalue().strip() == "INFO found 0"


def test_mapping_needing_replacement_keeps_missing_lookup(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, isolated_logger
) -> None:  # type: ignore[no-untyped-def]
    engine, buf = _engine_handler()
    errors: list[logging.LogRecord] = []
    monkeypatch.setattr(engine, "handleError", errors.append)
    mapping: collections.defaultdict[str, object] = collections.defaultdict(
        lambda: 0, e=ValueError(_CANARY)
    )
    logger = isolated_logger("f31_ae3_t_missing", engine)
    # The caller factory is not called: a missing name is the placeholder.
    logger.warning("%(e)s %(missing)s", mapping)
    assert buf.getvalue().strip() == "WARNING ValueError <mapping>"
    # `%(missing)d` on the placeholder is a stock logging error: the handler reports it once.
    assert errors == []
    logger.warning("%(e)s %(missing)d", mapping)
    assert len(errors) == 1
    assert buf.getvalue().strip() == "WARNING ValueError <mapping>"
    assert _CANARY not in capsys.readouterr().err


def test_unchanged_mapping_arg_renders_the_same() -> None:
    engine, buf = _engine_handler()
    record = _record("found %(missing)d %(existing)d", (), exc=False)
    record.args = collections.Counter(existing=2)
    engine.handle(record)
    assert buf.getvalue().strip() == "ERROR found 0 2"


def test_every_engine_handler_carries_the_filter(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = logging.getLogger("decoy_engine")
    # Console, file and the file-open fallback console: every route the logger can build.
    log_file = tmp_path / "engine.log"
    monkeypatch.setattr(
        engine_logging,
        "_ambient_policy",
        lambda: types.SimpleNamespace(
            log_handler=lambda *a: logging.FileHandler(a[0], encoding="utf-8")
        ),
    )
    _configure_logger(logger, {"console": True, "file": str(log_file)})
    owned = [h for h in logger.handlers if getattr(h, engine_logging._OWNED_ATTR, False)]
    assert any(isinstance(h, logging.FileHandler) for h in owned)
    assert any(not isinstance(h, logging.FileHandler) for h in owned)

    # The fallback: the file opener fails, so a console handler is added in its place.
    def _fail(*_a: object) -> logging.Handler:
        raise OSError("read-only")

    monkeypatch.setattr(
        engine_logging, "_ambient_policy", lambda: types.SimpleNamespace(log_handler=_fail)
    )
    _configure_logger(logger, {"file": str(log_file)})
    owned += [h for h in logger.handlers if getattr(h, engine_logging._OWNED_ATTR, False)]
    assert len(owned) >= 3
    for handler in logger.handlers:
        if isinstance(handler, logging.NullHandler):
            continue
        assert any(isinstance(f, SafeRecordFilter) for f in handler.filters)
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


@pytest.mark.xfail(strict=True, reason="named in the module gap list; call sites are guarded")
@pytest.mark.parametrize("shape", ["exc_args"])
def test_documented_gap_uncatchable_shapes(shape: str) -> None:
    engine, buf = _engine_handler()
    exc = ValueError(_CANARY)
    arg: object
    if shape == "exc_args":
        arg = exc.args
    engine.handle(_record("x %s", (arg,), exc=False))
    assert _CANARY not in buf.getvalue()


class _ExtraFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return (
            f"{record.getMessage()} | {record.__dict__.get('err')} | {record.__dict__.get('rows')}"
        )


def test_extra_attributes_are_scanned(isolated_logger) -> None:  # type: ignore[no-untyped-def]
    buf = io.StringIO()
    handler = _new_engine_handler(lambda: logging.StreamHandler(buf), _ExtraFormatter())
    logger = isolated_logger("f31_ae3_t_extra", handler, logging.INFO)
    exc = ValueError(_CANARY)
    logger.info("x", extra={"err": exc, "rows": [collections.UserDict(a=exc), 1]})
    assert buf.getvalue().strip() == "x | ValueError | [<mapping>, 1]"
    assert _CANARY not in buf.getvalue()


def test_standard_record_fields_are_not_rewritten() -> None:
    record = _record("x", (), exc=False)
    before = {k: v for k, v in vars(record).items() if k not in ("msg", "args", "exc_info")}
    SafeRecordFilter().filter(record)
    after = {k: v for k, v in vars(record).items() if k not in ("msg", "args", "exc_info")}
    assert after == before | {k: v for k, v in after.items() if k.startswith("_decoy")}


def test_failed_scrub_blanks_every_extra_attribute(
    monkeypatch: pytest.MonkeyPatch,
    isolated_logger,  # type: ignore[no-untyped-def]
) -> None:
    real = _log_filter._safe_value

    def flaky(value: object, depth: int) -> object:
        if isinstance(value, ValueError):
            raise RuntimeError(_CANARY)
        return real(value, depth)

    monkeypatch.setattr(_log_filter, "_safe_value", flaky)
    buf = io.StringIO()
    handler = _new_engine_handler(lambda: logging.StreamHandler(buf), _ExtraFormatter())
    logger = isolated_logger("f31_ae3_t_extra_fail", handler, logging.INFO)
    logger.info("x", extra={"err": ValueError(_CANARY), "rows": ["ok"]})
    assert _CANARY not in buf.getvalue()
    unrenderable = _log_filter._UNRENDERABLE
    assert buf.getvalue().strip() == f"{unrenderable} | {unrenderable} | {unrenderable}"


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _capturing_logger(isolated_logger, name: str):  # type: ignore[no-untyped-def]
    handler = _new_engine_handler(_Capture, logging.Formatter("%(message)s"))
    return isolated_logger(name, handler, logging.INFO), handler


def test_numeric_extra_key_is_scanned(isolated_logger) -> None:  # type: ignore[no-untyped-def]
    logger, handler = _capturing_logger(isolated_logger, "f31_ae3_t_numkey")
    logger.info("x", extra={7: ValueError(_CANARY)})
    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.msg == "x"
    assert record.__dict__[7] == "ValueError"
    assert _CANARY not in repr(vars(record))


def test_numeric_extra_key_is_blanked_when_the_scrub_fails(
    monkeypatch: pytest.MonkeyPatch,
    isolated_logger,  # type: ignore[no-untyped-def]
) -> None:
    def broken(value: object, depth: int) -> object:
        raise RuntimeError(_CANARY)

    monkeypatch.setattr(_log_filter, "_safe_value", broken)
    logger, handler = _capturing_logger(isolated_logger, "f31_ae3_t_numkey_fail")
    logger.info("x", extra={7: ValueError(_CANARY)})
    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.msg == _log_filter._UNRENDERABLE
    assert record.__dict__[7] == _log_filter._UNRENDERABLE
    assert _CANARY not in repr(vars(record))


class _JsonFormatter(logging.Formatter):
    """The shape of common JSON log formatters: it dumps the record's own attributes."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(record.__dict__, default=str)


def _json_handlers() -> list[tuple[str, logging.Handler, io.StringIO]]:
    engine_buf, host_buf = io.StringIO(), io.StringIO()
    engine = _new_engine_handler(lambda: logging.StreamHandler(engine_buf), _JsonFormatter())
    host = logging.StreamHandler(host_buf)
    host.setFormatter(_JsonFormatter())
    host.addFilter(SafeRecordFilter())
    return [("engine", engine, engine_buf), ("host", host, host_buf)]


@pytest.mark.parametrize("which", [0, 1], ids=["engine", "host"])
def test_json_formatter_prints_no_extra_exception_text(which: int) -> None:
    _, handler, buf = _json_handlers()[which]
    exc = ValueError(_CANARY)
    extra = {"err": exc, "ctx": _Holder(exc), "rows": [exc]}
    record = logging.getLogger("f31_ae3_t_json").makeRecord(
        "f31_ae3_t_json", logging.INFO, __file__, 1, "x", (), None, extra=extra
    )
    handler.handle(record)
    assert _CANARY not in buf.getvalue()
    parsed = json.loads(buf.getvalue())
    assert (parsed["err"], parsed["ctx"], parsed["rows"]) == (
        "ValueError",
        "<object>",
        ["ValueError"],
    )


@dataclasses.dataclass
class _Holder:
    error: object


@pytest.mark.parametrize("path", ["success", "fallback"])
@pytest.mark.parametrize("which", [0, 1], ids=["engine", "host"])
def test_cached_message_is_dropped_before_a_json_formatter(
    path: str, which: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, handler, buf = _json_handlers()[which]
    record = _record("failed: %s", (ValueError(_CANARY),), exc=False)
    logging.Formatter().format(record)
    # Positive control: an earlier stock formatter cached the exception text.
    assert _CANARY in record.message  # type: ignore[attr-defined]
    if path == "fallback":

        def broken(value: object, depth: int) -> object:
            raise RuntimeError(_CANARY)

        monkeypatch.setattr(_log_filter, "_safe_value", broken)
    handler.handle(record)
    parsed = json.loads(buf.getvalue())
    assert _CANARY not in buf.getvalue()
    assert "message" not in parsed
