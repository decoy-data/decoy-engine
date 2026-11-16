"""``plan_resume``: which stored tables a resumed run keeps and which it runs again.

Pure and value-free. The caller reads and verifies the store, then hands in the stored
``RunRecord``, the current ``RunFingerprint`` and table entries, and one ``TableCheck`` per
table. A run that does not match what the store was written for is refused, never partly kept.
Refusals name a field (``tables``, ``bindings`` or a fingerprint field), never a value or a table
name. ``ResumeRefusedError`` is raised outside any handler, so it carries no exception context.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from typing import Final

from decoy_engine import reasons
from decoy_engine.delivery.resume._fingerprint import RunFingerprint
from decoy_engine.delivery.resume._records import RunRecord, TableEntry
from decoy_engine.errors import DecoyError
from decoy_engine.reasons.decoy import (
    RESUME_CHECKPOINT_INVALID,
    RESUME_FINGERPRINT_CHANGED,
    RESUME_SOURCE_CHANGED,
)

__all__ = ["ResumePlan", "ResumeRefusedError", "ResumeWarning", "TableCheck", "plan_resume"]

_FIELD = re.compile(r"[a-z][a-z_]{0,31}")
_FIELD_TABLES: Final = "tables"
_FIELD_BINDINGS: Final = "bindings"


class ResumeRefusedError(DecoyError):
    """The run cannot resume. ``code`` is a registered ``decoy`` reason and ``field`` names what
    differed; ``str()`` is a fixed summary, the code and the field, never a value."""

    def __init__(self, code: str, field: str | None = None) -> None:
        # Registry membership, not character shape: a well-formed string is not a known reason.
        if reasons.find("decoy", code) is None:
            raise ValueError("invalid reason code")
        if field is not None and _FIELD.fullmatch(field) is None:
            raise ValueError("invalid field")
        # `args` is what pickling rebuilds the error from.
        super().__init__(str(code), field)
        self.code = str(code)
        self.field = field

    def __str__(self) -> str:
        where = "" if self.field is None else f" ({self.field})"
        return f"resume refused: {self.code}{where}"


@dataclass(frozen=True)
class TableCheck:
    """What the caller verified for one table: its record read cleanly, its kept file is still
    there with the recorded digest, its source file still has the recorded digest, and the
    placed path the record names is the path the current plan would place it at."""

    record_valid: bool
    artifact_ok: bool
    source_ok: bool
    path_ok: bool


@dataclass(frozen=True)
class ResumeWarning:
    """A table that was kept before but no longer verifies, so it runs again."""

    code: str
    index: int


@dataclass(frozen=True)
class ResumePlan:
    """``keep`` and ``rerun`` partition the tables by index, in order. ``rerun == ()`` means every
    table is kept and the run goes straight to delivery."""

    keep: tuple[int, ...]
    rerun: tuple[int, ...]
    warnings: tuple[ResumeWarning, ...]


# No record read for the table: it runs.
_NO_RECORD: Final = TableCheck(
    record_valid=False, artifact_ok=False, source_ok=False, path_ok=False
)


def plan_resume(
    stored: RunRecord,
    current: RunFingerprint,
    tables: Sequence[TableEntry],
    checks: Mapping[int, TableCheck],
) -> ResumePlan:
    """Decide keep and rerun for ``tables`` (the current chunked tables, in order).

    ``checks`` maps a table index to its ``TableCheck``; a table with no entry has no record.
    """
    for spec in fields(RunFingerprint):
        if getattr(stored.fingerprint, spec.name) != getattr(current, spec.name):
            raise ResumeRefusedError(RESUME_FINGERPRINT_CHANGED, spec.name)
    # Order counts: a reordered set is a different run, so compare the sequences.
    if [(t.index, t.name_digest) for t in stored.tables] != [
        (t.index, t.name_digest) for t in tables
    ]:
        raise ResumeRefusedError(RESUME_FINGERPRINT_CHANGED, _FIELD_TABLES)
    if [t.binding_digest for t in stored.tables] != [t.binding_digest for t in tables]:
        raise ResumeRefusedError(RESUME_FINGERPRINT_CHANGED, _FIELD_BINDINGS)
    # A kept file whose placed path moved would land somewhere the current plan does not: a
    # binding difference, refused before any table is judged.
    for entry in tables:
        check = checks.get(entry.index, _NO_RECORD)
        if check.record_valid and not check.path_ok:
            raise ResumeRefusedError(RESUME_FINGERPRINT_CHANGED, _FIELD_BINDINGS)
    keep: list[int] = []
    rerun: list[int] = []
    warnings: list[ResumeWarning] = []
    for entry in tables:
        check = checks.get(entry.index, _NO_RECORD)
        if not check.record_valid:
            rerun.append(entry.index)
        elif not check.source_ok:
            # A kept table would come from another snapshot than the one the rerun tables read.
            raise ResumeRefusedError(RESUME_SOURCE_CHANGED)
        elif not check.artifact_ok:
            rerun.append(entry.index)
            warnings.append(ResumeWarning(str(RESUME_CHECKPOINT_INVALID), entry.index))
        else:
            keep.append(entry.index)
    return ResumePlan(tuple(keep), tuple(rerun), tuple(warnings))
