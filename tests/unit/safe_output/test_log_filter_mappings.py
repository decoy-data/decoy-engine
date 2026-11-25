"""F31 AE3: mapping, depth and named-argument behavior of `SafeRecordFilter`.

Plan: docs/plans/2026-11-25-f31-ae3-plan-amendment.md.

Plan: docs/plans/2026-11-24-f31-audit.md, Behavior 4 and acceptance test 2. The canary is built
at run time in most cells, so a stock traceback's source lines cannot carry it by accident; the
one cell that writes it as a literal checks that the filter prints no source lines either.
"""

from __future__ import annotations

import argparse
import collections
import collections.abc
import configparser
import dataclasses
import datetime
import decimal
import enum
import functools
import io
import logging
import pathlib
import types
import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from decoy_engine.safe_output import SafeRecordFilter, _log_filter
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
    assert record.getMessage() == "[ValueError, <object>] {'k': ValueError, 'i': <object>}"
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


class _StrSub(str):
    """A `str` subclass whose own `__str__` and `__repr__` would print the canary."""

    __slots__ = ()

    def __str__(self) -> str:
        _CALLS.append("str")
        return _CANARY

    def __repr__(self) -> str:
        _CALLS.append("repr")
        return _CANARY


@pytest.mark.parametrize("inner", ["list", "tuple", "dict", "set"])
def test_plain_container_at_the_depth_limit_is_the_placeholder(inner: str) -> None:
    # Codex R1 V1: positional `[[exc]]` and the lone-mapping `{"k": [[exc]]}`.
    exc = ValueError(_CANARY)
    cell = {"list": [exc], "tuple": (exc,), "dict": {"e": exc}, "set": {exc}}[inner]
    engine, buf = _engine_handler()
    engine.handle(_record("x %s", ([cell],), exc=False))
    assert buf.getvalue().strip() == "ERROR x [<nested>]"
    lone = _lone("%(k)s", {"k": [cell]})
    SafeRecordFilter().filter(lone)
    assert lone.getMessage() == "[<nested>]"
    assert not any(o is exc for o in _reachable(lone.args))


def test_clean_scalars_at_the_depth_limit_are_kept() -> None:
    record = _record("%s", ([1, "a", None, 2.5],), exc=False)
    SafeRecordFilter().filter(record)
    assert record.getMessage() == "[1, 'a', None, 2.5]"


@pytest.mark.parametrize("where", ["arg", "in_list", "in_dict_value"])
def test_str_subclass_is_a_plain_copy(where: str) -> None:
    value = _StrSub("ok")
    arg = {"arg": value, "in_list": [value], "in_dict_value": {"k": value}}[where]
    record = _record("%s %r", (arg, arg), exc=False)
    _CALLS.clear()
    SafeRecordFilter().filter(record)
    text = record.getMessage()
    assert _CANARY not in text
    assert "ok" in text
    assert _CALLS == []


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
    assert buf.getvalue().strip() == "ERROR x {'self': {'self': <nested>}}"
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
        (result(1), "(1,)"),
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


# Dennis R2 V1: unknown iterables, views, dataclasses and slices.


@dataclasses.dataclass
class _Holder:
    error: object


class _AttrsLike:
    """What `attrs.define` leaves on a class: `__attrs_attrs__` and a repr that prints fields."""

    __attrs_attrs__ = ("error",)

    def __init__(self, error: object) -> None:
        self.error = error

    def __repr__(self) -> str:
        return f"AttrsLike(error={self.error!r})"


class _NamespaceSub(types.SimpleNamespace):
    pass


class _Wrapper:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def __str__(self) -> str:
        return str(self._exc)


class _CustomIterable:
    def __init__(self, error: object) -> None:
        self.error = error

    def __iter__(self):  # type: ignore[no-untyped-def]
        _CALLS.append("iter")
        yield self.error

    def __repr__(self) -> str:
        return f"CustomIterable({self.error!r})"


def _protocol_cell(name: str, exc: BaseException) -> tuple[object, str]:
    return {
        "deque": (collections.deque([exc]), "[ValueError]"),
        "dict_keys": ({exc: 1}.keys(), "[ValueError]"),
        "dict_values": ({"k": exc}.values(), "[ValueError]"),
        "dict_items": ({"k": exc}.items(), "[<nested>]"),
        "custom_iterable": (_CustomIterable(exc), "<nested>"),
        "generator": ((e for e in [exc]), "<nested>"),
        "dataclass": (_Holder(exc), "<object>"),
        "attrs_like": (_AttrsLike(exc), "<object>"),
        "slice": (slice(exc, None), "slice(ValueError, None, None)"),
        "simple_namespace": (types.SimpleNamespace(error=exc), "<object>"),
        "namespace_subclass": (_NamespaceSub(error=exc), "<object>"),
        "argparse_namespace": (argparse.Namespace(error=exc), "<object>"),
        "partial": (functools.partial(_ret, exc), "<object>"),
        "wrapper": (_Wrapper(exc), "<object>"),
    }[name]


_PROTOCOL_CELLS = [
    "deque",
    "dict_keys",
    "dict_values",
    "dict_items",
    "custom_iterable",
    "generator",
    "dataclass",
    "attrs_like",
    "slice",
    "simple_namespace",
    "namespace_subclass",
    "argparse_namespace",
    "partial",
    "wrapper",
]


