"""Native deterministic date_shift, reusing `derive_index_batch`.

The oracle (`execution/_strategies/_date_shift.py`) shifts each parseable date
by a keyed per-value offset in `[min_days, max_days]`:
`min_days + (int.from_bytes(derive(mask_key, namespace, canon(value))[:8],
"big") % range_size)`. With no `group_by` the digest input is the source value
itself, so the offset is exactly `derive_index_batch(source, pool_size=
range_size) + min_days`: the compiled kernel computes that reduction
byte-for-byte (KAT-pinned, `_index_ext.py`; canonicalization shared via
`generation.pool._canonicalize._canonicalize_source`). This operator therefore
reuses the audited HKDF-SHA256 -> HMAC envelope (`decoy-engine-native/src/
derive.rs`) and adds NO new Rust or crypto.

Established methodology: per-value keyed date shifting is the standard
de-identification technique (HIPAA Safe Harbor date-shift guidance: a
consistent keyed offset preserves intervals for the same source value). Parse
and format are delegated to pandas, the oracle's own authority, following the
`_bucket_perturb_ext.py` template: Arrow's datetime parser/formatter differs
from pandas on permissive input and unsupported directives, so the post-step
calls the SAME `pd.to_datetime(errors="coerce")`, `+ pd.to_timedelta(unit="D")`
and `.dt.strftime` sequence the oracle runs.

Row errors: a NON-null value that fails to parse under the explicit format is a
`format_error`. The oracle leaves the original value in its frame and records a
`RowError`; this operator does the same and returns the BATCH-LOCAL positions.
Dropping them would let an unparseable raw value reach the main output with the
job succeeding, so every caller must route them. The two callers differ on what
the positions mean afterwards:

- the full-frame coordinator (`_shadow_coordinator`) passes the whole column as
  one batch and rebases the positions to table-global indices;
- the chunked native route (`_chunk_masking._mask_date_shift`) passes one chunk
  and keeps the positions chunk-local, because the oracle chunked leg reports
  `row_index` within its chunk and never adds the chunk's global offset.

Typed sources (DATE-SHIFT-TYPED S1): a `date32` column whose plan shape is `DATE` keys each row
on its ISO date (`canonicalize_typed_array`, the same bytes `_canonicalize_source` builds) and
adds the days with `shift_typed_days`, the arithmetic the oracle calls too. The output stays
`date32`; a row outside years 1 to 9999, before or after the shift, is a `format_error` that keeps
its source value.

v1 text scope: STRING source, EXPLICIT `date_format` (no `%z`/`%Z`), no `group_by`,
integer `min_days`/`max_days` inside the pandas Timedelta range, on the full-frame
route and, per chunk, on the chunked route. Every other shape declines to the
oracle at admission (`date_shift_config_rejection`).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc

from decoy_engine import reasons
from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.execution._operator_registry import OPERATORS
from decoy_engine.execution._row_errors import RowError
from decoy_engine.generation.pool import GenerationError
from decoy_engine.generation.pool._canonicalize import canonicalize_typed_array
from decoy_engine.transforms.bucket_perturb import FORMAT_ERROR_REASON as _BUCKET_REASON
from decoy_engine.transforms.date_shift import order_window, shift_typed_days

if TYPE_CHECKING:
    from decoy_engine.execution.native._index_ext import IndexDerivationKernel

# The oracle's `reason` string for a parse failure, reproduced verbatim so the
# native and oracle `RowError` records compare equal.
FORMAT_ERROR_REASON = "value is not a parseable date under date_shift"

BUCKET_PERTURB_OPERATOR_ID = OPERATORS["bucket_perturb"].operator_id
DATE_SHIFT_OPERATOR_ID = OPERATORS["date_shift"].operator_id


def format_error_reason(operator_id: str) -> str:
    """The one choice of `format_error` reason text: bucket_perturb's, else date_shift's."""
    return _BUCKET_REASON if operator_id == BUCKET_PERTURB_OPERATOR_ID else FORMAT_ERROR_REASON


def format_error_row_errors(
    column: str, positions: Iterable[int], operator_id: str
) -> list[RowError]:
    """The one builder of `format_error` RowErrors for the native routes (sequential, chunked).

    One RowError per unparseable cell position, the reason picked by `format_error_reason`. No
    cell value is part of a record."""
    reason = format_error_reason(operator_id)
    return [
        RowError(column=column, row_index=int(pos), trigger="format_error", reason=reason)
        for pos in positions
    ]


def resolve_shift_range(min_days: int, max_days: int) -> tuple[int, int]:
    """`(min_days, range_size)` for bounds `shift_window` resolved: the offset draw covers
    `range_size` values from `min_days`. A reversed pair is ordered, so a caller that hands the
    kernel raw bounds still gets the oracle's window."""
    low, high = order_window(min_days, max_days)
    return low, high - low + 1


