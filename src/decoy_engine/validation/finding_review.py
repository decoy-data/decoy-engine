"""Post-scan review: turn a report's findings and the user's decisions into config edits.

`finding_edits` reads a `post-scan-integrity` report and one decision per finding. It returns the
edits a front end applies to the pipeline file; it never writes one. A `confirm` or `edit` becomes
at most one replacement entry per column. A `reject` becomes a `post_scan.dismissed` entry bound to
the column's final strategy, so it stops applying when that strategy changes. Only a `warning`
that came from a detector match can be dismissed (a promoted NER finding too); a mask check that
failed, or a finding raised from source-identity evidence, never can.

The result does not depend on the order of the decisions. Every refusal is a `ReviewInputError`
subclass that names a table or column, never a value (see `starter_review`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, get_args

from decoy_engine import reasons
from decoy_engine.detection.types import DETECTOR_ORDER, DetectorSource, ModelRef
from decoy_engine.profiling import declared_key_namespaces, detector_entry
from decoy_engine.validation.starter_review import (
    ReviewDecision,
    ReviewDuplicateError,
    ReviewEntryError,
    ReviewInputError,
    ReviewStaleError,
    ReviewUnknownColumnError,
    ReviewVerdict,
    _edited_entry,
    _index_of,
    column_entry,
    pin_key_entry,
)
from decoy_engine.verification.postmask import (
    READABLE_SCHEMA_VERSIONS,
    SCHEMA_VERSION,
    ResidualPIIFinding,
    Severity,
    is_source_identity_finding,
)

__all__ = [
    "ConfigEdit",
    "FindingDecision",
    "ReviewConflictError",
    "ReviewDismissRefusedError",
    "finding_edits",
]

_TEXT_REDACT = "text_redact"
_Identity = tuple[str, str, str, str, str | None, str | None]


class ReviewDismissRefusedError(ReviewInputError):
    """The finding cannot be dismissed: a failed mask check or source-identity evidence."""

    code = reasons.post_scan.DISMISS_REFUSED


class ReviewConflictError(ReviewInputError):
    """Decisions for findings on one column propose different entries."""

    code = reasons.post_scan.REVIEW_CONFLICT


@dataclass(frozen=True)
class FindingDecision:
    """One finding's verdict. `entry` is for `EDIT` only: a strategy and its options."""

    table: str
    column: str
    detector_id: str
    source: DetectorSource
    model: ModelRef | None
    verdict: ReviewVerdict
    entry: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ConfigEdit:
    """What to change in the pipeline file; the caller decides how to write it.

    `replace` swaps the node at `path`; `append` adds `value` to the list at `path`;
    `append_block` adds the mapping `value` as a new block at `path`. `note` is the REVIEW note
    for a replaced or appended column entry (None: no note).
    """

    path: tuple[str | int, ...]
    op: Literal["replace", "append", "append_block"]
    value: Mapping[str, Any]
    note: str | None = None