@pytest.mark.parametrize("name", _PROTOCOL_CELLS)
@pytest.mark.parametrize("where", ["positional", "lone_value"])
def test_protocol_routed_objects_print_no_exception_text(
    name: str, where: str, tmp_path: pathlib.Path
) -> None:
    exc = ValueError(_CANARY)
    cell, expected = _protocol_cell(name, exc)
    _CALLS.clear()
    if where == "positional":
        record = _record("x %s", (cell,), exc=False)
        want = f"x {expected}\n"
    else:
        record = _lone("%(k)s", {"k": cell})
        want = f"{expected}\n"
    assert _both(record, tmp_path) == (want, want)
    assert _CALLS == []
    assert not any(o is exc for o in _reachable(record.args))


@pytest.mark.parametrize("name", _PROTOCOL_CELLS)
def test_protocol_routed_objects_at_the_depth_limit(name: str) -> None:
    exc = ValueError(_CANARY)
    cell, _ = _protocol_cell(name, exc)
    record = _record("x %s", ([[cell]],), exc=False)
    SafeRecordFilter().filter(record)
    assert _CANARY not in record.getMessage()


def test_scalars_and_plain_objects_still_print_as_before() -> None:
    values = (
        pathlib.PurePosixPath("/tmp/a"),
        decimal.Decimal("1.50"),
        datetime.datetime(2026, 11, 25, 1, 2, 3),
        datetime.date(2026, 11, 25),
        uuid.UUID(int=7),
        range(3),
        b"ab",
        None,
        2.5,
    )
    msg = " ".join(["%s"] * len(values))
    record = _record(msg, values, exc=False)
    expected = msg % values
    SafeRecordFilter().filter(record)
    assert record.getMessage() == expected
    # And the same values one level inside a list.
    inside = _record("%s", (list(values),), exc=False)
    expected_inside = f"{list(values)}"
    SafeRecordFilter().filter(inside)
    assert inside.getMessage() == expected_inside


def test_removing_the_iterable_route_is_visible() -> None:
    # Pins the route itself: an unknown iterable is the placeholder, never its own repr.
    record = _record("%s", (_CustomIterable(ValueError(_CANARY)),), exc=False)
    SafeRecordFilter().filter(record)
    assert record.getMessage() == "<nested>"


# Security review: a subclass never returns the original object, so its own repr never runs.


class _Color(enum.Enum):
    RED = 1

    def __repr__(self) -> str:
        return _CANARY

    def __str__(self) -> str:
        return _CANARY


class _IntSub(int):
    def __repr__(self) -> str:
        return _CANARY

    __str__ = __repr__


class _ListSubLeak(list):  # type: ignore[type-arg]
    def __repr__(self) -> str:
        return _CANARY

    __str__ = __repr__


class _PathSub(type(pathlib.PurePosixPath())):  # type: ignore[misc]
    def __repr__(self) -> str:
        return _CANARY

    __str__ = __repr__


class _DecimalSub(decimal.Decimal):
    def __repr__(self) -> str:
        return _CANARY

    __str__ = __repr__


@dataclasses.dataclass(init=False, repr=False, eq=False)
class _RecordTuple(tuple):  # type: ignore[type-arg]
    def __repr__(self) -> str:
        return _CANARY

    __str__ = __repr__


def _subclass_cells() -> dict[str, tuple[object, str]]:
    return {
        "int_sub": (_IntSub(5), "5"),
        "list_sub": (_ListSubLeak([1]), "[1]"),
        "path_sub": (_PathSub("/tmp/a"), "<object>"),
        "decimal_sub": (_DecimalSub("1.5"), "<object>"),
        "enum": (_Color.RED, "_Color.RED"),
        "record_tuple": (_RecordTuple((1, 2)), "<object>"),
    }


@pytest.mark.parametrize("name", list(_subclass_cells()))
@pytest.mark.parametrize("where", ["positional", "lone_value", "nested"])
@pytest.mark.parametrize("conv", ["%s", "%r"])
def test_a_subclass_never_prints_through_its_own_repr(
    name: str, where: str, conv: str, tmp_path: pathlib.Path
) -> None:
    cell, expected = _subclass_cells()[name]
    if where == "positional":
        record = _record(f"x {conv}", (cell,), exc=False)
        want = f"x {expected}\n"
    elif where == "lone_value":
        record = _lone(f"{conv}", {"k": cell}) if False else _lone("%(k)" + conv[1:], {"k": cell})
        want = f"{expected}\n"
    else:
        record = _record(f"x {conv}", ([cell],), exc=False)
        inner = "<nested>" if name == "list_sub" else expected  # a container at the limit
        want = f"x [{inner}]\n"
    out = _both(record, tmp_path)
    assert _CANARY not in out[0]
    assert out == (want, want)


def test_clean_exact_scalars_and_containers_keep_their_identity() -> None:
    values = [pathlib.PurePosixPath("/a"), decimal.Decimal("1"), [1], (1,), {"a": 1}]
    record = _record("%s %s %s %s %s", tuple(values), exc=False)
    SafeRecordFilter().filter(record)
    assert all(a is b for a, b in zip(record.args, values, strict=True))  # type: ignore[arg-type]
