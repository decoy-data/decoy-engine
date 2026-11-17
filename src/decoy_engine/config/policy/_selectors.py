"""The closed selector grammar of the pipeline `policy` block.

Keys AND, list values OR, no negation, no nesting: the form of AWS Lake Formation LF-tag
expressions and Kubernetes `matchLabels`. Globs use `fnmatch.fnmatchcase`, which is
case-sensitive and anchored (it compiles to a regex ending in `\\Z`), so `"*_date"` does not
match `"a_date\\n"`.

Refusals are fixed registry text; a submitted value never reaches a message.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_core import PydanticCustomError

from decoy_engine import reasons
from decoy_engine.config._declared_casting import LOGICAL_TYPES
from decoy_engine.detection.domains import registered_detector_ids

__all__ = [
    "MAX_LIST_VALUES",
    "MAX_VALUE_LENGTH",
    "ROLES",
    "SLUG_RE",
    "FieldFacts",
    "Selector",
    "has_glob",
    "matches",
]

MAX_VALUE_LENGTH = 128
MAX_LIST_VALUES = 50
ROLES = ("parent_key", "child_key")
# Built for `re.fullmatch`; never `$`, which also matches before a trailing newline.
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_GLOB_CHARS = frozenset("*?[")
_SCALAR_KEYS = ("table", "column")
_LIST_KEYS = ("classification", "tag", "logical_type", "role")
_INVALID = str(reasons.config.POLICY_SELECTOR_INVALID)
_UNKNOWN_CLASSIFICATION = str(reasons.config.POLICY_UNKNOWN_CLASSIFICATION)


def has_glob(value: str) -> bool:
    return any(ch in _GLOB_CHARS for ch in value)


def _refuse(code: str, key: str | None = None) -> PydanticCustomError:
    summary = reasons.lookup(code)[0].summary
    if key is None:
        return PydanticCustomError(code, summary)
    return PydanticCustomError(code, "{summary} Key: {key}.", {"summary": summary, "key": key})


def _text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_VALUE_LENGTH and value.isprintable()


def _values(value: Any) -> list[str] | None:
    """The string values of a scalar or list entry, or None when the shape is wrong."""
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not 0 < len(items) <= MAX_LIST_VALUES:
        return None
    return items if all(_text(item) for item in items) else None


class Selector(BaseModel):
    """Which mask fields a rule or prohibition applies to. At least one key is present."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    table: str | None = None
    column: str | None = None
    classification: str | list[str] | None = None
    tag: str | list[str] | None = None
    logical_type: str | list[str] | None = None
    role: str | list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def _closed_grammar(cls, raw: Any) -> Any:
        if not isinstance(raw, Mapping):
            raise _refuse(_INVALID)
        allowed = {*_SCALAR_KEYS, *_LIST_KEYS}
        if not raw or any(key not in allowed for key in raw):
            raise _refuse(_INVALID)
        for key in _SCALAR_KEYS:
            if key in raw and not _text(raw[key]):
                raise _refuse(_INVALID, key)
        for key in _LIST_KEYS:
            if key in raw and _values(raw[key]) is None:
                raise _refuse(_INVALID, key)
        for key, vocabulary in (("logical_type", LOGICAL_TYPES), ("role", ROLES)):
            if key in raw and any(v not in vocabulary for v in _values(raw[key]) or ()):
                raise _refuse(_INVALID, key)
        if "tag" in raw and not all(SLUG_RE.fullmatch(v) for v in _values(raw["tag"]) or ()):
            raise _refuse(_INVALID, "tag")
        if "classification" in raw:
            known = registered_detector_ids()
            if any(v not in known for v in _values(raw["classification"]) or ()):
                raise _refuse(_UNKNOWN_CLASSIFICATION)
        return dict(raw)

    def present_keys(self) -> frozenset[str]:
        return frozenset(k for k in (*_SCALAR_KEYS, *_LIST_KEYS) if getattr(self, k) is not None)


@dataclass(frozen=True)
class FieldFacts:
    """What a selector can see of one mask field: config names and labels, never data."""

    table: str
    column: str
    classification: str | None = None
    tags: tuple[str, ...] = ()
    logical_type: str | None = None
    roles: frozenset[str] = frozenset()


def _one_of(value: str | list[str], candidates: frozenset[str] | set[str]) -> bool:
    wanted = [value] if isinstance(value, str) else value
    return any(w in candidates for w in wanted)


def matches(selector: Selector, field: FieldFacts) -> bool:
    """True when every key present in `selector` matches `field`."""
    if selector.table is not None and not fnmatchcase(field.table, selector.table):
        return False
    if selector.column is not None and not fnmatchcase(field.column, selector.column):
        return False
    if selector.classification is not None:
        if field.classification is None or not _one_of(
            selector.classification, {field.classification}
        ):
            return False
    if selector.tag is not None and not _one_of(selector.tag, set(field.tags)):
        return False
    if selector.logical_type is not None:
        if field.logical_type is None or not _one_of(selector.logical_type, {field.logical_type}):
            return False
    return selector.role is None or _one_of(selector.role, field.roles)
