"""Catalog of the ``route`` namespace: tombstones of identities that shipped and were renamed.

A reason that shipped in a tagged release stays resolvable by its historic name so persisted
evidence can still be read: it is deprecated, never deleted, and points at its replacement.
"""

from __future__ import annotations

from decoy_engine.reasons import _catalog

__all__ = ["POST_SCAN_INTEGRITY_REQUESTED"]

# Regex-only integrity no longer keeps a run resident; only a model ask does.
POST_SCAN_INTEGRITY_REQUESTED = _catalog.route("decoy_engine.execution._pipeline_routing")(
    "post_scan_integrity_requested",
    "The Post-scan integrity checks need the full frame resident.",
    deprecated_in="1.27.0",
    replaced_by=("route", "post_scan_models_resident"),
)
