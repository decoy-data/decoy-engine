"""`scan-diff/v1`: the drift rules between two scans, and the value-free document that holds them.

One module owns the PII buckets, the per-table rules and the table matching, so the CLI's
`scan diff`, the CI drift check and the run-start drift check cannot disagree. The CLI callers
arrive in a later slice (F15 C1); until then the CLI's own copy of the rules is the one in use.

`diff_scan_tables` is a line-for-line port of the CLI's `compute_scan_diff`. It reads only
`fields[].name`, `fields[].pii_score`, `quasi_identifier_groups` and `reid_risk_score` and
validates nothing else, so a legacy profile table (int scores, no `scan_schema`) diffs as it
always did. `diff_scan_documents` matches tables by name and owns the set-level drift kinds.

Nothing here reads a cell value: a diff holds table and column names, scores, buckets,
quasi-identifier group names and a risk delta. The persisted form is `ScanDiffCore` (strict,
unknown members refused); `ScanDiffCoreRead` is derived from it with unknown members ignored, the
tag's minor accepted and an unknown drift kind refused, because a reader that dropped a kind a
later minor added could report a drifted diff as clean.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Final, Literal, get_args

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from decoy_engine.profiling.scan_set import PII_CANDIDATE_THRESHOLD, _relaxed

SCAN_DIFF_SCHEMA: Final = "scan-diff/v1"
PiiBucket = Literal["none", "low", "med", "high"]
TableDriftKind = Literal["pii_bucket_increased", "new_high_pii_field", "new_quasi_identifier_group"]
SetDriftKind = Literal["table_added", "no_common_table"]

_MED_THRESHOLD: Final = 0.3
_RANK: Final[dict[str, int]] = {"none": 0, "low": 1, "med": 2, "high": 3}
_TAG: Final = re.compile(re.escape(SCAN_DIFF_SCHEMA) + r"(\.[0-9]+)?")
_KINDS: Final = frozenset(get_args(TableDriftKind)) | frozenset(get_args(SetDriftKind))
_UNKNOWN_KIND: Final = "scan-diff document holds an unknown drift kind"


def pii_bucket(score: float | None) -> PiiBucket:
    """The bucket of a PII score: `high` is the engine's PII candidate threshold."""
    if score is None:
        return "none"
    if score >= PII_CANDIDATE_THRESHOLD:
        return "high"
    if score >= _MED_THRESHOLD:
        return "med"
    if score > 0:
        return "low"
    return "none"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldChange:
    """A field whose PII bucket moved between the two scans."""

    name: str
    old_score: float
    new_score: float
    old_bucket: PiiBucket
    new_bucket: PiiBucket

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "old_score": self.old_score,
            "new_score": self.new_score,
            "old_bucket": self.old_bucket,
            "new_bucket": self.new_bucket,
        }


@dataclass(frozen=True)
class FieldPresence:
    """A field present on one side only. `pii_score` is `None` when the scan holds none."""

    name: str
    pii_score: float | None
    pii_bucket: PiiBucket

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "pii_score": self.pii_score, "pii_bucket": self.pii_bucket}


@dataclass(frozen=True)
class TableDiff:
    """The categorised difference between two scans of one table (pure, no I/O)."""

    added_rows: tuple[FieldPresence, ...]
    removed_rows: tuple[FieldPresence, ...]
    pii_increased: tuple[FieldChange, ...]
    pii_decreased: tuple[FieldChange, ...]
    qi_added: tuple[tuple[str, ...], ...]
    qi_removed: tuple[tuple[str, ...], ...]
    risk_delta: float | None
    new_high_pii: tuple[FieldPresence, ...]
    table: str = ""

    @property
    def drift_kinds(self) -> tuple[TableDriftKind, ...]:
        kinds: list[TableDriftKind] = []
        if self.pii_increased:
            kinds.append("pii_bucket_increased")
        if self.new_high_pii:
            kinds.append("new_high_pii_field")
        if self.qi_added:
            kinds.append("new_quasi_identifier_group")
        return tuple(kinds)

    @property
    def drift(self) -> bool:
        return bool(self.drift_kinds)

    def as_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "drift": self.drift,
            "drift_kinds": list(self.drift_kinds),
            "added": [r.as_dict() for r in self.added_rows],
            "removed": [r.as_dict() for r in self.removed_rows],
            "pii_increased": [r.as_dict() for r in self.pii_increased],
            "pii_decreased": [r.as_dict() for r in self.pii_decreased],
            "qi_added": [list(g) for g in self.qi_added],
            "qi_removed": [list(g) for g in self.qi_removed],
            "risk_delta": self.risk_delta,
        }


