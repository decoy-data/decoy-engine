//! Row-range partitioning, parallel dispatch, error arbitration, and the shared assembly-error
//! mapping used by the string, raw-hex, and index kernels.

use arrow_array::Array;
use rayon::prelude::*;

use crate::canonicalize::CanonError;
use crate::threads::shared_native_pool;

use super::BatchError;

/// One contiguous row range and the disjoint output-byte slice it fills. `split_at_mut` carves the
/// single values buffer into these non-overlapping `&mut [u8]` windows (one per range), so workers
/// never alias each other's memory and no `unsafe` or per-worker builder is needed (Task 1.5).
pub(super) struct RangeTask<'a> {
    pub(super) row_lo: usize,
    pub(super) row_hi: usize,
    /// Exactly `offsets[row_hi] - offsets[row_lo]` bytes: the output for rows `row_lo..row_hi`.
    pub(super) out: &'a mut [u8],
}

/// One contiguous row range and the disjoint `u64` output slots it fills (`derive_index_array`).
/// Unlike the string `RangeTask` (variable-width byte windows), every row owns exactly one fixed
/// `u64` slot, so the slice length is the row span and a row `i` writes `out[i - row_lo]` directly.
pub(super) struct IndexRangeTask<'a> {
    pub(super) row_lo: usize,
    pub(super) row_hi: usize,
    pub(super) out: &'a mut [u64],
}

/// One per-range result before arbitration: `Ok(())`, or the failing task's `(global_row_index,
/// error)`. `first_error_by_row_index` reduces these to the minimum-row-index error.
pub(super) type RangeResults = Vec<Result<(), (usize, BatchError)>>;

/// Run per-range `tasks` with `run`, avoiding the shared host-sized Rayon pool for a single range.
///
/// A single range is the whole batch on one worker, so installing it on the shared pool would
/// construct that pool (its host-core-sized worker threads and Rayon runtime state raise peak RSS
/// with the host's core count) for no parallel benefit. Running one range serially here is
/// byte-identical, and keeps the bounded path (`native_threads=None` -> `threads=1` -> one range)
/// from ever building the pool. Two or more ranges still install on the shared pool. A pool-build
/// failure surfaces as a coded error via `?` (the `From<DeriveError>` conversion for `BatchError`).
/// `install` is synchronous, so `run` may borrow from the caller's stack frame either way.
pub(super) fn run_range_tasks<T, F>(tasks: Vec<T>, run: F) -> Result<RangeResults, BatchError>
where
    T: Send,
    F: Fn(T) -> Result<(), (usize, BatchError)> + Sync + Send,
{
    if tasks.len() <= 1 {
        Ok(tasks.into_iter().map(run).collect())
    } else {
        let pool = shared_native_pool()?;
        Ok(pool.install(|| tasks.into_par_iter().map(run).collect()))
    }
}

/// Reduce per-range results to the single error at the MINIMUM global row index (the reference's
/// first-error-wins order), independent of which range or worker finished first. Extracted so the
/// arbitration is unit-testable with distinguishable synthetic errors: for this kernel the only
/// real per-row error (a timestamp tick out of range) is content-identical across rows, so the
/// integration path alone cannot observe WHICH failing row was chosen.
pub(super) fn first_error_by_row_index(
    results: Vec<Result<(), (usize, BatchError)>>,
) -> Option<BatchError> {
    results
        .into_iter()
        .filter_map(Result::err)
        .min_by_key(|(row, _)| *row)
        .map(|(_, err)| err)
}

/// Map an arrow-rs `StringArray::try_new` assembly failure to a coded batch error. This should be
/// unreachable in practice -- the offsets are monotonic by construction and hex bytes are valid
/// UTF-8 -- but assembling from raw buffers must still fail closed rather than panic if arrow's
/// `force_validate` scan ever rejects the buffers.
pub(super) fn assembly_error(e: arrow_schema::ArrowError) -> BatchError {
    BatchError::Canon(CanonError::unsupported(format!(
        "failed to assemble the derived StringArray from raw buffers: {e}"
    )))
}

/// Split the values buffer into `min(threads, non_null)` contiguous row ranges balanced by
/// NON-NULL count (the actual per-row work), not raw row count: nulls can cluster, and an
/// equal-row-count split would then starve some workers. Boundaries are deterministic (a forward
/// scan closing each range once it holds its target non-null quota), so the partition -- and thus
/// nothing about the output -- depends on the thread count.
/// Deterministic contiguous `(row_lo, row_hi)` ranges balanced by NON-NULL count (the actual
/// per-row work), `min(threads, non_null)` of them. Nulls can cluster, so an equal-row-count split
/// would starve some workers; this closes each range once it holds its non-null quota. Shared by
/// the string (byte-window) and index (u64-slot) parallel fills so both partition identically and
/// the partition -- and thus nothing about the output -- depends on the thread count.
pub(super) fn balanced_row_ranges(
    array: &dyn Array,
    threads: usize,
    non_null: usize,
) -> Vec<(usize, usize)> {
    let len = array.len();
    let nranges = threads.clamp(1, non_null);
    let per_range = non_null.div_ceil(nranges);
    let mut ranges: Vec<(usize, usize)> = Vec::with_capacity(nranges);
    let mut row_lo = 0usize;
    let mut seen_non_null = 0usize;
    let mut quota = per_range;
    for i in 0..len {
        if array.is_valid(i) {
            seen_non_null += 1;
        }
        let is_last_range = ranges.len() == nranges - 1;
        if !is_last_range && seen_non_null >= quota {
            ranges.push((row_lo, i + 1));
            row_lo = i + 1;
            quota += per_range;
        }
    }
    // The final range absorbs the rest (including any trailing null rows).
    ranges.push((row_lo, len));
    ranges
}

pub(super) fn partition_into_tasks<'a>(
    array: &dyn Array,
    offsets: &[i32],
    values: &'a mut [u8],
    threads: usize,
    non_null: usize,
) -> Vec<RangeTask<'a>> {
    let mut tasks: Vec<RangeTask<'a>> = Vec::new();
    let mut remaining: &'a mut [u8] = values;
    for (row_lo, row_hi) in balanced_row_ranges(array, threads, non_null) {
        let byte_len = (offsets[row_hi] - offsets[row_lo]) as usize;
        let (head, tail) = remaining.split_at_mut(byte_len);
        tasks.push(RangeTask {
            row_lo,
            row_hi,
            out: head,
        });
        remaining = tail;
    }
    tasks
}

pub(super) fn partition_index_tasks<'a>(
    array: &dyn Array,
    values: &'a mut [u64],
    threads: usize,
    non_null: usize,
) -> Vec<IndexRangeTask<'a>> {
    let mut tasks: Vec<IndexRangeTask<'a>> = Vec::new();
    let mut remaining: &'a mut [u64] = values;
    for (row_lo, row_hi) in balanced_row_ranges(array, threads, non_null) {
        let (head, tail) = remaining.split_at_mut(row_hi - row_lo);
        tasks.push(IndexRangeTask {
            row_lo,
            row_hi,
            out: head,
        });
        remaining = tail;
    }
    tasks
}
