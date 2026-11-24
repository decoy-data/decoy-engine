"""Catalog of the ``runtime`` namespace: tombstones of identities that shipped and were removed.

A reason that shipped in a tagged release stays resolvable by its historic name so persisted
evidence can still be read: it is deprecated, never deleted.
"""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import UNRELEASED as UNRELEASED

__all__ = ["WHEN_PREDICATE_READS_MASKED_COLUMN"]

# A `when:` now reads original values on every route, so the native lanes no longer decline for
# reading a column an earlier node masks (WHEN-READS-SOURCE). No replacement: the decline is gone.
WHEN_PREDICATE_READS_MASKED_COLUMN = _catalog.runtime(
    "decoy_engine.execution.native._when_admission"
)(
    "when_predicate_reads_masked_column",
    "When predicate reads masked column.",
    deprecated_in=UNRELEASED,
)
