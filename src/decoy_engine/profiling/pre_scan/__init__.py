"""decoy_engine.profiling.pre_scan - the run-start pre-scan coverage verdict.

`evaluate_pre_scan` decides which flagged source columns a pipeline leaves unmasked. The module
holds names only, never a value. Public names are re-exported from `decoy_engine.profiling`.
"""

from decoy_engine.profiling.pre_scan._check import (
    PreScanBlockedError,
    PreScanFailedError,
    PreScanFinding,
    PreScanVerdict,
    PreScanWarning,
    evaluate_pre_scan,
)

__all__ = [
    "PreScanBlockedError",
    "PreScanFailedError",
    "PreScanFinding",
    "PreScanVerdict",
    "PreScanWarning",
    "evaluate_pre_scan",
]