@dataclass(frozen=True)
class ScanSetDiff:
    """Two scan sets compared: matched tables, tables on one side only and the set-level kinds."""

    baseline_engine_version: str
    current_engine_version: str
    detectors_changed: bool
    tables_added: tuple[str, ...]
    tables_removed: tuple[str, ...]
    tables: tuple[TableDiff, ...]
    no_common_table: bool

    @property
    def drift_kinds(self) -> tuple[SetDriftKind, ...]:
        kinds: list[SetDriftKind] = []
        if self.tables_added:
            kinds.append("table_added")
        if self.no_common_table:
            kinds.append("no_common_table")
        return tuple(kinds)

    @property
    def drift(self) -> bool:
        return bool(self.drift_kinds) or any(t.drift for t in self.tables)


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def _score(raw: object) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    raise TypeError("a scan field holds a pii_score that is not a number")


def _canon_qi(group: Sequence[object]) -> tuple[str, ...]:
    return tuple(sorted(str(x) for x in group))


def _fields(table: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {f["name"]: f for f in table.get("fields") or [] if f.get("name")}


def diff_scan_tables(
    old: Mapping[str, Any], new: Mapping[str, Any], *, table: str = ""
) -> TableDiff:
    """Categorise drift between two table dicts. Reads four members and validates nothing else."""
    old_fields, new_fields = _fields(old), _fields(new)
    increased: list[FieldChange] = []
    decreased: list[FieldChange] = []
    for name in sorted(set(old_fields) & set(new_fields)):
        old_score = _score(old_fields[name].get("pii_score")) or 0.0
        new_score = _score(new_fields[name].get("pii_score")) or 0.0
        old_bucket, new_bucket = pii_bucket(old_score), pii_bucket(new_score)
        change = FieldChange(name, old_score, new_score, old_bucket, new_bucket)
        if _RANK[new_bucket] > _RANK[old_bucket]:
            increased.append(change)
        elif _RANK[new_bucket] < _RANK[old_bucket]:
            decreased.append(change)

    old_qi = {_canon_qi(g) for g in old.get("quasi_identifier_groups") or []}
    new_qi = {_canon_qi(g) for g in new.get("quasi_identifier_groups") or []}

    old_risk, new_risk = old.get("reid_risk_score"), new.get("reid_risk_score")
    risk_delta: float | None = None
    if isinstance(old_risk, (int, float)) and isinstance(new_risk, (int, float)):
        risk_delta = float(new_risk) - float(old_risk)

    def presence(
        fields: Mapping[str, Mapping[str, Any]], names: Collection[str]
    ) -> list[FieldPresence]:
        rows = []
        for n in sorted(names):
            score = _score(fields[n].get("pii_score"))
            rows.append(FieldPresence(n, score, pii_bucket(score)))
        return rows

    added = presence(new_fields, set(new_fields) - set(old_fields))
    return TableDiff(
        added_rows=tuple(added),
        removed_rows=tuple(presence(old_fields, set(old_fields) - set(new_fields))),
        pii_increased=tuple(increased),
        pii_decreased=tuple(decreased),
        qi_added=tuple(sorted(new_qi - old_qi)),
        qi_removed=tuple(sorted(old_qi - new_qi)),
        risk_delta=risk_delta,
        new_high_pii=tuple(r for r in added if r.pii_bucket == "high"),
        table=table,
    )


def _by_name(document: Mapping[str, Any], selection: Collection[str] | None) -> dict[str, Any]:
    named: dict[str, Any] = {}
    for t in document.get("tables") or []:
        name = t["name"]
        if selection is not None and name not in selection:
            continue
        if name in named:
            raise ValueError("a scan document repeats a table name")
        named[name] = t
    return named


def diff_scan_documents(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    tables: Collection[str] | None = None,
) -> ScanSetDiff:
    """Compare two scan-set documents. Tables match by name.

    A current table the baseline lacks is `table_added` drift; a baseline table the current set
    lacks is reported, not drift. When no table matches at all the one drift kind is
    `no_common_table` and `tables_added` stays empty. `tables` limits both sides to those names.
    A change of engine version or detector runs sets `detectors_changed`, which is not drift.
    """
    base, cur = _by_name(baseline, tables), _by_name(current, tables)
    common = sorted(set(base) & set(cur))
    no_common = not common and bool(base or cur)
    base_version = str(baseline.get("engine_version") or "")
    cur_version = str(current.get("engine_version") or "")
    return ScanSetDiff(
        baseline_engine_version=base_version,
        current_engine_version=cur_version,
        detectors_changed=base_version != cur_version
        or (baseline.get("detectors") or []) != (current.get("detectors") or []),
        tables_added=() if no_common else tuple(sorted(set(cur) - set(base))),
        tables_removed=tuple(sorted(set(base) - set(cur))),
        tables=tuple(diff_scan_tables(base[n], cur[n], table=n) for n in common),
        no_common_table=no_common,
    )


# ---------------------------------------------------------------------------
# The persisted document
# ---------------------------------------------------------------------------


def _known_kind(value: object) -> object:
    if isinstance(value, str) and value not in _KINDS:
        raise PydanticCustomError("scan_diff_unknown_kind", _UNKNOWN_KIND)
    return value


class _Core(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


_Score = Annotated[float, Field(allow_inf_nan=False)]
_TableKind = Annotated[TableDriftKind, BeforeValidator(_known_kind)]
_SetKind = Annotated[SetDriftKind, BeforeValidator(_known_kind)]


class FieldPresenceCore(_Core):
    name: str
    pii_score: _Score | None
    pii_bucket: PiiBucket


class FieldChangeCore(_Core):
    name: str
    old_score: _Score
    new_score: _Score
    old_bucket: PiiBucket
    new_bucket: PiiBucket


class TableDiffCore(_Core):
    table: str
    drift: bool
    drift_kinds: list[_TableKind]
    added: list[FieldPresenceCore]
    removed: list[FieldPresenceCore]
    pii_increased: list[FieldChangeCore]
    pii_decreased: list[FieldChangeCore]
    qi_added: list[list[str]]
    qi_removed: list[list[str]]
    risk_delta: _Score | None


class ScanDiffCore(_Core):
    scan_diff_schema: Literal["scan-diff/v1"]
    baseline_engine_version: str
    current_engine_version: str
    detectors_changed: bool
    drift: bool
    drift_kinds: list[_SetKind]
    no_common_table: bool
    tables_added: list[str]
    tables_removed: list[str]
    tables: list[TableDiffCore]


class ScanDiffCoreRead(_relaxed(ScanDiffCore)):  # type: ignore[misc]
    """`ScanDiffCore` with unknown members ignored and `scan-diff/v1.<minor>` accepted."""

    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("scan_diff_schema", mode="before")
    @classmethod
    def _minor(cls, value: object) -> object:
        return SCAN_DIFF_SCHEMA if isinstance(value, str) and _TAG.fullmatch(value) else value


def scan_diff_to_dict(diff: ScanSetDiff) -> dict[str, Any]:
    """The `scan-diff/v1` document of `diff`, checked by the strict write model."""
    document = {
        "scan_diff_schema": SCAN_DIFF_SCHEMA,
        "baseline_engine_version": diff.baseline_engine_version,
        "current_engine_version": diff.current_engine_version,
        "detectors_changed": diff.detectors_changed,
        "drift": diff.drift,
        "drift_kinds": list(diff.drift_kinds),
        "no_common_table": diff.no_common_table,
        "tables_added": list(diff.tables_added),
        "tables_removed": list(diff.tables_removed),
        "tables": [t.as_dict() for t in diff.tables],
    }
    dumped: dict[str, Any] = ScanDiffCore.model_validate(document).model_dump()
    return dumped
