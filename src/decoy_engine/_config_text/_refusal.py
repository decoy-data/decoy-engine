"""The refusal text builder: a location, a closed problem, a closed expected type.

Every refusal a config loader raises takes its text and its `path` key from `config_refusal`,
so no supplied value, file locator or library exception text can reach `str(exc)`. The model
is the one Pydantic and `jsonschema` use for validation failures: where the problem is (a
tuple of field names and indexes), what kind of problem it is (a closed error type) and what
was expected, with the input left out (`ValidationError.errors(include_input=False)`). See
OWASP ASVS 7.4.1 and CWE-209 for the rule that error text stays generic.

Only these reach the text: literal field names written in engine source, integer indexes,
supplied names that pass `approve_name` (else a fixed placeholder), the closed `Problem`,
`Expected` and `Kind` members, engine-owned constant choice lists and literal hints.
`tests/sentry/defects/test_config_refusal_text.py` enforces the call shape.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath

from decoy_engine import reasons
from decoy_engine.fileaccess import position_key
from decoy_engine.reasons import approve_name


class Problem(Enum):
    """What went wrong, as one fixed phrase."""

    MISSING = "missing"
    EMPTY = "empty"
    WRONG_TYPE = "wrong type"
    NOT_FOUND = "not found"
    UNREADABLE = "could not be read"
    SNAPSHOT_UNREADABLE = "snapshot_file could not be read"
    UNPARSEABLE = "could not be parsed"
    DUPLICATE = "declared more than once"
    MISMATCH = "does not match"
    TOO_LARGE = "too large"
    NOT_ALLOWED = "not allowed"


class Expected(Enum):
    """What the field should hold, as one fixed phrase. A new phrase is a new member here."""

    STRING = "a string"
    NON_EMPTY_STRING = "a non-empty string"
    INTEGER = "an integer"
    INT64 = "int64"
    RELEASE_ID = "a string or integer release id"
    BOOLEAN = "a boolean"
    NUMBER = "a number"
    LIST = "a list"
    NON_EMPTY_LIST = "a non-empty list"
    MAPPING = "a mapping"
    NON_EMPTY_MAPPING = "a non-empty mapping"
    FILE = "a file"
    PARQUET_TABLE = "a readable Parquet table"
    NAME = "a name"
    SHIPPED_NAME = "the name of a shipped table or corpus"
    ID_COLUMN = "an int64 id column"
    CODE_COLUMN = "a code column"
    STRING_COLUMN = "a string column"
    SCHEMA_VERSION = "an accepted schema version"
    SHA256 = "a sha256 digest"
    BASE64 = "base64 text"
    UTF8_JSON = "UTF-8 JSON"
    MODE = "a supported mode"
    ONE_OF_CHOICES = "one of the allowed choices"
    CATEGORICAL_SOURCE = "a categorical source column"
    FIELD_PRESENT = "this field to be present"
    REFERENCE_TABLE = "a shipped or customer-provided reference table"
    SNAPSHOT_FILE = "a readable snapshot_file"


class Kind(Enum):
    """A closed kind of a rejected value: a column kind or a Python value kind. Never a type
    name, never a repr, so no file-authored text (a time zone, a struct field) can reach a message."""

    INTEGER = "integer"
    FLOATING_POINT = "floating-point"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    STRING = "string"
    BINARY = "binary"
    TIMESTAMP = "timestamp"
    DATE = "date"
    TIME = "time"
    DURATION = "duration"
    DICTIONARY = "dictionary"
    NESTED = "nested"
    LIST = "list"
    DICT = "dict"
    NULL = "null"
    SET = "set"
    OTHER = "other"


# Exact types only: a subclass (a `str` that overrides `__repr__`) is `other`, never trusted.
_VALUE_KINDS: tuple[tuple[type, Kind], ...] = (
    (bool, Kind.BOOLEAN),
    (int, Kind.INTEGER),
    (float, Kind.FLOATING_POINT),
    (str, Kind.STRING),
    (list, Kind.LIST),
    (dict, Kind.DICT),
    (type(None), Kind.NULL),
    (datetime.date, Kind.DATE),
    (datetime.datetime, Kind.TIMESTAMP),
    (bytes, Kind.BINARY),
    (set, Kind.SET),
)


def kind_of(value: object) -> Kind:
    """The closed kind of `value`, by exact type."""
    kind = type(value)
    for candidate, label in _VALUE_KINDS:
        if kind is candidate:
            return label
    return Kind.OTHER


_NAME_SHOWN = "<name>"
_FILE_SHOWN = "<file>"


@dataclass(frozen=True, slots=True)
class Name:
    """A supplied name (a detector id, a column) at a position. Shown only when it is a plain
    `str` that passes `approve_name`; anything else shows as `<name>`. Takes the raw config
    object, never a converted one: `str(["x"])` would turn a list into an approvable string."""

    value: object

    def shown(self) -> str:
        if type(self.value) is str:
            approved = approve_name(self.value)
            if approved is not None:
                return approved
        return _NAME_SHOWN


@dataclass(frozen=True, slots=True)
class QuotedName(Name):
    """A `Name` shown in single quotes, for a message that names a column in a sentence (the
    withheld-values refusal). The quotes are added only around an approved name."""

    def shown(self) -> str:
        text = Name.shown(self)
        return text if text == _NAME_SHOWN else f"'{text}'"


def _is_url(value: str) -> bool:
    """URL syntax: a scheme separator anywhere, or a network-path reference (`//host/x`)."""
    return "://" in value or value.startswith("//")


@dataclass(frozen=True, slots=True)
class Member:
    """A file name a manifest lists. Shown as the bare name when it passes the same checks as
    `Name`, so `../x` and `/etc/x` show as `x`; anything else shows as `<file>`."""

    value: object

    def shown(self) -> str:
        # A URL's last segment can be a bearer token that passes `approve_name`, so the raw
        # value is checked for URL syntax before any basename is taken.
        if type(self.value) is str and not _is_url(self.value):
            bare = PurePosixPath(self.value).name
            approved = approve_name(bare)
            if approved is not None:
                return approved
        return _FILE_SHOWN


Segment = str | int | Name | Member


@dataclass(frozen=True, slots=True)
class ConfigPosition:
    """Where a refusal happened. `key` is the display joined once, with the table and column an
    enclosing `at_position` binds, so a refusal and its `path` agree."""

    key: str


def _display(segments: tuple[Segment, ...]) -> str:
    out = ""
    for segment in segments:
        if isinstance(segment, bool):
            raise TypeError("a position index is an int, not a bool")
        if isinstance(segment, int):
            out += f"[{segment}]"
        elif isinstance(segment, Member):
            out += f"/{segment.shown()}"
        elif isinstance(segment, Name):
            out += f".{segment.shown()}" if out else segment.shown()
        else:
            out += f".{segment}" if out else segment
    return out


def config_position(*segments: Segment) -> ConfigPosition:
    """Join `segments` into one position. A plain `str` is a field name and must be a literal
    (sentry rule S2)."""
    return ConfigPosition(position_key(_display(segments)))


class _Absent:
    pass


_ABSENT = _Absent()


@dataclass(frozen=True, slots=True)
class Refusal:
    """A built refusal. Only `config_refusal` makes one; `Refusal(...)` elsewhere is a sentry
    finding. `detail` is the text with no position prefix, for a class that prints its `path`."""

    text: str
    detail: str
    key: str


def _choices_text(choices: tuple[str, ...]) -> str:
    shown = [c for c in choices if approve_name(c) is not None]
    return ", ".join(shown)


def config_refusal(
    position: ConfigPosition,
    problem: Problem,
    *,
    expected: Expected | None = None,
    got: object = _ABSENT,
    got_kind: Kind | None = None,
    choices: tuple[str, ...] | None = None,
    names: tuple[Name, ...] | None = None,
    code: str | None = None,
    hint: str | None = None,
    line: int | None = None,
    column: int | None = None,
) -> Refusal:
    """Build the refusal for `problem` at `position`.

    `got` is a Python value and `got_kind` a closed kind; passing both is a `TypeError`.
    `names` lists supplied names (each a `Name`, shown only when it passes `approve_name`).
    `code` is an engine reason code whose registered summary is appended (engine-owned text).
    `line` and `column` are the integer mark of a parse failure and are used only by
    `read_config`.
    """
    if got is not _ABSENT and got_kind is not None:
        raise TypeError("pass got or got_kind, not both")
    detail = problem.value
    if type(line) is int and type(column) is int and problem is Problem.UNPARSEABLE:
        detail += f" at line {line}, column {column}"
    if expected is not None:
        detail += f"; expected {expected.value}"
    kind = kind_of(got) if got is not _ABSENT else got_kind
    if kind is not None:
        detail += f", got {kind.value}"
    if choices:
        detail += f". Allowed: {_choices_text(choices)}"
    if code is not None:
        specs = reasons.lookup(code)
        if specs:
            detail += f". {specs[0].summary}"
    if names:
        detail += f". Names: {', '.join(n.shown() for n in names)}"
    if hint:
        detail += f". {hint}"
    return Refusal(text=f"{position.key}: {detail}", detail=detail, key=position.key)
