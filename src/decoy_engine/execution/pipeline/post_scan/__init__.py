"""The post-scan gate and its two helpers (`_distribution`, `_suite`).

Callers outside the package import the functions below from here, never from `_gate` or the other
underscore modules.
"""

from decoy_engine.execution.pipeline.post_scan._gate import (
    PostScanGate,
    active_gate,
    attach_cast_run,
    bind_gate,
    note_quarantined,
    publish_after_gate,
    settle,
    tee_reader,
)

__all__ = [
    "PostScanGate",
    "active_gate",
    "attach_cast_run",
    "bind_gate",
    "note_quarantined",
    "publish_after_gate",
    "settle",
    "tee_reader",
]
