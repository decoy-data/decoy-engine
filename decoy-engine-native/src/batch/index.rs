//! `derive_index_array`: the deterministic pool-index kernel for the faker route.

use arrow_array::{Array, UInt64Array};
use arrow_buffer::{BooleanBuffer, NullBuffer, ScalarBuffer};

use crate::canonicalize::{canonicalize_row, is_admitted_type, CanonError};
use crate::derive::DeriveContext;

use super::ranges::{
    assembly_error, first_error_by_row_index, partition_index_tasks, run_range_tasks,
    IndexRangeTask,
};
use super::{BatchError, PoolSize};

fn fill_index_range(
    ctx: &DeriveContext,
    array: &dyn Array,
    pool_size: u64,
    task: IndexRangeTask<'_>,
) -> Result<(), (usize, BatchError)> {
    // Same worker-panic injection as `fill_range`: fires only on a Rayon pool worker.
    if task.row_hi > task.row_lo
        && std::env::var_os("DECOY_ENGINE_NATIVE_FORCE_PANIC_IN_WORKER").is_some()
        && rayon::current_thread_index().is_some()
    {
        panic!("test-only forced panic inside a Rayon worker");
    }

    for i in task.row_lo..task.row_hi {
        match canonicalize_row(array, i).map_err(|e| (i, BatchError::from(e)))? {
            // Null row: leave the pre-zeroed slot; the output null buffer masks it.
            None => {}
            Some(canonical) => {
                let digest = ctx
                    .derive_row(&canonical)
                    .map_err(|e| (i, BatchError::from(e)))?;
                // First 8 bytes of the 32-byte digest as a big-endian u64, then mod pool_size:
                // byte-identical to Python's `int.from_bytes(digest[:8], "big") % pool_size`.
                let head = u64::from_be_bytes(
                    digest[..8]
                        .try_into()
                        .expect("derive_row always returns 32 bytes"),
                );
                task.out[i - task.row_lo] = head % pool_size;
            }
        }
    }
    Ok(())
}

/// Deterministic pool index per row: `u64_be(derive(mask_key, namespace, canonical(value))[:8]) %
/// pool_size`, reproducing the frozen `derive_index` contract (see the derive-index-contract doc
/// and the `derive_index_kat.json` vectors). Output is a `UInt64Array`, null in -> null out. The
/// row loop runs across up to `threads` Rayon workers on the shared pool, byte-identical at every
/// thread count (each index depends only on its own row).
///
/// `pool_size` is a signed `i64` so the guards can report the reference's coded errors directly; the
/// PyO3 boundary maps an out-of-`i64` Python int to `pool_size_overflow` before it reaches here.
/// Ergonomic i64 entry point: an in-contract `pool_size` is always a Python int by the time the
/// numeric guards run, so the whole Rust-only surface (tests, allocation bound, KAT) uses this.
/// The PyO3 boundary uses `derive_index_array_typed` directly so it can defer a NON-int pool_size.
pub fn derive_index_array(
    array: &dyn Array,
    mask_key: Option<&[u8]>,
    namespace: &str,
    pool_size: i64,
    threads: usize,
) -> Result<UInt64Array, BatchError> {
    derive_index_array_typed(
        array,
        mask_key,
        namespace,
        PoolSize::Int(pool_size),
        threads,
    )
}

pub fn derive_index_array_typed(
    array: &dyn Array,
    mask_key: Option<&[u8]>,
    namespace: &str,
    pool_size: PoolSize,
    threads: usize,
) -> Result<UInt64Array, BatchError> {
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
    // Output validity == input validity; materialize a FRESH bitmap (never `array.nulls().cloned()`,
    // which would pin the whole imported `Arc<FFI_ArrowArray>` -- Task 1.5 lesson).
    let nulls = array
        .nulls()
        .map(|nb| NullBuffer::new(BooleanBuffer::from_iter(nb.iter())));

    // No non-null row: the reference sampler never calls `derive_index` for a null row, so an empty
    // or all-null batch validates NOTHING (not pool_size, seed, or namespace) and returns all-null.
    if non_null == 0 {
        return UInt64Array::try_new(ScalarBuffer::from(vec![0u64; len]), nulls)
            .map_err(assembly_error);
    }

    // Reference precedence: the sampler canonicalizes a row BEFORE that row's `derive_index` runs
    // its pool-size check, so a canonicalization failure on the FIRST non-null row outranks a bad
    // pool_size (which in turn outranks a bad seed/namespace). Canonicalize the first non-null row
    // here so canon(first) precedes the pool guard; only the first non-null row matters, since the
    // pool check happens at that row. The parallel fill re-canonicalizes it (one row, negligible).
    let first_non_null = (0..len)
        .find(|&i| array.is_valid(i))
        .expect("non_null > 0 guarantees a valid row");
    canonicalize_row(array, first_non_null)?;

    // Pool guards, AFTER the first-row canonicalization and BEFORE the derive context. This is the
    // slot the reference's in-`derive_index` `pool_size > MAX` comparison occupies, so a non-int
    // pool_size (`NotAnInteger`) is rejected HERE too -- after canon(first non-null) outranks it and
    // after the all-null short-circuit above skips it entirely -- never eagerly at the boundary.
    // `2**56` is INCLUSIVE (the guard is strictly greater-than), matching the frozen contract.
    let pool_size = match pool_size {
        PoolSize::NotAnInteger => return Err(BatchError::PoolSizeType),
        PoolSize::Int(n) if n < 1 => return Err(BatchError::PoolSizeInvalid),
        PoolSize::Int(n) if n > (1i64 << 56) => return Err(BatchError::PoolSizeOverflow),
        PoolSize::Int(n) => n as u64,
    };

    let ctx = DeriveContext::new(mask_key, namespace)?;

    let mut values = vec![0u64; len];
    let tasks = partition_index_tasks(array, &mut values, threads, non_null);

    let results = run_range_tasks(tasks, |task| fill_index_range(&ctx, array, pool_size, task))?;
    if let Some(err) = first_error_by_row_index(results) {
        return Err(err);
    }

    UInt64Array::try_new(ScalarBuffer::from(values), nulls).map_err(assembly_error)
}
