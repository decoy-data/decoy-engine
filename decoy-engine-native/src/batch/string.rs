//! `derive_array`: the canonicalizing keyed-hash string kernel.

use arrow_array::{Array, StringArray};
use arrow_buffer::{BooleanBuffer, Buffer, NullBuffer, OffsetBuffer, ScalarBuffer};

use crate::canonicalize::{canonicalize_row, is_admitted_type, CanonError};
use crate::derive::{hex_token_into, DeriveContext, HEX_LEN};

use super::ranges::{
    assembly_error, first_error_by_row_index, partition_into_tasks, run_range_tasks, RangeTask,
};
use super::BatchError;

/// The constant per-row output width for this `truncate`: the keyed hash is always a 32-byte
/// digest -> 64 hex chars, and `token[:truncate]` slices to a length that depends only on
/// `truncate` and the constant 64, never on the digest bytes. So every non-null row has the SAME
/// width, which is what lets the offset layout be computed from the null mask alone, before any
/// derivation. A future variable-width kernel (e.g. redact) would have to revisit this.
fn constant_output_width(truncate: Option<isize>) -> usize {
    let mut buf = [0u8; HEX_LEN];
    hex_token_into(&[0u8; 32], truncate, &mut buf).len()
}

/// Validate the mask key and the array's admitted type, then canonicalize + derive + hex-encode
/// every row across up to `threads` Rayon workers, returning one output string per input row
/// (null in, null out; no derivation for a null slot). Output is byte-identical to a single-thread
/// run at every thread count: each row's hash depends only on its own canonical bytes and the
/// shared per-batch key, so the row partition cannot change any byte.
///
/// `truncate` is a signed Python-style slice stop (see `derive::hex_token_into`), not a
/// `usize`: the reference's `token[:truncate]` accepts a negative `truncate` and slices from
/// the end rather than erroring, so the native kernel must too.
///
/// `threads` is the resolved per-job budget (`NativeThreadBudget::threads`): it bounds the number
/// of row ranges, and therefore the parallelism. `1` means a single range run serially, which
/// (see `run_range_tasks`) never constructs the shared host-sized pool; `>= 2` ranges install on
/// that pool.
pub fn derive_array(
    array: &dyn Array,
    mask_key: Option<&[u8]>,
    namespace: &str,
    truncate: Option<isize>,
    threads: usize,
) -> Result<StringArray, BatchError> {
    let mask_key = match mask_key {
        Some(k) if !k.is_empty() => k,
        _ => return Err(BatchError::MaskKeyRequired),
    };

    let data_type = array.data_type();
    if !is_admitted_type(data_type) {
        return Err(BatchError::Canon(CanonError::unsupported(format!(
            "Arrow type {data_type:?} is not in the native keyed-hash admitted set"
        ))));
    }

    let len = array.len();
    let non_null = len - array.null_count();
    let width = constant_output_width(truncate);

    // Output validity == input validity (null in <-> null out). MATERIALIZE a fresh, Rust-owned
    // null bitmap (one bit per row) rather than `array.nulls().cloned()`: an imported Arrow array
    // shares an `Arc<FFI_ArrowArray>` owner across all its buffers, so a cloned validity buffer
    // would keep the ENTIRE source C array -- including its large values buffers -- alive for as
    // long as the returned output lives. `from_iter` copies only the bits, breaking that link.
    let nulls = array
        .nulls()
        .map(|nb| NullBuffer::new(BooleanBuffer::from_iter(nb.iter())));

    // The ONLY derivation-free short-circuit is "no non-null row": then the reference never calls
    // `derive()`, so seed/namespace are never validated and an empty or all-null batch must NOT
    // raise even under a wrong-length key. (A zero-`width` truncate is NOT this case: its non-null
    // rows are empty strings that still go through `derive()`, so a bad seed there must surface.)
    // Every offset is 0 (no valid row adds width), so no pre-pass is needed here.
    if non_null == 0 {
        let offsets_buf = OffsetBuffer::new(ScalarBuffer::from(vec![0i32; len + 1]));
        return StringArray::try_new(offsets_buf, Buffer::from_vec(Vec::<u8>::new()), nulls)
            .map_err(assembly_error);
    }

    // Build the per-batch key ONCE, up front (Task 1.2), BEFORE sizing the output, so an
    // (out-of-contract) >2GB batch with a wrong-length key still reports `seed_wrong_length`
    // rather than `native_offset_overflow`.
    //
    // Reference precedence, though, is: `_require_mask_key` (done above), then `_array_to_pylist`
    // converts the WHOLE array, then the per-row loop validates the seed length inside `derive()`.
    // So a per-row canonicalization failure (e.g. a timestamp tick out of range) OUTRANKS the
    // seed-length error. Match that: on the bad-seed path only -- which is already an error path
    // with no output -- scan every row for a canonicalization failure and surface it first. The
    // happy path (valid seed) never runs this scan, so there is no throughput cost.
    let ctx = match DeriveContext::new(mask_key, namespace) {
        Ok(ctx) => ctx,
        Err(seed_err) => {
            for i in 0..len {
                canonicalize_row(array, i)?;
            }
            return Err(BatchError::from(seed_err));
        }
    };

    // Serial pre-pass: the full i32 offset layout from the null mask alone (no derivation yet).
    // `offsets[i+1] = offsets[i] + (valid ? width : 0)`; a null row keeps the previous offset
    // (0-width). Fail closed on i32 overflow rather than wrap: the pre-1.5 `StringBuilder` had the
    // same i32 ceiling, and a >2GB batch is outside this kernel's per-batch contract (the engine
    // chunks far under it).
    let mut offsets: Vec<i32> = Vec::with_capacity(len + 1);
    offsets.push(0);
    let mut acc: i32 = 0;
    for i in 0..len {
        if array.is_valid(i) {
            acc = acc
                .checked_add(width as i32)
                .ok_or(BatchError::OffsetOverflow)?;
        }
        offsets.push(acc);
    }
    let total_bytes = acc as usize;

    // One initialized values buffer, carved into disjoint per-range windows. `vec![0u8; ..]` (not
    // just capacity) so the slices have real length to split; each worker overwrites its window.
    let mut values = vec![0u8; total_bytes];
    let tasks = partition_into_tasks(array, &offsets, &mut values, threads, non_null);

    // A single range is the whole batch on one worker, so `run_range_tasks` runs it serially and
    // never constructs the host-sized shared pool (see that fn). Multi-range work installs on the
    // shared pool; `install` is synchronous, so workers may borrow `array`/`ctx`/`values` from
    // this stack frame and a worker panic propagates to `derive_batch`'s `catch_unwind`.
    let results = run_range_tasks(tasks, |task| fill_range(&ctx, array, truncate, task))?;

    // Multi-error arbitration: report the failure at the MINIMUM global row index, never
    // task-completion order, so the error matches the sequential first-error-wins path exactly.
    if let Some(err) = first_error_by_row_index(results) {
        return Err(err);
    }

    let offsets_buf = OffsetBuffer::new(ScalarBuffer::from(offsets));
    StringArray::try_new(offsets_buf, Buffer::from_vec(values), nulls).map_err(assembly_error)
}