def finding_edits(
    config: Mapping[str, Any], report: Mapping[str, Any], decisions: Sequence[FindingDecision]
) -> tuple[ConfigEdit, ...]:
    """The config edits that carry out `decisions` over the findings of `report`."""
    rows = _report_rows(report)
    keys = declared_key_namespaces(config.get("relationships") or ())
    tables = {t.get("name"): t for t in config.get("tables") or () if isinstance(t, Mapping)}
    groups: dict[tuple[str, str], list[tuple[FindingDecision, Mapping[str, Any]]]] = {}
    seen: set[_Identity] = set()
    for decision in decisions:
        identity = _identity(decision)
        row = rows.get(identity)
        if row is None or tables.get(decision.table) is None:
            raise ReviewUnknownColumnError(
                "the decision names a finding the report does not hold",
                table=decision.table,
                column=decision.column,
            )
        if identity in seen:
            raise ReviewDuplicateError(
                "two decisions name the same finding", table=decision.table, column=decision.column
            )
        seen.add(identity)
        if (
            not isinstance(decision.verdict, ReviewVerdict)
            or decision.verdict is ReviewVerdict.DROP
        ):
            raise ReviewEntryError(
                "the verdict does not apply to a finding",
                table=decision.table,
                column=decision.column,
            )
        groups.setdefault((decision.table, decision.column), []).append((decision, row))
    replacements: list[tuple[int, int, ConfigEdit]] = []
    dismissals: list[dict[str, Any]] = []
    existing = _existing_dismissals(config)
    for (table_name, column), group in sorted(groups.items()):
        table = tables[table_name]
        index = _index_of(table, column)
        current = None if index is None else table["columns"][index]
        key = keys.get((table_name, column))
        final = _final_entry(group, key)
        if final is not None and final != current:
            table_index = list(config["tables"]).index(table)
            path = ("tables", table_index, "columns") + (() if index is None else (index,))
            op: Literal["replace", "append"] = "append" if index is None else "replace"
            replacements.append(
                (table_index, -1 if index is None else index, ConfigEdit(path, op, final))
            )
        now = (current or {}).get("strategy")
        strategy = final["strategy"] if final is not None else now
        for decision, row in group:
            if decision.verdict is not ReviewVerdict.REJECT:
                continue
            if strategy == now and row.get("configured_strategy") != now:
                # The finding was raised under another strategy than the column has now, and this
                # review does not change it: a dismissal would bind a strategy nobody reviewed.
                raise ReviewStaleError(
                    "the finding was raised under a strategy the column no longer has",
                    table=decision.table,
                    column=decision.column,
                )
            dismissal = _dismissal(decision, row, strategy)
            if dismissal is not None and dismissal not in existing and dismissal not in dismissals:
                dismissals.append(dismissal)
    edits = [edit for _, _, edit in sorted(replacements, key=lambda r: r[:2])]
    dismissals.sort(key=lambda d: tuple(str(d[k]) for k in sorted(d)))
    return tuple(edits) + _dismissal_edits(config, dismissals)


def _identity(decision: FindingDecision) -> _Identity:
    model = decision.model
    return (
        decision.table,
        decision.column,
        decision.source,
        decision.detector_id,
        None if model is None else model.id,
        None if model is None else model.version,
    )


def _report_rows(report: Mapping[str, Any]) -> dict[_Identity, Mapping[str, Any]]:
    if not isinstance(report, Mapping):
        raise ReviewEntryError("the report is not a mapping")
    version = report.get("schema_version")
    # A str test first: an unhashable value must not reach the set lookup.
    if not isinstance(version, str) or version not in READABLE_SCHEMA_VERSIONS:
        raise ReviewEntryError("the report has an unreadable schema version")
    listed = report.get("residual_pii")
    if listed is None:
        listed = ()
    if not isinstance(listed, Sequence) or isinstance(listed, str | bytes):
        raise _malformed()
    rows: dict[_Identity, Mapping[str, Any]] = {}
    for raw in listed:
        row = _read_finding(raw, current=version == SCHEMA_VERSION)
        model = row["model"]
        identity = (
            row["table"],
            row["column"],
            row["source"],
            row["detector_id"],
            None if model is None else model["id"],
            None if model is None else model["version"],
        )
        rows[identity] = row
    return rows


# The finding fields by type, as `ResidualPIIFinding` writes them into a v3 report. A v2 row
# predates the model detectors: it has none of `_V3_ONLY`, which read as a regex finding with no
# model, not dismissed and not promoted. A v3 row must carry every field.
_V3_ONLY = ("source", "model", "band", "dismissed", "promoted")
_V3_DEFAULTS: dict[str, Any] = {
    "source": "regex",
    "model": None,
    "band": None,
    "dismissed": False,
    "promoted": False,
}
_OPTIONAL_V2 = {
    "configured_strategy": None,
    "sample_match_count": 0,
    "message": "",
    "source_identity_rate": None,
    "source_compared": False,
}
_SEVERITIES = frozenset(get_args(Severity))


