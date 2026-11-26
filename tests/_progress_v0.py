"""One projection of a progress event onto its version-0 keys, shared by the progress tests."""

from __future__ import annotations

from typing import Any

from decoy_engine import progress
from decoy_engine._progress_events import _LEGACY_FIELDS


def v0_projection(event: progress.ProgressEvent) -> dict[str, Any]:
    """The version-0 keys of `event_to_dict(event)`, in version-1 order."""
    legacy = _LEGACY_FIELDS[type(event)]
    return {k: v for k, v in progress.event_to_dict(event).items() if k in legacy}
