"""F31 AE3: `SafeRecordFilter` keeps exception text out of every engine log handler.

Plan: docs/plans/2026-11-24-f31-audit.md, Behavior 4 and acceptance test 2. The canary is built
at run time in most cells, so a stock traceback's source lines cannot carry it by accident; the
one cell that writes it as a literal checks that the filter prints no source lines either.
"""

from __future__ import annotations

import ast
import collections
import collections.abc
import configparser
import functools
import gc
import io
import itertools
import logging
import pathlib
import sys
import types

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from decoy_engine.internal import logging as engine_logging
from decoy_engine.internal.logging import _configure_logger, _new_engine_handler
from decoy_engine.safe_output import SafeRecordFilter, _log_filter

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


def test_tuple_key_in_lone_mapping_arg_is_the_placeholder() -> None:
    engine, buf = _engine_handler()
    logger = logging.getLogger("f31_ae3_t_key")
    logger.propagate = False
    logger.handlers = [engine]
    logger.error("failed: %s", {(ValueError(_CANARY),): 1})
    assert buf.getvalue().strip() == "ERROR failed: <mapping>"
    assert _CANARY not in buf.getvalue()


def test_non_dict_mapping_msg_and_arg_are_the_placeholder() -> None:
    engine, buf = _engine_handler()
    engine.handle(_record(collections.UserDict({"e": ValueError(_CANARY)}), (), exc=False))
    engine.handle(_record("x %s", (collections.UserDict({"e": ValueError(_CANARY)}),), exc=False))
    assert buf.getvalue().count("<mapping>") == 2
    assert _CANARY not in buf.getvalue()


def test_valid_record_is_not_dropped_by_the_filter() -> None:
    engine, buf = _engine_handler()
    logger = logging.getLogger("f31_ae3_t_counter")
    logger.propagate = False
    logger.handlers = [engine]
    logger.setLevel(logging.INFO)
    counter = collections.Counter(existing=2)
    logger.info("found %(missing)d", counter)
    assert buf.getvalue().strip() == "INFO found 0"