def _read_finding(raw: object, *, current: bool) -> dict[str, Any]:
    """One finding row, checked against the whole versioned shape, or a value-free refusal.

    Every field the review reads is typed here, so nothing downstream can fail on a bad value.
    """
    if not isinstance(raw, Mapping):
        raise _malformed()
    row: dict[str, Any] = dict(raw)
    required = ("table", "column", "detector_id", "severity", "match_rate")
    if current:
        required += tuple(_OPTIONAL_V2) + _V3_ONLY
    if any(name not in row for name in required):
        raise _malformed()
    for name, default in {**_OPTIONAL_V2, **({} if current else _V3_DEFAULTS)}.items():
        row.setdefault(name, default)
    model = row["model"]
    ok = (
        all(isinstance(row[n], str) for n in ("table", "column", "detector_id"))
        and isinstance(row["message"], str)
        and row["severity"] in _SEVERITIES
        and row["source"] in DETECTOR_ORDER
        and (row["match_rate"] is None or _is_number(row["match_rate"]))
        and (row["configured_strategy"] is None or isinstance(row["configured_strategy"], str))
        and _is_int(row["sample_match_count"])
        and (row["source_identity_rate"] is None or _is_number(row["source_identity_rate"]))
        and isinstance(row["source_compared"], bool)
        and (row["band"] is None or isinstance(row["band"], str))
        and isinstance(row["dismissed"], bool)
        and isinstance(row["promoted"], bool)
        and (
            model is None
            or (
                isinstance(model, Mapping)
                and isinstance(model.get("id"), str)
                and isinstance(model.get("version"), str)
            )
        )
    )
    if not ok:
        raise _malformed()
    return row


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _malformed() -> ReviewEntryError:
    return ReviewEntryError("the report holds a malformed finding")


def _final_entry(
    group: Sequence[tuple[FindingDecision, Mapping[str, Any]]], key: tuple[str, bool] | None
) -> dict[str, Any] | None:
    """The one entry the column's `confirm` and `edit` decisions agree on, or None."""
    proposed: list[dict[str, Any]] = []
    for decision, _row in group:
        if decision.verdict is ReviewVerdict.CONFIRM:
            entry = _confirm_entry(decision)
        elif decision.verdict is ReviewVerdict.EDIT:
            as_review = ReviewDecision(
                decision.table, decision.column, ReviewVerdict.EDIT, entry=decision.entry
            )
            entry = _edited_entry(as_review, None if key is None else key[0])
        else:
            continue
        if key is not None:
            entry = pin_key_entry(decision.table, decision.column, entry, key[0])
        if entry not in proposed:
            proposed.append(entry)
    if len(proposed) > 1:
        first = group[0][0]
        raise ReviewConflictError(
            "decisions for one column propose different entries",
            table=first.table,
            column=first.column,
        )
    return proposed[0] if proposed else None


def _confirm_entry(decision: FindingDecision) -> dict[str, Any]:
    if decision.source == "ner":
        options: dict[str, Any] = {"ner_entities": [decision.detector_id]}
        if decision.model is not None:
            options["ner_model"] = decision.model.id
        return column_entry(_TEXT_REDACT, decision.column, options=options)
    entry = detector_entry(decision.detector_id, decision.column)
    if entry is None:
        raise ReviewEntryError(
            "the detector has no default strategy to confirm",
            table=decision.table,
            column=decision.column,
        )
    return entry


def _dismissal(
    decision: FindingDecision, row: Mapping[str, Any], strategy: str | None
) -> dict[str, Any] | None:
    """The `post_scan.dismissed` entry for a reject, or None when the finding is already dismissed."""
    if row.get("dismissed") is True:
        return None
    severity = row["severity"]
    probe = ResidualPIIFinding(
        table=decision.table,
        column=decision.column,
        detector_id=decision.detector_id,
        match_rate=None,
        severity=severity,
        source=decision.source,
        source_identity_rate=row.get("source_identity_rate"),
    )
    promoted = decision.source == "ner" and row.get("promoted") is True
    if not (severity == "warning" or promoted) or is_source_identity_finding(probe):
        raise ReviewDismissRefusedError(
            "this finding cannot be dismissed", table=decision.table, column=decision.column
        )
    model = decision.model
    return {
        "table": decision.table,
        "column": decision.column,
        "detector_id": decision.detector_id,
        "source": decision.source,
        "model_id": None if model is None else model.id,
        "model_version": None if model is None else model.version,
        "strategy": strategy,
    }


def _existing_dismissals(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    block = config.get("post_scan")
    listed = block.get("dismissed") if isinstance(block, Mapping) else None
    fields = ("table", "column", "detector_id", "source", "model_id", "model_version", "strategy")
    return [{f: d.get(f) for f in fields} for d in (listed or ()) if isinstance(d, Mapping)]


def _dismissal_edits(
    config: Mapping[str, Any], dismissals: list[dict[str, Any]]
) -> tuple[ConfigEdit, ...]:
    if not dismissals:
        return ()
    if isinstance(config.get("post_scan"), Mapping):
        return tuple(ConfigEdit(("post_scan", "dismissed"), "append", d) for d in dismissals)
    return (ConfigEdit(("post_scan",), "append_block", {"dismissed": dismissals}),)
