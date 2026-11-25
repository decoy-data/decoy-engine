"""Catalog of the ``route`` namespace: tombstones of identities that shipped and were renamed.

A reason that shipped in a tagged release stays resolvable by its historic name so persisted
evidence can still be read: it is deprecated, never deleted, and points at its replacement.
"""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import UNRELEASED as UNRELEASED

__all__ = ["POST_SCAN_INTEGRITY_REQUESTED", "WHEN_READS_MASKED_COLUMN"]

# Regex-only integrity no longer keeps a run resident; only a model ask does.
POST_SCAN_INTEGRITY_REQUESTED = _catalog.route("decoy_engine.execution._pipeline_routing")(
    "post_scan_integrity_requested",
    "The Post-scan integrity checks need the full frame resident.",
    deprecated_in="1.27.0",
    replaced_by=("route", "post_scan_models_resident"),
)

# A `when:` now reads original values on every route, so no table declines for reading a column an
# earlier node masks (WHEN-READS-SOURCE). The registry has no removal form, so the
# tombstone points at the one live code for a `when:` that asks for a masked value: the `masked.`
# form is the only way to ask now, and V1 rejects it with `when_masked_reference_unsupported`.
# The old decline itself is never produced again.
WHEN_READS_MASKED_COLUMN = _catalog.route("RouteDeclineCode")(
    "when_reads_masked_column",
    "When reads masked column.",
    deprecated_in=UNRELEASED,
    replaced_by=("runtime", "when_masked_reference_unsupported"),
)
