"""One versioned reader for a persisted residual-PII finding row.

`ResidualPIIFinding` is the writer; a report dict holds its fields. The reader takes the field
set, the required fields and the defaults from that dataclass, so a field added there is read
here without a second table. A v2 row predates the model detectors: it has none of
`V3_ADDED_FIELDS`, which read as their defaults, and its `match_rate` is always a number. A v3
row must carry every field. A failure names no field and no value.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple, get_args

from decoy_engine.detection.types import DETECTOR_ORDER
from decoy_engine.verification.postmask.types import (
    READABLE_SCHEMA_VERSIONS,
    SCHEMA_VERSION,
    ResidualPIIFinding,
    Severity,
)

__all__ = ["V3_ADDED_FIELDS", "VerdictRow", "project_for_verdict", "read_residual_finding"]

# The fields v3 added to the writer. A v2 row lacks them and reads their defaults.
V3_ADDED_FIELDS: tuple[str, ...] = ("source", "model", "band", "dismissed", "promoted")

_SEVERITIES = frozenset(get_args(Severity))
_FIELDS = {f.name: f for f in dataclasses.fields(ResidualPIIFinding)}


def _text(value: object) -> bool:
    return isinstance(value, str)


def _opt_text(value: object) -> bool:
    return value is None or isinstance(value, str)


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _opt_number(value: object) -> bool:
    return value is None or _number(value)


def _count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _flag(value: object) -> bool:
    return isinstance(value, bool)


def _model(value: object) -> bool:
    return value is None or (
        isinstance(value, Mapping)
        and isinstance(value.get("id"), str)
        and isinstance(value.get("version"), str)
    )


# One check per writer field; `tests/unit/verification` pins the keys to the dataclass fields.
FIELD_CHECKS: dict[str, Callable[[object], bool]] = {
    "table": _text,
    "column": _text,
    "detector_id": _text,
    "match_rate": _opt_number,
    "severity": lambda v: isinstance(v, str) and v in _SEVERITIES,
    "configured_strategy": _opt_text,
    "sample_match_count": _count,
    "message": _text,
    "source_identity_rate": _opt_number,
    "source_compared": _flag,
    "source": lambda v: isinstance(v, str) and v in DETECTOR_ORDER,
    "model": _model,
    "band": _opt_text,
    "dismissed": _flag,
    "promoted": _flag,
}


def read_residual_finding(raw: object, *, version: str) -> dict[str, Any] | None:
    """The finding row `raw` of a report at `version`, with defaults filled in.

    Returns None for a row that is not a mapping, lacks a required field, or has a field of the
    wrong type, and for an unreadable `version`. The caller names the refusal; nothing here holds a
    value.
    """
    if version not in READABLE_SCHEMA_VERSIONS or not isinstance(raw, Mapping):
        return None
    current = version == SCHEMA_VERSION
    row: dict[str, Any] = dict(raw)
    if not current and any(name in row for name in V3_ADDED_FIELDS):
        # A v2 report predates these fields; a row that carries one is not a v2 row.
        return None
    for name, field in _FIELDS.items():
        if name in row:
            continue
        if field.default is dataclasses.MISSING or current:
            return None
        row[name] = field.default
    if not all(FIELD_CHECKS[name](row[name]) for name in _FIELDS):
        return None
    if not current and row["match_rate"] is None:
        # `None` is the classifier finding's marker, which only v3 reports carry.
        return None
    return row


class VerdictRow(NamedTuple):
    """What the post-scan verdict reads of one report row. A field the row lacks reads as None."""

    severity: object
    source: object
    table: object
    column: object
    detector_id: object
    valid: bool = True  # False: the strict reader refuses the row (only judged when asked)


_ABSENT = VerdictRow(None, None, None, None, None, valid=False)


def project_for_verdict(raw: object, *, version: object, residual: bool = False) -> VerdictRow:
    """The verdict's view of one finding row: tolerant of a malformed row, exact about versions.

    The run gate must withhold outputs on a row the strict reader would refuse, so this never
    refuses: an absent or mistyped field reads as None and the caller blocks on it. It applies the
    same version rule as `read_residual_finding`: a v2 report predates `V3_ADDED_FIELDS`, so a
    v2 row's `source` is `regex` whatever the row says.

    With `residual=True` the row is also run through `read_residual_finding`, and `valid` says
    whether the strict reader accepts it: a row it refuses is not a finding the verdict can trust,
    so the caller blocks on it. The tolerant fields stay filled in, for the location text only.
    """
    if not isinstance(raw, Mapping):
        return _ABSENT
    v2 = version == "post-scan-integrity/v2"
    return VerdictRow(
        severity=raw.get("severity"),
        source=_FIELDS["source"].default if v2 else raw.get("source"),
        table=raw.get("table"),
        column=raw.get("column"),
        detector_id=raw.get("detector_id"),
        valid=(
            True
            if not residual
            else isinstance(version, str)
            and read_residual_finding(raw, version=version) is not None
        ),
    )