def _derive_offsets(
    values: pa.Array,
    *,
    range_size: int,
    mask_key: bytes,
    namespace: str,
    index_kernel: IndexDerivationKernel,
    native_threads: int | None,
) -> np.ndarray:
    """The keyed `[0, range_size)` draw per (non-null, parseable) row, with the
    same runtime invariants `native_bucket_perturb` applies to the kernel's own
    result, so a malformed compiled kernel fails here, coded and fail-closed."""
    try:
        idx = index_kernel.derive_index_batch(
            values,
            mask_key=mask_key,
            namespace=namespace,
            pool_size=range_size,
            native_threads=native_threads,
        )
        # Type check FIRST so a non-`pa.Array` result cannot leak an uncoded
        # AttributeError from the checks below.
        if not isinstance(idx, pa.Array) or idx.type != pa.uint64():
            got = idx.type if isinstance(idx, pa.Array) else type(idx).__name__
            raise GenerationError(
                code=reasons.runtime.INDEX_BATCH_TYPE_MISMATCH,
                message=f"derive_index_batch returned {got}, expected a uint64 Arrow array",
            )
        if len(idx) != len(values):
            raise GenerationError(
                code=reasons.runtime.INDEX_BATCH_LENGTH_MISMATCH,
                message=f"derive_index_batch returned {len(idx)} indices for {len(values)} rows",
            )
        if idx.null_count != 0:
            raise GenerationError(
                code=reasons.runtime.INDEX_BATCH_NULL_MASK_MISMATCH,
                message="derive_index_batch returned a null offset for a non-null source row",
            )
        idx_np = idx.to_numpy(zero_copy_only=False)
        if idx_np.size and int(idx_np.max()) >= range_size:
            raise GenerationError(
                code=reasons.runtime.INDEX_BATCH_OUT_OF_BOUNDS,
                message=f"derive_index_batch returned an offset >= range_size {range_size}",
            )
        return idx_np
    except BaseException:
        del mask_key
        raise


def _typed_date_shift(
    col: pa.Array,
    *,
    min_days: int,
    range_size: int,
    mask_key: bytes,
    namespace: str,
    index_kernel: IndexDerivationKernel,
    native_threads: int | None,
    derive_calls: list[int] | None,
) -> tuple[pa.Array, tuple[int, ...]]:
    """The `DATE` shape: keyed offsets over the ISO keys, then the shared typed arithmetic.

    A row with no key (null, or outside years 1 to 9999) derives no offset; `shift_typed_days`
    flags it, and any row whose shifted day leaves that range, as failed."""
    keys, _ = canonicalize_typed_array(col)
    usable = keys.is_valid().to_numpy(zero_copy_only=False)
    offsets = np.zeros(len(col), dtype=np.int64)
    if usable.any():
        drawn = _derive_offsets(
            keys.filter(pa.array(usable)),
            range_size=range_size,
            mask_key=mask_key,
            namespace=namespace,
            index_kernel=index_kernel,
            native_threads=native_threads,
        )
        offsets[usable] = drawn.astype(np.int64) + min_days
    if derive_calls is not None:
        derive_calls.append(int(usable.any()))
    shifted, failed = shift_typed_days(col, offsets)
    return shifted, tuple(int(i) for i in np.flatnonzero(failed))


