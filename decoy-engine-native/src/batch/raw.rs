//! `derive_hex_raw_array`: the non-canonicalizing raw-hex kernel for the `group_key` path.

use arrow_array::{Array, StringArray};
use arrow_buffer::{BooleanBuffer, Buffer, NullBuffer, OffsetBuffer, ScalarBuffer};

use crate::derive::{hex_prefix_into, DeriveContext, HEX_LEN};

use super::ranges::{
    assembly_error, first_error_by_row_index, partition_into_tasks, run_range_tasks, RangeTask,
};
use super::BatchError;

/// Validate the mask key, then derive + hex-encode every row of a `pa.string()` column WITHOUT
/// canonicalization, returning one hex string per input row (null in, null out).
///
/// This is the `group_key` derivation path. Its one difference from `derive_array` is the whole
/// reason it exists: `derive_array` canonicalizes each row (`canonicalize_row`: NFC-normalize
/// strings, length-prefix ints, special-encode bool/date) before deriving, but the group_key
/// oracle hashes the RAW bytes of `str(value)` with no canonicalizer at all
/// (`transforms/group_key.py`). So this kernel reads the UTF-8 bytes of an already-stringified
/// column straight into `derive`, byte-parity target
/// `derive(mask_key, namespace, s.encode())[:hex_chars//2].hex()`. The stringification itself is
/// the caller's job (pandas `Series.astype(str)`, the one formatter proven to match the oracle),
/// so the kernel only ever sees a `pa.string()` array.
///
/// `hex_chars` is the config `length` (even, `[8, 64]`); the truncation unit is converted to
/// bytes in exactly one place here (`output_bytes = hex_chars / 2`), so no layer downstream can
/// double it. Output is byte-identical at every thread count (each row's hash depends only on its
/// own bytes and the shared per-batch key), the same invariant `derive_array` holds.
pub fn derive_hex_raw_array(
    array: &dyn Array,
    mask_key: Option<&[u8]>,
    namespace: &str,
    hex_chars: usize,
    threads: usize,
) -> Result<StringArray, BatchError> {
    let mask_key = match mask_key {
        Some(k) if !k.is_empty() => k,
        _ => return Err(BatchError::MaskKeyRequired),
    };

    // The truncation unit, converted to bytes in ONE place. Even and in `[2, 64]` mirrors the
    // config `length`'s `[8, 64]`-even contract; a smaller even width (2..6) is still well-formed
    // arithmetic and rejected only by the Python-side range check, so accepting it here keeps the
    // kernel's own contract self-consistent rather than duplicating the config bound.
    if hex_chars == 0 || !hex_chars.is_multiple_of(2) || hex_chars > HEX_LEN {
        return Err(BatchError::RawHexCharsInvalid);
    }
    let output_bytes = hex_chars / 2;

    let string_array = array
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or(BatchError::RawInputNotString)?;

    let len = string_array.len();
    let non_null = len - string_array.null_count();
    let width = hex_chars; // constant per non-null row: 2 hex chars per output byte

    // Output validity == input validity. Materialize a FRESH bitmap (never `nulls().cloned()`,
    // which pins the whole imported `Arc<FFI_ArrowArray>` -- Task 1.5 lesson, same as
    // `derive_array`). In practice the caller's `astype(str)` leaves NO nulls (a null cell becomes
    // the string "None"), so this branch is a defensive carry-through, not a live group_key shape.
    let nulls = string_array
        .nulls()
        .map(|nb| NullBuffer::new(BooleanBuffer::from_iter(nb.iter())));

    // No non-null row: the oracle never calls `derive()` for an empty column, so seed/namespace
    // are never validated -- an empty batch must return cleanly even under a wrong-length key.
    if non_null == 0 {
        let offsets_buf = OffsetBuffer::new(ScalarBuffer::from(vec![0i32; len + 1]));
        return StringArray::try_new(offsets_buf, Buffer::from_vec(Vec::<u8>::new()), nulls)
            .map_err(assembly_error);
    }

    // The raw path has NO per-row canonicalization that can fail, so (unlike `derive_array`) a
    // bad seed needs no first-scan to outrank it: the seed/namespace error surfaces directly from
    // `DeriveContext::new`, exactly where the oracle's first `derive()` call would raise it.
    let ctx = DeriveContext::new(mask_key, namespace)?;

    // Serial pre-pass: full i32 offset layout from the null mask alone (no derivation yet).
    let mut offsets: Vec<i32> = Vec::with_capacity(len + 1);
    offsets.push(0);
    let mut acc: i32 = 0;
    for i in 0..len {
        if string_array.is_valid(i) {
            acc = acc
                .checked_add(width as i32)
                .ok_or(BatchError::OffsetOverflow)?;
        }
        offsets.push(acc);
    }
    let total_bytes = acc as usize;

    let mut values = vec![0u8; total_bytes];
    let tasks = partition_into_tasks(string_array, &offsets, &mut values, threads, non_null);
    let results = run_range_tasks(tasks, |task| {
        fill_raw_range(&ctx, string_array, output_bytes, task)
    })?;
    if let Some(err) = first_error_by_row_index(results) {
        return Err(err);
    }

    let offsets_buf = OffsetBuffer::new(ScalarBuffer::from(offsets));
    StringArray::try_new(offsets_buf, Buffer::from_vec(values), nulls).map_err(assembly_error)
}

/// Fill one range's output window for the raw-hex kernel: derive + hex-encode each non-null row's
/// RAW UTF-8 bytes straight into `task.out`, no canonicalization. Mirrors `fill_range` but reads
/// the string value directly (a `StringArray` value is always valid UTF-8 by Arrow construction,
/// so there is no per-row canon error to surface; only a >4 GiB source length could fail, matching
/// `derive_array`'s own reachable per-row error set).
fn fill_raw_range(
    ctx: &DeriveContext,
    array: &StringArray,
    output_bytes: usize,
    task: RangeTask<'_>,
) -> Result<(), (usize, BatchError)> {
    // Same worker-panic injection as `fill_range`: fires only on a Rayon pool worker.
    if task.row_hi > task.row_lo
        && std::env::var_os("DECOY_ENGINE_NATIVE_FORCE_PANIC_IN_WORKER").is_some()
        && rayon::current_thread_index().is_some()
    {
        panic!("test-only forced panic inside a Rayon worker");
    }

    let mut hex_buf = [0u8; HEX_LEN];
    let mut cursor = 0usize;
    for i in task.row_lo..task.row_hi {
        if array.is_null(i) {
            continue;
        }
        let raw = array.value(i).as_bytes();
        let digest = ctx.derive_row(raw).map_err(|e| (i, BatchError::from(e)))?;
        let token = hex_prefix_into(&digest, output_bytes, &mut hex_buf);
        let bytes = token.as_bytes();
        task.out[cursor..cursor + bytes.len()].copy_from_slice(bytes);
        cursor += bytes.len();
    }
    Ok(())
}
