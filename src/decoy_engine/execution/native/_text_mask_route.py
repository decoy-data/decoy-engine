"""Route-shared text_mask adapter helpers: the fail-closed kill and the handler's warning (C6b-i).

Both native routes run the shipped `TextMaskHandler` per cell through `native_text_mask`
(`_kernels_scalar.py`), then surface the two things the per-cell mask does not build itself: the
fail-closed `StrategyError` the handler raises when a span cannot be FF1-encrypted and no
`sub_floor_span` policy is set, and the one aggregate sub-floor warning the handler builds OUTSIDE
`mask_cell`. Both are the handler's own builders, re-exported here for the unified route
(`physical/_shadow_coordinator`, `physical/_shadow_assembly`) and the chunked route
(`_chunk_masking`), so no route can drift from the oracle's error or warning.
"""

from __future__ import annotations

from decoy_engine.execution._errors import text_mask_fail_closed_error
from decoy_engine.execution._strategies._text_mask import text_mask_sub_floor_warning

__all__ = [
    "text_mask_fail_closed_error",
    "text_mask_sub_floor_warning",
]