/// Fill one range's output window: canonicalize + derive + hex-encode each non-null row straight
/// into `task.out`. On the first failing row, return its GLOBAL index with the coded error and
/// stop (the caller reduces to the minimum index across ranges). Null rows write nothing (their
/// 0-width slot is already laid out).
fn fill_range(
    ctx: &DeriveContext,
    array: &dyn Array,
    truncate: Option<isize>,
    task: RangeTask<'_>,
) -> Result<(), (usize, BatchError)> {
    // Test-only fault injection: force a panic INSIDE a Rayon worker (a non-empty range on a pool
    // thread) so the worker-panic path is exercised end to end -- the panic must propagate out of
    // `pool.install` and become the coded `internal_panic` error, with no partial array returned.
    // Never set in production; the single `var_os` is per range (a handful per batch), negligible.
    if task.row_hi > task.row_lo
        && std::env::var_os("DECOY_ENGINE_NATIVE_FORCE_PANIC_IN_WORKER").is_some()
        && rayon::current_thread_index().is_some()
    {
        // The `current_thread_index().is_some()` guard means this fires ONLY on a Rayon pool
        // worker: a test that observes the coded `internal_panic` has thereby proven the range
        // ran on the pool, not inline on the calling thread.
        panic!("test-only forced panic inside a Rayon worker");
    }

    let mut hex_buf = [0u8; HEX_LEN];
    let mut cursor = 0usize;
    for i in task.row_lo..task.row_hi {
        match canonicalize_row(array, i).map_err(|e| (i, BatchError::from(e)))? {
            None => {}
            Some(canonical) => {
                let digest = ctx
                    .derive_row(&canonical)
                    .map_err(|e| (i, BatchError::from(e)))?;
                let token = hex_token_into(&digest, truncate, &mut hex_buf);
                let bytes = token.as_bytes();
                task.out[cursor..cursor + bytes.len()].copy_from_slice(bytes);
                cursor += bytes.len();
            }
        }
    }
    Ok(())
}
