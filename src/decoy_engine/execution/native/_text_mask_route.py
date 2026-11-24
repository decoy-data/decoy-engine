"""Route-shared text_mask adapter helpers: the fail-closed kill and the handler's warning (C6b-i).

Both native routes run the shipped `TextMaskHandler` per cell through `native_text_mask`
(`_kernels_scalar.py`), then surface the two things the per-cell mask does not build itself: the
fail-closed `StrategyError` the handler raises when a span cannot be FF1-encrypted and no
`sub_floor_span` policy is set, and the one aggregate sub-floor warning the handler builds OUTSIDE
`mask_cell`. These helpers live here so the unified route (`physical/_shadow_coordinator`,
`physical/_shadow_assembly`) and the chunked route (`_chunk_masking`) build the identical
`StrategyError` and `QualityWarning` and cannot drift from the oracle's.
"""

from __future__ import annotations

from decoy_engine import reasons
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._strategies._text_mask import text_mask_sub_floor_warning

__all__ = [
    "text_mask_fail_closed_error",
    "text_mask_sub_floor_warning",
]


def text_mask_fail_closed_error(column: str) -> StrategyError:
    """The `StrategyError` a sub-floor fpe span with no `sub_floor_span` policy maps to.

    Reproduces `TextMaskHandler.run`'s `except FpeUnencryptableError` branch exactly (code,
    strategy, message), so the native route raises the identical error the oracle handler does.
    A separate function so mutation testing can grade the code + message mapping on its own."""
    return StrategyError(
        code=reasons.runtime.FPE_UNENCRYPTABLE_DOMAIN,
        strategy="text_mask",
        message=(
            f"column {column!r}: a text span is outside the FPE domain of its charset. "
            "The engine fails closed rather than silently choose a sub_floor_span fallback."
        ),
    )
