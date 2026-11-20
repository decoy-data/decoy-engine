"""Catalog of the ``post_scan`` namespace, part 2 (declared key checks and the verdict)."""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import UNRELEASED, Outcome, Phase, ReasonCode, RetryClass

__all__ = [
    "DISMISS_REFUSED",
    "FINDING_BLOCKED",
    "FOREIGN_KEY_ORPHANS_INTRODUCED",
    "FOREIGN_KEY_ORPHANS_QUARANTINED",
    "GATE_DEFERRED_ROUTE",
    "KEY_COLUMN_MISSING",
    "KEY_TYPE_MISMATCH",
    "PRIMARY_KEY_DUPLICATES_INTRODUCED",
    "PRIMARY_KEY_NULLS_INTRODUCED",
    "REVIEW_CONFLICT",
    "REVIEW_INTEGRITY_OFF",
]

_d = _catalog.post_scan("decoy_engine.verification.postmask._keys")
_verdict = _catalog.post_scan("decoy_engine.verification.postmask._blocked")
_repair = RetryClass.CONFIGURATION_REPAIR

PRIMARY_KEY_DUPLICATES_INTRODUCED = _d(
    "primary_key_duplicates_introduced",
    "The run left more duplicate primary keys in the output than its inputs held.",
    retry=_repair,
    since="1.25.0",
)
PRIMARY_KEY_NULLS_INTRODUCED = _d(
    "primary_key_nulls_introduced",
    "The run left more null primary keys in the output than its inputs held.",
    retry=_repair,
    since="1.25.0",
)
FOREIGN_KEY_ORPHANS_INTRODUCED = _d(
    "foreign_key_orphans_introduced",
    "The run left more foreign keys without a parent in the output than its inputs held.",
    retry=_repair,
    since="1.25.0",
)
GATE_DEFERRED_ROUTE = _verdict(
    "gate_deferred_route",
    "The blocking post-scan gate cannot read this route yet, so the run was checked as before "
    "and not withheld.",
    retry=_repair,
    since="1.26.0",
)
FOREIGN_KEY_ORPHANS_QUARANTINED = _d(
    "foreign_key_orphans_quarantined",
    "Quarantine removed parent rows, so some child rows in the output have no parent. The run "
    "is not withheld for them.",
    retry=_repair,
    since="1.26.0",
)
KEY_COLUMN_MISSING = _d(
    "key_column_missing",
    "A declared relationship key column is absent from the output.",
    retry=_repair,
    since="1.25.0",
)
KEY_TYPE_MISMATCH = _d(
    "key_type_mismatch",
    "The output parent and child key columns of a relationship have types that cannot be compared.",
    retry=_repair,
    since="1.25.0",
)
FINDING_BLOCKED = _verdict(
    "finding_blocked",
    "A post-scan column check found a failing finding in the output, so the run is withheld.",
    retry=_repair,
    since="1.25.0",
)

# INIT-WIZARD E2: a post-scan review the engine cannot turn into config edits. The caller repairs
# its decisions; each names a table or column, never a value.
_review_declare = _catalog.post_scan("ReviewInputError")


def _review(code: str, summary: str) -> ReasonCode:
    return _review_declare(
        code,
        summary,
        phases=(Phase.CONFIGURATION,),
        outcome=Outcome.CONFIGURATION,
        retry=RetryClass.CONFIGURATION_REPAIR,
        since=UNRELEASED,
    )


DISMISS_REFUSED = _review(
    "dismiss_refused",
    "A finding that failed a mask check, or that came from source-identity evidence, cannot be "
    "dismissed.",
)
REVIEW_CONFLICT = _review(
    "review_conflict",
    "Decisions for findings on one column propose different entries.",
)
REVIEW_INTEGRITY_OFF = _review(
    "review_integrity_off",
    "A dismissal needs the post-scan integrity checks turned on in the config.",
)
