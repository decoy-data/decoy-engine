"""Arrow kernels for `bucketize`: the range exit mask an integer width needs.

An integer-width bucket label is built from a float64 quotient, so a source value is only
representable when its magnitude stays below ``EXACT_INT_BOUND`` (2**53) and is finite. The
handler (and, after later slices, the array operator) asks this one function which positions
exit; neither keeps a copy of the rule.
"""

from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc

from decoy_engine.contracts.bucketize_width import EXACT_INT_BOUND

_BOUND = float(EXACT_INT_BOUND)  # 2**53 is exact in float64


def integer_width_exit_mask(values: pa.Array | pa.ChunkedArray) -> pa.Array:
    """Positions that cannot take an integer-width label, as a boolean array without nulls.

    B2: a finite value whose magnitude is at least ``EXACT_INT_BOUND``. B3: positive or negative
    infinity. An Arrow null and a valid NaN are never an exit: their predicates are false, so
    callers keep their own missingness rules.
    """
    # pyarrow ships no stubs for the compute functions it builds at import time.
    is_finite = pc.is_finite(values)  # type: ignore[attr-defined, unused-ignore]
    magnitude = pc.abs(values)  # type: ignore[attr-defined, unused-ignore]
    at_bound = pc.greater_equal(magnitude, _BOUND)  # type: ignore[attr-defined, unused-ignore]
    out_of_range = pc.and_(is_finite, at_bound)  # type: ignore[attr-defined, unused-ignore]
    infinite = pc.is_inf(values)  # type: ignore[attr-defined, unused-ignore]
    either = pc.or_(out_of_range, infinite)  # type: ignore[attr-defined, unused-ignore]
    mask = pc.fill_null(either, False)
    if isinstance(mask, pa.ChunkedArray):
        return mask.combine_chunks()
    return mask
