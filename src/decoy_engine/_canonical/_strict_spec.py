"""The strict persisted-reader specs shared by every versioned on-disk record.

A record's wire shape is one declaration of ``(name, spec)`` pairs. Each spec both reads a JSON
value (``load``) and writes the typed value back (``dump``), so the writer cannot emit what the
reader refuses. The rules are the persisted-reader contract: exact built-in JSON types (``bool``
is never an ``int``), bounded counts, closed tokens, ``re.fullmatch`` shapes (a ``$`` anchor also
matches before a trailing newline), relative paths one validated component at a time, every field
present and none unknown.

A refusal raises :class:`SpecRefusedError` carrying only a closed check token. The owner of a record
format turns it into its own refusal outside the handler that caught it, so no exception context
holds a byte of the record. This module imports only the canonical JSON error base: the shape tests
a spec needs (the component validator, the count limit) are handed in by the declaration.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from typing import Any, Literal, NoReturn, Protocol

from decoy_engine._canonical._json import CanonicalJsonError, StrictJsonError, strict_json_loads

__all__ = [
    "UNIT_PATH_MAX_DEPTH",
    "CountSpec",
    "ExactSpec",
    "ListSpec",
    "NullableSpec",
    "ObjectSpec",
    "OneOfSpec",
    "RelPathSpec",
    "ShapedSpec",
    "Spec",
    "SpecCheck",
    "SpecRefusedError",
    "VersionSpec",
    "attempt",
    "check_unit_path",
    "check_unit_paths",
    "parse_or_token",
]

SpecCheck = Literal[
    "schema_unknown",
    "missing_field",
    "unknown_field",
    "wrong_type",
    "out_of_range",
    "bad_token",
    "bad_path",
]


class SpecRefusedError(CanonicalJsonError):
    """A spec refused a value; ``check`` is the closed token and the only payload.

    It sits under ``CanonicalJsonError``, as ``StrictJsonError`` does, so it is a ``DecoyError``
    and a ``ValueError`` in the registered config family with no new family to classify.
    """

    def __init__(self, check: SpecCheck) -> None:
        super().__init__(check)
        self.check = check

    def __reduce__(self) -> tuple[type[SpecRefusedError], tuple[str]]:
        return (type(self), (self.check,))


def _refuse(check: SpecCheck) -> NoReturn:
    raise SpecRefusedError(check)


class Spec(Protocol):
    def load(self, raw: Any) -> Any: ...
    def dump(self, value: Any) -> Any: ...
    def describe(self) -> str: ...


@dataclass(frozen=True)
class ExactSpec:
    value: str

    def load(self, raw: Any) -> str:
        if type(raw) is not str or raw != self.value:
            _refuse("schema_unknown")
        return raw

    def dump(self, value: Any) -> Any:
        return value

    def describe(self) -> str:
        return f"exact:{self.value}"


@dataclass(frozen=True)
class VersionSpec:
    """A numeric format version: exactly the declared integer (a ``bool`` is not one)."""

    value: int

    def load(self, raw: Any) -> int:
        if type(raw) is not int or raw != self.value:
            _refuse("schema_unknown")
        return raw

    def dump(self, value: Any) -> Any:
        return value

    def describe(self) -> str:
        return f"version:{self.value}"


@dataclass(frozen=True)
class OneOfSpec:
    values: tuple[str, ...]

    def load(self, raw: Any) -> str:
        if type(raw) is not str:
            _refuse("wrong_type")
        if raw not in self.values:
            _refuse("bad_token")
        return raw

    def dump(self, value: Any) -> Any:
        return value

    def describe(self) -> str:
        return "one_of:" + "|".join(self.values)


@dataclass(frozen=True)
class ShapedSpec:
    pattern: str
    test: Any  # (object) -> bool, the one shape check for this kind of value

    def load(self, raw: Any) -> str:
        if type(raw) is not str:
            _refuse("wrong_type")
        if not self.test(raw):
            _refuse("bad_token")
        return raw

    def dump(self, value: Any) -> Any:
        return value

    def describe(self) -> str:
        return f"fullmatch:{self.pattern}"


@dataclass(frozen=True)
class CountSpec:
    limit: int

    def load(self, raw: Any) -> int:
        if type(raw) is not int:
            _refuse("wrong_type")
        # `type(...) is int` above: `bool` is an `int` subclass and must never pass as a count.
        if not 0 <= raw <= self.limit:
            _refuse("out_of_range")
        return raw

    def dump(self, value: Any) -> Any:
        return value

    def describe(self) -> str:
        return "count"


UNIT_PATH_MAX_DEPTH = 8


def check_unit_path(
    path: object,
    *,
    component_test: Callable[[str], bool],
    reserved: Collection[str] = (),
    max_depth: int = UNIT_PATH_MAX_DEPTH,
) -> None:
    """Refuse one member path of a unit that is not an exact built-in string of at most
    ``max_depth`` components, each passing ``component_test`` (no empty, ``.``, ``..`` or NUL
    part, so no absolute path and no escape from the unit root), or that is a whole reserved name
    (compared casefolded: macOS and Windows file systems fold case). Writer and reader share this
    one rule."""
    if type(path) is not str:
        _refuse("wrong_type")
    parts = path.split("/")
    if (
        len(parts) > max_depth
        or not all(component_test(p) for p in parts)
        or path.casefold() in {name.casefold() for name in reserved}
    ):
        _refuse("bad_path")


def check_unit_paths(paths: Iterable[str]) -> None:
    """Refuse the facts only a whole unit shows: a duplicate path, or one path that is a folder
    prefix of another (``a`` beside ``a/b``). Each path already passed ``check_unit_path``."""
    seen: set[str] = set()
    for path in paths:
        if path in seen:
            _refuse("bad_path")
        seen.add(path)
    for path in seen:
        head, sep, _ = path.rpartition("/")
        while sep:
            if head in seen:
                _refuse("bad_path")
            head, sep, _ = head.rpartition("/")


@dataclass(frozen=True)
class RelPathSpec:
    component_test: Any  # (object) -> bool, the engine's one path component validator
    reserved: Collection[str] = ()  # whole paths this record may not name

    def load(self, raw: Any) -> str:
        check_unit_path(raw, component_test=self.component_test, reserved=self.reserved)
        return str(raw)

    def dump(self, value: Any) -> Any:
        return value

    def describe(self) -> str:
        return "rel_path"


@dataclass(frozen=True)
class ListSpec:
    item: Spec

    def load(self, raw: Any) -> tuple[Any, ...]:
        if type(raw) is not list:
            _refuse("wrong_type")
        return tuple(self.item.load(entry) for entry in raw)

    def dump(self, value: Any) -> Any:
        if type(value) is not tuple:
            _refuse("wrong_type")
        return [self.item.dump(entry) for entry in value]

    def describe(self) -> str:
        return f"list:{self.item.describe()}"


@dataclass(frozen=True)
class NullableSpec:
    item: Spec

    def load(self, raw: Any) -> Any:
        return None if raw is None else self.item.load(raw)

    def dump(self, value: Any) -> Any:
        return None if value is None else self.item.dump(value)

    def describe(self) -> str:
        return f"nullable:{self.item.describe()}"


@dataclass(frozen=True)
class ObjectSpec:
    cls: type
    fields: tuple[tuple[str, Spec], ...]

    def load(self, raw: Any) -> Any:
        if type(raw) is not dict:
            _refuse("wrong_type")
        names = {name for name, _ in self.fields}
        if not names <= raw.keys():
            _refuse("missing_field")
        if not raw.keys() <= names:
            _refuse("unknown_field")
        return self.cls(**{name: spec.load(raw[name]) for name, spec in self.fields})

    def dump(self, value: Any) -> dict[str, Any]:
        if type(value) is not self.cls:
            _refuse("wrong_type")
        return {name: spec.dump(getattr(value, name)) for name, spec in self.fields}

    def describe(self) -> str:
        inner = ",".join(f"{name}={spec.describe()}" for name, spec in self.fields)
        return f"object:({inner})"


def attempt(call: Callable[[Any], Any], arg: Any) -> tuple[Any, SpecCheck | None]:
    """``call(arg)``; a spec refusal comes back as its closed token.

    The caller raises its own refusal from the token, outside this handler, so no exception
    context carries a byte of the record.
    """
    try:
        return call(arg), None
    except SpecRefusedError as error:
        return None, error.check


def parse_or_token(data: bytes, max_int_digits: int) -> tuple[Any, str | None]:
    """Strict JSON of ``data``; a refusal comes back as the decoder's closed token."""
    try:
        return strict_json_loads(data, max_int_digits=max_int_digits), None
    except StrictJsonError as error:
        return None, error.token
