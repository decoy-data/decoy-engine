"""F31 AE3: objects the filter has no mapping row for (iterables, records, subclasses).

Plan: docs/plans/2026-11-25-f31-ae3-plan-amendment.md.
"""

from __future__ import annotations

import argparse
import collections
import collections.abc
import dataclasses
import datetime
import decimal
import enum
import fractions
import functools
import pathlib
import types
import uuid

import pytest

from decoy_engine.safe_output import SafeRecordFilter
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

_CALLS: list[str] = []


# Dennis R2 V1: unknown iterables, views, dataclasses and slices.


@dataclasses.dataclass
class _Holder:
    error: object

    def method(self) -> None:
        """Bound, its repr is `<bound method _Holder.method of {repr(instance)}>`."""


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


def _numpy_int() -> object:
    numpy = pytest.importorskip("numpy")
    return numpy.int64(1)


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
        "bound_method": (_Holder(exc).method, "<object>"),
        "fraction": (fractions.Fraction(1, 2), "<object>"),
        "numpy_int": (_numpy_int(), "<object>"),
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
    "bound_method",
    "fraction",
    "numpy_int",
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


class _Num(enum.IntEnum):
    RED = 1

    def __repr__(self) -> str:
        return _CANARY

    __str__ = __repr__


class _Perm(enum.IntFlag):
    READ = 1

    def __repr__(self) -> str:
        return _CANARY

    __str__ = __repr__


if hasattr(enum, "StrEnum"):
    _Mode = enum.StrEnum("_Mode", {"FAST": "fast"})
else:  # Python 3.10 has no StrEnum; the str mixin takes the same row.
    _Mode = enum.Enum("_Mode", {"FAST": "fast"}, type=str)  # type: ignore[misc]


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
        "int_enum": (_Num.RED, "1"),
        "int_flag": (_Perm.READ, "1"),
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


def test_int_enum_member_formats_under_percent_d(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The member copies to its number, so `%d` works as it does on stock logging.
    for member in (_Num.RED, _Perm.READ):
        assert _both(_record("x %d", (member,), exc=False), tmp_path) == ("x 1\n", "x 1\n")
    assert capsys.readouterr().err == ""


def test_str_enum_member_prints_its_value(tmp_path: pathlib.Path) -> None:
    member = _Mode.FAST
    assert _both(_record("x %s", (member,), exc=False), tmp_path) == ("x fast\n", "x fast\n")
    assert _both(_lone("%(k)s", {"k": member}), tmp_path) == ("fast\n", "fast\n")
    assert _both(_record("x %s", ([member],), exc=False), tmp_path) == ("x ['fast']\n",) * 2


# B10, B11: a key outside the plain key types and a name the dict lacks print the placeholder.


@pytest.mark.parametrize(
    "key",
    [(1,), b"k", frozenset({1}), _Num.RED, _Mode.FAST],
    ids=["tuple", "bytes", "frozenset", "int_enum", "str_enum"],
)
def test_non_plain_key_and_missing_name_print_the_placeholder(
    key: object, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    keyed = {key: 1}
    record = _record("x %s %d", (keyed, 1), exc=False)
    assert _both(record, tmp_path) == ("x <mapping> 1\n", "x <mapping> 1\n")
    assert keyed == {key: 1}
    assert capsys.readouterr().err == ""


def test_missing_name_in_a_lone_dict_prints_the_placeholder(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _lone("%(a)s %(missing)s", {"a": 1})
    assert _both(record, tmp_path) == ("1 <mapping>\n", "1 <mapping>\n")
    assert capsys.readouterr().err == ""


# Row 12 and row 13 read a caller object with no caller method.


def _rec(name: str, result: object):  # type: ignore[no-untyped-def]
    def method(self: object, *_args: object) -> object:
        _CALLS.append(name)
        return result

    return method


def _recorders() -> dict[str, object]:
    return {
        "__repr__": _rec("repr", _CANARY),
        "__str__": _rec("str", _CANARY),
        "__format__": _rec("format", _CANARY),
        "__eq__": _rec("eq", True),
        "__hash__": _rec("hash", 1),
    }


def _recording_cells() -> list[tuple[object, str]]:
    plain = type("_RecPlain", (), _recorders())()
    int_sub = type(
        "_RecInt",
        (int,),
        {**_recorders(), "__int__": _rec("int", 5), "__index__": _rec("index", 5)},
    )(5)
    float_sub = type("_RecFloat", (float,), {**_recorders(), "__float__": _rec("float", 1.5)})(1.5)
    return [(plain, "<object>"), (int_sub, "5"), (float_sub, "1.5")]


@pytest.mark.parametrize("index", [0, 1, 2], ids=["object", "int_sub", "float_sub"])
@pytest.mark.parametrize("where", ["positional", "lone_value"])
def test_other_value_runs_no_caller_code(index: int, where: str, tmp_path: pathlib.Path) -> None:
    cell, expected = _recording_cells()[index]
    if where == "positional":
        record = _record("x %s", (cell,), exc=False)
        want = f"x {expected}\n"
    else:
        record = _lone("%(k)s", {"k": cell})
        want = f"{expected}\n"
    _CALLS.clear()
    assert _both(record, tmp_path) == (want, want)
    assert _CALLS == []
