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

from dataclasses import dataclass
from typing import Any, Literal, NoReturn, Protocol

from decoy_engine._canonical._json import CanonicalJsonError

__all__ = [
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


@dataclass(frozen=True)
class RelPathSpec:
    component_test: Any  # (object) -> bool, the engine's one path component validator
    reserved: str | None = None  # a whole path this record may not name

    def load(self, raw: Any) -> str:
        if type(raw) is not str:
            _refuse("wrong_type")
        # Each component through the one validator: no empty, `.`, `..` or NUL part, so no
        # absolute path and no escape from the root the path is relative to.
        if raw == self.reserved or not all(self.component_test(p) for p in raw.split("/")):
            _refuse("bad_path")
        return raw

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
