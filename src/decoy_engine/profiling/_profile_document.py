"""The plain profile writer: `profile_document` and `redact_profile_dict`.

`ColumnProfile.to_dict()` stays the raw form (the platform persists and rebuilds it). Anything
that writes a profile for a person to read or commit goes through `profile_document`, and
anything that reads a saved profile back for display goes through `redact_profile_dict`. Which
fields hold cell values, and how a value is removed, come from the one registry in
`_value_redaction.py`; this module only walks a document and applies it, as `_snapshot_values.py`
does for the fit snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from decoy_engine.profiling._value_redaction import (
    REDACTED,
    _apply,
    _redact_field,
    _sensitive_entries,
    _shape_keep,
    _shapes,
    stamp_value_policy,
)
from decoy_engine.profiling.types import ColumnProfile


def _detached(root: Mapping[str, Any]) -> dict[str, Any]:
    """Copy of a JSON object without recursion, so a deeply nested file cannot crash the redactor."""
    out: dict[str, Any] = {}
    stack: list[tuple[Any, Any]] = [(root, out)]
    while stack:
        src, dst = stack.pop()
        for key, value in src.items() if isinstance(src, Mapping) else enumerate(src):
            child = value
            if isinstance(value, (Mapping, list, tuple)):
                child = {} if isinstance(value, Mapping) else []
                stack.append((value, child))
            if isinstance(dst, dict):
                dst[key] = child
            else:
                dst.append(child)
    return out


def redact_profile_dict(doc: Mapping[str, Any], *, include_values: bool = False) -> dict[str, Any]:
    """A copy of a profile document with the value-sensitive columns' cell values removed.

    Never mutates `doc` and never trusts its `value_policy` marker, so a second pass is a
    no-op and a forged or legacy file is still redacted. A key no profile type declares, or a
    value-free key holding a value of the wrong type, is replaced at the root and inside a
    value-sensitive column, since a newer or hand-edited file may keep a cell there. `include_values=True` keeps every value and adds a `raw`
    policy only when the document has none.
    """
    if not isinstance(doc, Mapping):
        raise TypeError(f"a profile document is a JSON object, not {type(doc).__name__}")
    if type(include_values) is not bool:
        raise TypeError(f"include_values must be a bool, not {type(include_values).__name__}")
    out = _detached(doc)
    if not include_values:
        # The two marker keys are rewritten below, so their loaded values never survive.
        _apply(out, {}, _shape_keep(_shapes(ColumnProfile)))
    fields: Any = out.get("fields")
    entries = _sensitive_entries(fields)
    if not include_values:
        for index, _ in entries:
            if index is None:
                out["fields"] = REDACTED
            else:
                _redact_field(fields, index)
    return stamp_value_policy(out, [name for _, name in entries], include_values=include_values)


def profile_document(profile: ColumnProfile, *, include_values: bool = False) -> dict[str, Any]:
    """The JSON document to write for a profile: `to_dict()` passed through the redactor."""
    return redact_profile_dict(profile.to_dict(), include_values=include_values)