def test_mapping_needing_replacement_keeps_missing_lookup(
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine, buf = _engine_handler()
    mapping: collections.defaultdict[str, object] = collections.defaultdict(
        lambda: 0, e=ValueError(_CANARY)
    )
    logger = logging.getLogger("f31_ae3_t_missing")
    logger.propagate = False
    logger.handlers = [engine]
    # The caller factory is not called: a missing name is the placeholder.
    logger.warning("%(e)s %(missing)s", mapping)
    assert buf.getvalue().strip() == "WARNING ValueError <mapping>"
    # `%(missing)d` on the placeholder is a stock logging error: no line, no canary.
    logger.warning("%(e)s %(missing)d", mapping)
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


class _Wrapper:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def __str__(self) -> str:
        return str(self._exc)


@pytest.mark.xfail(strict=True, reason="named in the module gap list; call sites are guarded")
@pytest.mark.parametrize("shape", ["exc_args", "wrapper_str", "too_deep"])
def test_documented_gap_uncatchable_shapes(shape: str) -> None:
    engine, buf = _engine_handler()
    exc = ValueError(_CANARY)
    arg: object
    if shape == "exc_args":
        arg = exc.args
    elif shape == "wrapper_str":
        arg = _Wrapper(exc)
    else:
        arg = [[exc]]
    engine.handle(_record("x %s", (arg,), exc=False))
    assert _CANARY not in buf.getvalue()


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


def _partial_defaultdict() -> collections.defaultdict[str, object]:
    factory = functools.partial(_ret, ValueError(_CANARY))
    return collections.defaultdict(factory, {"a": 1})


def test_partial_factory_exception_is_unreachable(tmp_path: pathlib.Path) -> None:
    # Positional through both handlers, and the lone mapping with a nonempty store.
    for fmt in ("%s 1", "%r 1"):
        out = _both(
            _record(fmt.replace(" 1", " %s"), (_partial_defaultdict(), 1), exc=False), tmp_path
        )
        assert out == ("<mapping> 1\n", "<mapping> 1\n")
    for fmt in ("%s", "%r", "%(missing)s"):
        out = _both(_lone(fmt, _partial_defaultdict()), tmp_path)
        assert out == ("<mapping>\n", "<mapping>\n")
    for record in (
        _record("%s %s", (_partial_defaultdict(), 1), exc=False),
        _lone("%s", _partial_defaultdict()),
    ):
        SafeRecordFilter().filter(record)
        reached = _reachable(record.args) + _reachable(record.msg)
        assert not any(isinstance(o, (BaseException, functools.partial)) for o in reached)


def test_partial_factory_brace_field_reaches_nothing() -> None:
    # A fresh record and one filter pass: a second pass would hide the first-pass leak.
    record = _record("%s %s", (_partial_defaultdict(), 1), exc=False)
    SafeRecordFilter().filter(record)
    brace = logging.Formatter("{args[0].default_factory._factory.args[0]}", style="{")
    with pytest.raises(AttributeError):
        brace.format(record)


def test_exception_key_does_not_overwrite_a_named_key(tmp_path: pathlib.Path) -> None:
    mapping = {"ValueError": 7, ValueError(_CANARY): 11}
    assert _both(_lone("%(ValueError)d", mapping), tmp_path) == ("7\n", "7\n")


def test_ordereddict_arg_is_the_placeholder(tmp_path: pathlib.Path) -> None:
    od: collections.OrderedDict[str, object] = collections.OrderedDict(
        one=ValueError(_CANARY), two=2
    )
    od.move_to_end("one")
    order = list(od)
    assert _both(_record("%s %s", (od, 1), exc=False), tmp_path) == ("<mapping> 1\n",) * 2
    assert list(od) == order
    lone = collections.OrderedDict(one=1, two=2)
    assert _both(_lone("%(one)s %(two)s", lone), tmp_path) == ("1 2\n", "1 2\n")


def test_mappingproxy_is_the_placeholder(tmp_path: pathlib.Path) -> None:
    proxy = types.MappingProxyType({"e": ValueError(_CANARY)})
    assert _both(_record("x %s", (proxy,), exc=False), tmp_path) == ("x <mapping>\n",) * 2


def test_named_lookup_never_mutates_a_clean_caller_mapping() -> None:
    engine, buf = _engine_handler()
    mapping: collections.defaultdict[str, int] = collections.defaultdict(int, a=1)
    engine.handle(_lone("%(missing)d", mapping))
    assert buf.getvalue().strip() == "ERROR 0"
    assert "missing" not in mapping


def test_brace_formatter_cannot_reach_the_original_exception() -> None:
    exc = ValueError(_CANARY)
    record = _record("x %(err)s", (), exc=False)
    record.args = {"err": exc}
    SafeRecordFilter().filter(record)
    assert record.getMessage() == "x ValueError"
    assert not any(obj is exc for obj in _reachable(record.args))
    braced = logging.Formatter("{message} {args}", style="{")
    assert _CANARY not in braced.format(record)
    with pytest.raises(AttributeError):
        logging.Formatter("{args._original[err]}", style="{").format(record)


def test_fallback_lookup_result_is_not_enumerated(capsys: pytest.CaptureFixture[str]) -> None:
    parser = configparser.ConfigParser()
    parser.read_dict({"sec": {"opt": "%(absent)s " + _CANARY}})
    section = parser["sec"]
    engine, buf = _engine_handler()
    lone = _lone("%(x)s", collections.defaultdict(lambda: section, a=1))
    engine.handle(lone)
    engine.handle(_record("%s", (section,), exc=False))
    assert buf.getvalue().splitlines() == ["ERROR <mapping>", "ERROR <mapping>"]
    assert lone.getMessage() == "<mapping>"
    assert _CANARY not in capsys.readouterr().err


def test_plain_dict_passes_through_and_a_second_filter_is_a_no_op() -> None:
    mapping = {"a": 1}
    record = _record("%r", (mapping,), exc=False)
    SafeRecordFilter().filter(record)
    first, text = record.args, record.getMessage()
    assert text == repr({"a": 1})
    assert mapping == {"a": 1}
    SafeRecordFilter().filter(record)
    assert record.args is first
    assert record.getMessage() == text


@pytest.mark.parametrize(
    "mapping",
    [
        collections.Counter(a=3),
        collections.OrderedDict(a=1, b=2),
        collections.defaultdict(int, a=1),
        collections.UserDict(a=1),
    ],
    ids=["counter", "ordereddict", "defaultdict_int", "userdict"],
)
def test_clean_non_plain_mapping_is_the_placeholder(mapping: object) -> None:
    positional = _record("%s %d", (mapping, 1), exc=False)
    lone = _record("%r", (mapping,), exc=False)
    SafeRecordFilter().filter(positional)
    SafeRecordFilter().filter(lone)
    assert positional.getMessage() == "<mapping> 1"
    assert lone.getMessage() == "<mapping>"


def test_lookup_never_mutates_the_caller_mapping() -> None:
    mapping: collections.defaultdict[str, object] = collections.defaultdict(
        lambda: 0, e=ValueError(_CANARY)
    )
    record = _record("%(e)s %(missing)s", (), exc=False)
    record.args = mapping
    SafeRecordFilter().filter(record)
    assert record.getMessage() == "ValueError <mapping>"
    assert "missing" not in mapping
    assert isinstance(mapping["e"], ValueError)


def test_nested_non_plain_mapping_is_the_placeholder() -> None:
    record = _record("x", (), exc=False)
    nested: collections.defaultdict[str, object] = collections.defaultdict(
        lambda: ValueError(_CANARY), a=1
    )
    record.args = {"nested": nested}
    SafeRecordFilter().filter(record)
    assert logging.Formatter("{args[nested]}", style="{").format(record) == "<mapping>"
    with pytest.raises(TypeError):
        logging.Formatter("{args[nested][missing]}", style="{").format(record)
    assert not any(
        isinstance(o, (BaseException, collections.defaultdict)) for o in _reachable(record.args)
    )


# Test 15: no caller code runs.

_CALLS: list[str] = []


def _spy(name: str):  # type: ignore[no-untyped-def]
    def method(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        _CALLS.append(name)
        raise RuntimeError(_CANARY)

    return method


class _SpyDict(dict):  # type: ignore[type-arg]
    __getitem__ = _spy("getitem")
    __missing__ = _spy("missing")
    __iter__ = _spy("iter")
    items = _spy("items")
    keys = _spy("keys")
    __eq__ = _spy("eq")
    __hash__ = None  # type: ignore[assignment]


class _SpyUserDict(collections.UserDict):  # type: ignore[type-arg]
    __getitem__ = _spy("getitem")


class _SpyMapping(collections.abc.Mapping):  # type: ignore[type-arg]
    __getitem__ = _spy("getitem")
    __iter__ = _spy("iter")

    def __len__(self) -> int:
        return 1


class _SpyKey(str):
    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        _CALLS.append("key_eq")
        return str.__eq__(self, other)

    __hash__ = str.__hash__


class _SpyItem:
    def __eq__(self, other: object) -> bool:
        _CALLS.append("item_eq")
        return self is other

    __hash__ = object.__hash__

    def __repr__(self) -> str:
        return "item"


def _spy_default_dict() -> collections.defaultdict[str, object]:
    return collections.defaultdict(lambda: _CALLS.append("factory"), a=ValueError(_CANARY))


def _spy_mappings() -> dict[str, object]:
    return {
        "dict_sub": _SpyDict(a=1),
        "defaultdict": _spy_default_dict(),
        "userdict": _SpyUserDict(a=1),
        "abc_mapping": _SpyMapping(),
    }


@pytest.mark.parametrize("name", ["dict_sub", "defaultdict", "userdict", "abc_mapping"])
@pytest.mark.parametrize("fmt", ["%s", "%r", "%(a)s"])
@pytest.mark.parametrize("shape", ["positional", "lone"])
def test_no_caller_code_runs(name: str, fmt: str, shape: str) -> None:
    if shape == "positional" and fmt == "%(a)s":
        pytest.skip("a named field needs a mapping argument")
    mapping = _spy_mappings()[name]
    if shape == "positional":
        record = _record(fmt, (mapping, 1), exc=False)
        record.msg = fmt + " %s"
    else:
        record = _lone(fmt, mapping)
    _CALLS.clear()
    SafeRecordFilter().filter(record)
    text = record.getMessage()
    assert _CALLS == []
    assert _CANARY not in text


def test_str_subclass_key_is_never_compared_or_read() -> None:
    mapping = {_SpyKey("a"): 7, "b": ValueError(_CANARY)}
    record = _lone("%(a)s %(b)s", mapping)
    _CALLS.clear()
    SafeRecordFilter().filter(record)
    assert record.getMessage() == "<mapping> ValueError"
    assert _CALLS == []
    positional = _record("%s", ({_SpyKey("a"): 7},), exc=False)
    positional.args = ({_SpyKey("a"): 7},)
    SafeRecordFilter().filter(positional)
    assert positional.getMessage() == "<mapping>"
    assert _CALLS == []


def test_item_equality_is_never_called_on_a_caller_value() -> None:
    item = _SpyItem()
    record = _record(
        "%s %s", ([ValueError(_CANARY), item], {"k": ValueError(_CANARY), "i": item}), exc=False
    )
    _CALLS.clear()
    SafeRecordFilter().filter(record)
    assert record.getMessage() == "[ValueError, item] {'k': ValueError, 'i': item}"
    assert _CALLS == []


def test_dict_arg_keeps_identity_only_when_nothing_changes() -> None:
    clean = {"a": 7}
    record = _record("%s %d", (clean, 1), exc=False)
    SafeRecordFilter().filter(record)
    assert record.args[0] is clean  # type: ignore[index]
    dirty = {"a": ValueError(_CANARY)}
    record = _record("%s %d", (dirty, 1), exc=False)
    SafeRecordFilter().filter(record)
    assert record.args[0] is not dirty  # type: ignore[index]
    assert record.getMessage() == "{'a': ValueError} 1"
    assert isinstance(dirty["a"], ValueError)


# Test 16: any mapping type is value free.


class _DictSub(dict):  # type: ignore[type-arg]
    pass


class _CallerMapping(collections.abc.Mapping):  # type: ignore[type-arg]
    def __init__(self, data: dict[object, object]) -> None:
        self._data = data

    def __getitem__(self, key: object) -> object:
        return self._data[key]

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


_KINDS = [
    "exc",
    "dict_sub",
    "ordereddict",
    "counter",
    "dd_empty",
    "dd_caller",
    "userdict",
    "proxy",
    "chainmap",
    "section",
    "caller_mapping",
]


def _planted(kind: str, mode: str, exc: BaseException) -> object:
    if kind == "exc":
        return exc
    items: dict[object, object] = {exc: 1} if mode == "key" else {"k": exc}
    if kind == "dd_caller":
        factory = {
            "factory_arg": functools.partial(_ret, exc),
            "factory_result": lambda: exc,
        }.get(mode, lambda: 0)
        if mode.startswith("factory"):
            items = {"k": 1}
        return collections.defaultdict(factory, items)
    if kind == "section":
        parser = configparser.ConfigParser()
        parser.read_dict({"sec": {"opt": "%(absent)s " + _CANARY}})
        return parser["sec"]
    builders = {
        "dict_sub": _DictSub,
        "ordereddict": collections.OrderedDict,
        "counter": collections.Counter,
        "dd_empty": lambda d: collections.defaultdict(int, d),
        "userdict": collections.UserDict,
        "proxy": types.MappingProxyType,
        "chainmap": collections.ChainMap,
        "caller_mapping": _CallerMapping,
    }
    return builders[kind](items)


def _wrap(shape: str, inner: object) -> object:
    return {"bare": inner, "list": [inner], "tuple": (inner,), "dict": {"k": inner}}[shape]


@settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[__import__("hypothesis").HealthCheck.function_scoped_fixture],
)
@given(
    kind=st.sampled_from(_KINDS),
    mode=st.sampled_from(["key", "value", "factory_arg", "factory_result"]),
    wrap=st.sampled_from(["bare", "list", "tuple", "dict"]),
    where=st.sampled_from(["positional", "lone"]),
)
def test_any_mapping_type_is_value_free(kind: str, mode: str, wrap: str, where: str) -> None:
    exc = ValueError(_CANARY)
    arg = _wrap(wrap, _planted(kind, mode, exc))
    if where == "positional":
        records = [_record(fmt, (arg,), exc=False) for fmt in ("%s", "%r")]
        if not isinstance(arg, collections.abc.Mapping):
            pass
        else:
            records = [_record(fmt, (arg, 1), exc=False) for fmt in ("%s %s", "%r %s")]
    else:
        if not isinstance(arg, collections.abc.Mapping) or not arg:
            arg = {"k": arg}
        records = [_lone(fmt, arg) for fmt in ("%s", "%r", "%(k)s")]
    for record in records:
        SafeRecordFilter().filter(record)
        texts = [record.getMessage(), logging.Formatter("{args}", style="{").format(record)]
        assert all(_CANARY not in t for t in texts)
        reached = _reachable(record.args)
        assert not any(o is exc or isinstance(o, functools.partial) for o in reached)


def test_userdict_inside_a_positional_list_is_replaced_at_depth_zero() -> None:
    record = _record("x %s", ([collections.UserDict({"e": ValueError(_CANARY)})],), exc=False)
    SafeRecordFilter().filter(record)
    assert record.getMessage() == "x [<mapping>]"


@pytest.mark.xfail(strict=True, reason="a plain container at depth zero is not opened")
def test_documented_gap_too_deep_in_a_lone_mapping() -> None:
    record = _lone("%(k)s", {"k": [[ValueError(_CANARY)]]})
    SafeRecordFilter().filter(record)
    assert _CANARY not in record.getMessage()


# Test 17: named args match stock output.


def _stock(msg: str, mapping: dict[object, object]) -> str:
    return msg % mapping


def test_named_args_match_stock_output() -> None:
    record = _lone(pathlib.PurePath("%(a)d"), {"a": 7})
    SafeRecordFilter().filter(record)
    assert record.getMessage() == "7"

    host = logging.Formatter("{message} {args[a]}", style="{")
    record = _lone("done", {"a": 7})
    SafeRecordFilter().filter(record)
    assert host.format(record) == "done 7"

    for msg, mapping in (
        ("%(a(b))s", {"a(b)": 5}),
        ("%%(a)s %(b)s", {"a": 1, "b": 2}),
    ):
        record = _lone(msg, mapping)
        SafeRecordFilter().filter(record)
        assert record.getMessage() == _stock(msg, mapping)

    record = _lone("%(a)s", {"a": 1, 2: 3, _SpyKey("c"): 4})
    SafeRecordFilter().filter(record)
    assert list(dict.keys(record.args)) == ["a"]  # type: ignore[arg-type]
    assert all(type(k) is str for k in dict.keys(record.args))  # type: ignore[arg-type]


# Test 19: the lone mapping keeps mapping semantics.


def test_lone_mapping_keeps_mapping_semantics(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, buf = _engine_handler()
    for msg, mapping, expected in (
        ("x", {"a": 1}, "ERROR x"),
        ("done", {"a": 1}, "ERROR done"),
        ("x %s", {"k": 1}, "ERROR x {'k': 1}"),
        ("x %r", {"k": 1}, "ERROR x {'k': 1}"),
        ("x %r", {b"status": 7}, "ERROR x <mapping>"),
        ("x %s", collections.Counter(k=1), "ERROR x <mapping>"),
        ("x %r", collections.Counter(k=1), "ERROR x <mapping>"),
        ("x %s", {"k": ValueError(_CANARY)}, "ERROR x {'k': ValueError}"),
    ):
        buf.truncate(0)
        buf.seek(0)
        record = _lone(msg, mapping)
        engine.handle(record)
        assert buf.getvalue().strip() == expected
        assert type(record.args) is _log_filter._NamedArgs
        assert record.args
    recursive: dict[str, object] = {}
    recursive["self"] = recursive
    buf.truncate(0)
    buf.seek(0)
    engine.handle(_lone("x %r", recursive))
    assert buf.getvalue().strip() == "ERROR x {'self': {'self': {...}}}"
    assert capsys.readouterr().err == ""

    record = _lone("100%%", {0: 7})
    SafeRecordFilter().filter(record)
    assert len(record.args) == 0  # type: ignore[arg-type]
    assert bool(record.args)
    assert record.getMessage() == "100%"

    # Compatibility change: a non-str key is not readable by name, so a decimal field fails.
    dest = io.StringIO()
    handler = logging.StreamHandler(dest)
    handler.setFormatter(logging.Formatter("{args[0]:d}", style="{"))
    handler.addFilter(SafeRecordFilter())
    errors: list[object] = []
    monkeypatch.setattr(handler, "handleError", errors.append)
    record = _lone("done", {0: 7})
    handler.handle(record)
    assert record.args[0] == "<mapping>"  # type: ignore[index]
    with pytest.raises(ValueError):
        handler.formatter.format(record)  # type: ignore[union-attr]
    assert len(errors) == 1
    assert dest.getvalue() == ""


# Test 20: the display scans to the same depth as the named values.


def test_lone_mapping_display_scans_to_the_named_depth(tmp_path: pathlib.Path) -> None:
    mapping = {"k": [ValueError(_CANARY)]}
    for fmt in ("x %s", "x %r"):
        assert _both(_lone(fmt, mapping), tmp_path) == ("x {'k': [ValueError]}\n",) * 2
    assert _both(_lone("%(k)s", mapping), tmp_path) == ("[ValueError]\n",) * 2
    record = _lone("x", mapping)
    SafeRecordFilter().filter(record)
    assert logging.Formatter("{args}", style="{").format(record) == "{'k': [ValueError]}"


# Test 21: sequence subclasses keep the safe rule.


class _ListSub(list):  # type: ignore[type-arg]
    pass


class _SetSub(set):  # type: ignore[type-arg]
    pass


def test_sequence_subclass_keeps_the_safe_rule(tmp_path: pathlib.Path) -> None:
    result = collections.namedtuple("Result", "issue")
    exc = ValueError(_CANARY)
    cells = (
        (result(exc), "(ValueError,)"),
        (_ListSub([exc]), "[ValueError]"),
        (_SetSub([exc]), "{ValueError}"),
        (result(1), "Result(issue=1)"),
    )
    for arg, expected in cells:
        assert _both(_record("%s", (arg,), exc=False), tmp_path) == (expected + "\n",) * 2


# Test 22: two handlers print one record the same.


@pytest.mark.parametrize(
    ("mapping", "msg", "expected"),
    [
        ({"k": 1}, "x %s", "x {'k': 1}\n"),
        ({"k": 1}, "x %r", "x {'k': 1}\n"),
        ({"k": 1}, "%(k)d", "1\n"),
        ({"k": ValueError(_CANARY)}, "x %s", "x {'k': ValueError}\n"),
        ({"k": ValueError(_CANARY)}, "x %r", "x {'k': ValueError}\n"),
        ({"k": ValueError(_CANARY)}, "%(k)s", "ValueError\n"),
    ],
)
def test_two_handlers_print_the_same_record(
    tmp_path: pathlib.Path, mapping: dict[str, object], msg: str, expected: str
) -> None:
    stream_out, file_out = _both(_lone(msg, mapping), tmp_path)
    assert stream_out == expected
    assert file_out == expected


# Test 23: an unused value cannot drop a named record.


def test_unused_value_cannot_drop_a_named_record() -> None:
    engine, buf = _engine_handler()
    mapping = {"a": 7, "unused": 10**5000}
    engine.handle(_lone("%(a)d", mapping))
    engine.handle(_lone("x %s", mapping))
    assert buf.getvalue().splitlines() == ["ERROR 7", "ERROR x <mapping>"]
    assert "could not be made safe" not in buf.getvalue()


# Test 18: the filter builds only closed types.

_FILTER_SOURCE = pathlib.Path(_log_filter.__file__).read_text(encoding="utf-8")
_CHECKED = ("_safe_value", "_safe_pairs", "_named_args")
_BANNED_CALLS = {
    "collections.OrderedDict",
    "collections.Counter",
    "collections.defaultdict",
    "collections.UserDict",
    "copy.copy",
    "copy.deepcopy",
}
_BASES = {"list", "tuple", "set", "frozenset"}


def _aliases(tree: ast.Module) -> dict[str, str]:
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names[a.asname or a.name] = a.name
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                names[a.asname or a.name] = f"{node.module}.{a.name}"
    return names


def _dotted(node: ast.expr, names: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return names.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value, names)
        return None if head is None else f"{head}.{node.attr}"
    return None


def _flaws(source: str) -> list[str]:
    tree = ast.parse(source)
    names = _aliases(tree)
    found: list[str] = []
    items_sites: list[tuple[str, int]] = []
    for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))]:
        for node in ast.walk(func):
            if isinstance(node, ast.Call):
                target = _dotted(node.func, names)
                if target in _BANNED_CALLS or target == "copy":
                    found.append(f"{func.name}:{node.lineno} builds {target}")
                if isinstance(node.func, ast.Call) and _dotted(node.func.func, names) == "type":
                    found.append(f"{func.name}:{node.lineno} type(...)(...)")
                if func.name == "_safe_value" and target == "isinstance":
                    found.append(f"{func.name}:{node.lineno} isinstance")
            if isinstance(node, ast.Attribute):
                where = f"{func.name}:{node.lineno}"
                if node.attr in {"default_factory", "get", "keys", "values"}:
                    found.append(f"{where} reads .{node.attr}")
                if node.attr == "items":
                    items_sites.append((func.name, node.lineno))
                if node.attr == "__iter__" and not (
                    isinstance(node.value, ast.Name) and node.value.id in _BASES
                ):
                    found.append(f"{where} __iter__ outside the four base types")
            if func.name in _CHECKED and isinstance(node, ast.Compare):
                for op, right in zip(node.ops, node.comparators, strict=True):
                    if isinstance(op, (ast.In, ast.NotIn)):
                        found.append(f"{func.name}:{node.lineno} membership test")
                    if isinstance(op, (ast.Eq, ast.NotEq)):
                        sides = [node.left, right]
                        if not any(
                            isinstance(s, ast.Constant) and isinstance(s.value, int) for s in sides
                        ):
                            found.append(f"{func.name}:{node.lineno} == on a caller value")
    ok = [s for s in items_sites if s[0] == "_safe_pairs"]
    found.extend(
        f"{n}:{ln} dict.items outside _safe_pairs" for n, ln in items_sites if n != "_safe_pairs"
    )
    if len(ok) != 1:
        found.append(f"_safe_pairs has {len(ok)} items reads, expected exactly 1")
    return found


def test_filter_builds_only_closed_types() -> None:
    assert _flaws(_FILTER_SOURCE) == []


_HEAD = "def _safe_value(value: object, depth: int) -> object:\n"


@pytest.mark.parametrize(
    ("seed", "needle"),
    [
        ("    x = defaultdict(int)\n", "builds"),
        ("    x = collections.OrderedDict()\n", "builds"),
        ("    x = OD()\n", "builds"),
        ("    x = c.defaultdict(int)\n", "builds"),
        ("    x = store.get('a')\n", "reads .get"),
        ("    x = value == depth\n", "== on a caller value"),
        ("    x = dict.items(value)\n", "dict.items outside _safe_pairs"),
    ],
)
def test_filter_sentry_flags_each_seed(seed: str, needle: str) -> None:
    header = (
        "import collections\nimport collections as c\nfrom collections import OrderedDict as OD\n"
    )
    assert _HEAD in _FILTER_SOURCE
    seeded = header + _FILTER_SOURCE.replace(_HEAD, _HEAD + seed, 1)
    flagged = _flaws(seeded)
    assert any(needle in f for f in flagged), flagged
    assert any(f.startswith("_safe_value:") for f in flagged), flagged