def native_date_shift(
    array: pa.Array | pa.ChunkedArray,
    *,
    min_days: int,
    max_days: int,
    date_format: str | None,
    mask_key: bytes | None,
    namespace: str,
    index_kernel: IndexDerivationKernel,
    native_threads: int | None = None,
    derive_calls: list[int] | None = None,
    preserved: np.ndarray[Any, Any] | None = None,
    shape: ColumnShape | None = None,
) -> tuple[pa.Array, tuple[int, ...]]:
    """Shift a `pa.string()` date column, or a `date32` column whose plan `shape` is `DATE`, on
    the native lane (full-frame or one chunk).

    Returns `(out, format_error_positions)`: `out` is pinned `pa.string()` (the
    whole-column null-shape reconciliation to the oracle's data-dependent type
    happens at final assembly, `_shadow_assembly.assemble_column`), and
    `format_error_positions` are the 0-based positions WITHIN `array` of the
    non-null values that failed to parse. Null and unparseable rows keep their
    original value, as in the oracle.

    `derive_calls`, when given, receives the number of compiled `derive_index_batch`
    calls this invocation made: one when any row parsed, zero for an empty, all-null or
    all-unparseable input. The chunked route reads it so its evidence only claims a
    compiled kernel when one ran.

    `preserved`, when given, is a boolean mask over `array` of sentinel rows (D1c). They are
    filtered out before parsing, so they never reach the kernel, the date arithmetic or the
    whole-column strftime, are never format errors, and keep their source text. The returned
    positions are rebased to `array`.

    A typed `shape` ignores `date_format` and returns the source type (`date32`); admission
    declines `preserve_values` on a typed column, so `preserved` is never set with it.
    """
    try:
        if mask_key is None:  # pragma: no cover - require_mask_key never returns None
            raise AssertionError(
                "date_shift reached with mask_key=None; require_mask_key always "
                "resolves a concrete key before the native route dispatches."
            )
        min_days, range_size = resolve_shift_range(min_days, max_days)
        col = array.combine_chunks() if isinstance(array, pa.ChunkedArray) else array
        if shape is not None:
            if shape is not ColumnShape.DATE or preserved is not None:  # pragma: no cover
                raise AssertionError("admission admits only a DATE shape without preserve_values")
            return _typed_date_shift(
                col,
                min_days=min_days,
                range_size=range_size,
                mask_key=mask_key,
                namespace=namespace,
                index_kernel=index_kernel,
                native_threads=native_threads,
                derive_calls=derive_calls,
            )
        if date_format is None:  # pragma: no cover - admission requires a text format
            raise AssertionError("text date_shift reached the kernel without a date_format")
        if preserved is not None and preserved.any():
            rest = pa.array(~preserved)
            computed, positions = native_date_shift(
                col.filter(rest),
                min_days=min_days,
                max_days=max_days,
                date_format=date_format,
                mask_key=mask_key,
                namespace=namespace,
                index_kernel=index_kernel,
                native_threads=native_threads,
                derive_calls=derive_calls,
            )
            kept = np.flatnonzero(~preserved)
            return (
                pc.replace_with_mask(col.cast(pa.string()), rest, computed),  # type: ignore[attr-defined, unused-ignore]
                tuple(int(kept[p]) for p in positions),
            )

        # The oracle's own series preparation: an extension dtype is coerced to
        # object before parsing. `to_pandas()` of a pa.string() column is object
        # dtype with None for nulls, matching the frame the oracle reads.
        series = col.to_pandas()
        if pd.api.types.is_extension_array_dtype(series.dtype):
            series = series.astype(object)
        parsed = pd.to_datetime(series, format=date_format, errors="coerce")
        unusable = parsed.isna().to_numpy()
        source_null = series.isna().to_numpy()

        # Unusable rows get a zero shift, exactly as the oracle's per-row loop does,
        # so the vectorized add below is the same operation over the same inputs.
        shifts = np.zeros(len(series), dtype=np.int64)
        usable = ~unusable
        if usable.any():
            offsets = _derive_offsets(
                col.filter(pa.array(usable)),
                range_size=range_size,
                mask_key=mask_key,
                namespace=namespace,
                index_kernel=index_kernel,
                native_threads=native_threads,
            )
            shifts[usable] = offsets.astype(np.int64) + min_days
        if derive_calls is not None:
            derive_calls.append(int(usable.any()))

        shifted = parsed + pd.to_timedelta(shifts, unit="D")
        formatted = shifted.dt.strftime(date_format)

        out = np.array(series.astype(object).to_numpy(copy=True), dtype=object)
        if usable.any():
            out[usable] = np.asarray(formatted.to_numpy()[usable], dtype=object)

        format_errors = tuple(int(i) for i in np.flatnonzero(unusable & ~source_null))
        return pa.array(out, type=pa.string()), format_errors
    except BaseException:
        del mask_key
        raise


__all__ = [
    "BUCKET_PERTURB_OPERATOR_ID",
    "DATE_SHIFT_OPERATOR_ID",
    "FORMAT_ERROR_REASON",
    "format_error_reason",
    "format_error_row_errors",
    "native_date_shift",
    "resolve_shift_range",
]
