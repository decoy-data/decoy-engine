use super::ranges::first_error_by_row_index;
use super::*;
use crate::canonicalize::CanonError;
use arrow_array::{Array, StringArray};

fn one_row_array() -> StringArray {
    StringArray::from(vec![Some("alice")])
}

/// The two lengths the reference accepts (8-byte job_seed, 32-byte mask_key) must still
/// succeed: this guard must reject only what the reference rejects, never narrow the
/// admitted set further.
#[test]
fn accepts_the_two_reference_seed_lengths() {
    let array = one_row_array();
    for len in [8usize, 32] {
        let key = vec![0u8; len];
        let result = derive_array(&array, Some(&key), "ns", None, 1);
        assert!(
            result.is_ok(),
            "length {len} must be accepted, got {result:?}"
        );
    }
}

/// Every OTHER length -- including ones that are merely "close" to 8 or 32 -- must fail
/// closed with the reference's own `seed_wrong_length` code once a non-null row is reached.
#[test]
fn rejects_every_other_seed_length_with_seed_wrong_length() {
    let array = one_row_array();
    for len in [1usize, 7, 9, 16, 20, 31, 33, 64] {
        let key = vec![0u8; len];
        let err = derive_array(&array, Some(&key), "ns", None, 1)
            .expect_err(&format!("length {len} must be rejected"));
        assert_eq!(err.code(), "seed_wrong_length");
        assert!(
            err.detail().contains(&len.to_string()),
            "detail should report the offending length {len}: {}",
            err.detail()
        );
    }
}

/// A present-but-empty mask key (`Some(&[])`, distinct from a wholly missing `None`) must
/// fail closed the same way a missing key does: the guard checks non-emptiness, not just
/// presence, matching `_require_mask_key`'s own check on the reference side.
#[test]
fn present_but_empty_mask_key_fails_closed_with_mask_key_required() {
    let array = one_row_array();
    let empty_key: &[u8] = &[];
    let err = derive_array(&array, Some(empty_key), "ns", None, 1).unwrap_err();
    assert!(matches!(err, BatchError::MaskKeyRequired));
    assert_eq!(err.code(), "mask_key_required");
    assert!(err.detail().contains("mask_key"));
}

/// A batch with at least one non-null row must produce no output at all for a wrong-length
/// key (Rust's `Result` already guarantees this structurally: an `Err` return carries no
/// `StringArray`), and must report the reference's own code.
#[test]
fn wrong_length_key_with_a_non_null_row_produces_no_output_at_all() {
    let array = StringArray::from(vec![Some("a"), Some("b"), Some("c")]);
    let err = derive_array(&array, Some(&[0u8; 20]), "ns", None, 1).unwrap_err();
    assert_eq!(err.code(), "seed_wrong_length");
    assert!(err.detail().contains("20"));
}

/// The reference's `_ReferenceKeyedDerivation.derive_batch` never calls `derive()` for an
/// empty batch (nothing to iterate), so a wrong-length key or an empty namespace must not
/// raise: the native kernel must match, not "fail extra safely" ahead of the reference.
#[test]
fn empty_batch_with_wrong_length_key_or_empty_namespace_succeeds() {
    let empty = StringArray::from(Vec::<Option<&str>>::new());
    let wrong_len_key = [0u8; 20];
    let valid_key = [0u8; 32];

    let out = derive_array(&empty, Some(&wrong_len_key), "ns", None, 1).unwrap();
    assert_eq!(out.len(), 0);

    let out = derive_array(&empty, Some(&valid_key), "", None, 1).unwrap();
    assert_eq!(out.len(), 0);
}

/// Same reasoning as the empty-batch case, but with rows present and all of them null:
/// `derive()` is still never called (every row takes the `None` branch), so this must
/// still succeed, returning an all-null column.
#[test]
fn all_null_batch_with_wrong_length_key_or_empty_namespace_succeeds() {
    let all_null = StringArray::from(vec![None::<&str>, None, None]);
    let wrong_len_key = [0u8; 20];
    let valid_key = [0u8; 32];

    let out = derive_array(&all_null, Some(&wrong_len_key), "ns", None, 1).unwrap();
    assert_eq!(out.to_data().null_count(), 3);

    let out = derive_array(&all_null, Some(&valid_key), "", None, 1).unwrap();
    assert_eq!(out.to_data().null_count(), 3);
}

/// The mirror case: as soon as ONE row is non-null, both bad-key-length and empty-namespace
/// must fail closed, even alongside nulls in the same batch.
#[test]
fn one_non_null_row_among_nulls_still_fails_closed() {
    let mixed = StringArray::from(vec![None, Some("alice"), None]);
    let wrong_len_key = [0u8; 20];
    let valid_key = [0u8; 32];

    let err = derive_array(&mixed, Some(&wrong_len_key), "ns", None, 1).unwrap_err();
    assert_eq!(err.code(), "seed_wrong_length");

    let err = derive_array(&mixed, Some(&valid_key), "", None, 1).unwrap_err();
    assert_eq!(err.code(), "namespace_empty");
}

/// A mixed string array with nulls, long enough to split into several ranges. Content varies
/// per row so partition boundaries could expose an off-by-one in the offset math.
fn mixed_string_fixture(rows: usize) -> StringArray {
    let values: Vec<Option<String>> = (0..rows)
        .map(|i| match i % 5 {
            0 => None,
            1 => Some(String::new()),
            n => Some(format!("row-{i}-{}", "x".repeat(n))),
        })
        .collect();
    StringArray::from(values)
}

/// EXIT GATE: output must be byte-identical at every thread count. Each row's hash depends only
/// on its own bytes and the shared key, so no row partition can change any output byte. Covers
/// several `truncate` values, including `0` (every non-null row -> empty string, still derived)
/// and out-of-range slices.
#[test]
fn thread_count_never_changes_output() {
    let array = mixed_string_fixture(97); // prime-ish, forces uneven range boundaries
    let key = [7u8; 32];
    for truncate in [
        None,
        Some(0isize),
        Some(1),
        Some(10),
        Some(63),
        Some(100),
        Some(-5),
    ] {
        // threads=1 is the serial, pool-free path (`run_range_tasks`); 2..16 install on the
        // shared pool. This asserts the direct-one-range output matches the pooled output.
        let baseline = derive_array(&array, Some(&key), "ns", truncate, 1).unwrap();
        for threads in [2usize, 3, 4, 8, 16] {
            let out = derive_array(&array, Some(&key), "ns", truncate, threads).unwrap();
            assert_eq!(
                out, baseline,
                "output diverged at threads={threads}, truncate={truncate:?}"
            );
        }
    }
}

/// A tz-aware second-resolution timestamp holding `i64::MAX` is admitted by type but fails
/// conversion per row (Codex's non-vacuous per-row error). It must surface the coded overflow
/// error at every thread count, whichever range the bad row lands in.
fn timestamp_with_bad_rows() -> arrow_array::TimestampSecondArray {
    let mut v: Vec<Option<i64>> = (0..80).map(|i| Some(i as i64)).collect();
    v[3] = Some(i64::MAX); // low-index failure
    v[61] = Some(i64::MIN); // high-index failure, a different range under threads>=2
    arrow_array::TimestampSecondArray::from(v).with_timezone("UTC")
}

#[test]
fn multi_error_surfaces_the_overflow_code_under_parallelism() {
    let array = timestamp_with_bad_rows();
    let key = [7u8; 32];
    for threads in [1usize, 2, 4, 8] {
        let err = derive_array(&array, Some(&key), "ns", None, threads).unwrap_err();
        assert_eq!(
            err.code(),
            "mixed_object_not_native",
            "threads={threads}: a bad timestamp row must fail closed with its coded error"
        );
    }
}

/// Reference precedence (matched by the bad-seed canonicalization scan): `_array_to_pylist`
/// converts the whole array before the derive loop validates the seed length, so a per-row
/// canonicalization failure OUTRANKS a wrong-length seed. A batch with a bad timestamp row AND
/// a wrong-length key must report the DATA error, not `seed_wrong_length`, at every thread
/// count. (A clean array with a wrong-length key still reports `seed_wrong_length`.)
#[test]
fn canonicalization_error_outranks_wrong_seed_length() {
    let bad = timestamp_with_bad_rows(); // rows 3 and 61 fail conversion
    let wrong_len_key = [0u8; 20];
    for threads in [1usize, 2, 4, 8] {
        let err = derive_array(&bad, Some(&wrong_len_key), "ns", None, threads).unwrap_err();
        assert_eq!(
            err.code(),
            "mixed_object_not_native",
            "threads={threads}: a bad-data row must outrank the wrong-length seed"
        );
    }

    // Control: a clean array with the same wrong-length key still surfaces the seed error.
    let clean =
        arrow_array::TimestampSecondArray::from(vec![Some(0i64), Some(1)]).with_timezone("UTC");
    let err = derive_array(&clean, Some(&wrong_len_key), "ns", None, 4).unwrap_err();
    assert_eq!(err.code(), "seed_wrong_length");
}

/// The arbitration reducer picks the MINIMUM global row index regardless of collection order,
/// which is what matches the reference's first-error-wins semantics. Tested directly with
/// DISTINGUISHABLE errors because the kernel's only real per-row error is content-identical
/// across rows (so the integration path cannot observe which row was chosen).
#[test]
fn first_error_by_row_index_selects_the_lowest_row() {
    // Row 2's error must win over row 5's, in either collection order.
    let low = || (2usize, BatchError::MaskKeyRequired);
    let high = || {
        (
            5usize,
            BatchError::Canon(CanonError::unsupported("higher row")),
        )
    };
    let forward = vec![Ok(()), Err(low()), Ok(()), Err(high())];
    let reversed = vec![Err(high()), Ok(()), Err(low()), Ok(())];
    assert_eq!(
        first_error_by_row_index(forward).unwrap().code(),
        "mask_key_required"
    );
    assert_eq!(
        first_error_by_row_index(reversed).unwrap().code(),
        "mask_key_required"
    );
    // All-Ok reduces to no error.
    assert!(first_error_by_row_index(vec![Ok(()), Ok(())]).is_none());
}

/// TSan target (name contains "concurrent" so the sanitizer job's filter matches it): a single
/// multi-range `derive_array` call must be race-free and byte-identical to the 1-thread run.
/// The disjoint `split_at_mut` windows are the thing under test -- any aliasing write would be
/// a TSan finding here.
#[test]
fn parallel_multi_range_concurrent_fill_agrees_with_single_thread() {
    let array = mixed_string_fixture(50);
    let key = [9u8; 32];
    let baseline = derive_array(&array, Some(&key), "ns", None, 1).unwrap();
    let parallel = derive_array(&array, Some(&key), "ns", None, 8).unwrap();
    assert_eq!(parallel, baseline);
}

/// Thread invariance is TYPE-AGNOSTIC (the parallel machinery branches only on the null mask,
/// never on the input Arrow type), but the string tests alone leave that unasserted for the
/// other admitted types. Assert parallel == 1-thread for int64, bool, and LargeUtf8 with nulls,
/// which -- combined with the Python live-reference parity suite proving 1-thread == oracle --
/// seals parallel == oracle for every admitted type.
#[test]
fn thread_invariance_holds_for_non_string_admitted_types() {
    use arrow_array::{BooleanArray, Int64Array, LargeStringArray};
    let key = [3u8; 32];

    let int64: Vec<Option<i64>> = (0..60)
        .map(|i| {
            if i % 4 == 0 {
                None
            } else {
                Some(i as i64 * 7 - 3)
            }
        })
        .collect();
    let int64 = Int64Array::from(int64);
    assert_eq!(
        derive_array(&int64, Some(&key), "ns", None, 8).unwrap(),
        derive_array(&int64, Some(&key), "ns", None, 1).unwrap(),
    );

    let boolean: Vec<Option<bool>> = (0..60)
        .map(|i| if i % 3 == 0 { None } else { Some(i % 2 == 0) })
        .collect();
    let boolean = BooleanArray::from(boolean);
    assert_eq!(
        derive_array(&boolean, Some(&key), "ns", None, 8).unwrap(),
        derive_array(&boolean, Some(&key), "ns", None, 1).unwrap(),
    );

    let large: Vec<Option<String>> = (0..60)
        .map(|i| match i % 5 {
            0 => None,
            1 => Some(String::new()),
            n => Some(format!("large-{i}-{}", "y".repeat(n))),
        })
        .collect();
    let large = LargeStringArray::from(large);
    assert_eq!(
        derive_array(&large, Some(&key), "ns", None, 8).unwrap(),
        derive_array(&large, Some(&key), "ns", None, 1).unwrap(),
    );
}

/// A `truncate` of 0 makes every non-null row an EMPTY string, but the reference still calls
/// `derive()` per non-null row, so a bad seed must still fail closed -- the zero-width case must
/// NOT take the derivation-free "no non-null row" short-circuit.
#[test]
fn zero_width_truncate_still_validates_the_seed() {
    let array = StringArray::from(vec![Some("a"), Some("b")]);
    let err = derive_array(&array, Some(&[0u8; 20]), "ns", Some(0), 4).unwrap_err();
    assert_eq!(err.code(), "seed_wrong_length");

    // With a valid key, zero-width yields two non-null EMPTY strings (not nulls).
    let out = derive_array(&array, Some(&[0u8; 32]), "ns", Some(0), 4).unwrap();
    assert_eq!(out.len(), 2);
    assert_eq!(out.null_count(), 0);
    assert_eq!(out.value(0), "");
    assert_eq!(out.value(1), "");
}

// --- derive_index_array (Task 2.2) ---

/// EXIT GATE: the index output is byte-identical at every thread count and pool size.
#[test]
fn derive_index_thread_count_never_changes_output() {
    let array = mixed_string_fixture(97);
    let key = [7u8; 32];
    for pool in [1i64, 2, 1000, 1 << 56] {
        // threads=1 is the serial, pool-free path; 2..16 install on the shared pool.
        let baseline = derive_index_array(&array, Some(&key), "ns", pool, 1).unwrap();
        for threads in [2usize, 3, 4, 8, 16] {
            let out = derive_index_array(&array, Some(&key), "ns", pool, threads).unwrap();
            assert_eq!(out, baseline, "diverged at threads={threads} pool={pool}");
        }
    }
}

/// The reduction is exactly `u64_be(derive(...)[:8]) % pool_size` and every index is in range;
/// null in -> null out.
#[test]
fn derive_index_matches_manual_reduction_and_is_in_range() {
    use crate::canonicalize::canonicalize_row;
    use crate::derive::derive;
    let array = StringArray::from(vec![Some("alice"), None, Some("bob")]);
    let key = [3u8; 32];
    let pool: i64 = 1000;
    let out = derive_index_array(&array, Some(&key), "ns", pool, 4).unwrap();
    assert!(out.is_null(1));
    for row in [0usize, 2] {
        let canonical = canonicalize_row(&array, row).unwrap().unwrap();
        let digest = derive(&key, "ns", &canonical).unwrap();
        let manual = u64::from_be_bytes(digest[..8].try_into().unwrap()) % pool as u64;
        assert_eq!(out.value(row), manual);
        assert!(out.value(row) < pool as u64);
    }
}

#[test]
fn derive_index_pool_size_guards_with_inclusive_2_56_boundary() {
    let array = StringArray::from(vec![Some("alice")]);
    let key = [0u8; 32];
    let code = |p: i64| {
        derive_index_array(&array, Some(&key), "ns", p, 1)
            .unwrap_err()
            .code()
            .to_string()
    };
    assert_eq!(code(0), "pool_size_invalid");
    assert_eq!(code(-5), "pool_size_invalid");
    assert_eq!(code((1 << 56) + 1), "pool_size_overflow");
    // 2**56 is INCLUSIVE (the guard is strictly greater-than).
    assert!(derive_index_array(&array, Some(&key), "ns", 1 << 56, 1).is_ok());
}

/// An empty or all-null batch validates NOTHING (no derive_index is called), so a wrong-length
/// key AND a bad pool_size must both be tolerated (mirrors the reference sampler).
#[test]
fn derive_index_all_null_and_empty_validate_nothing() {
    let all_null = StringArray::from(vec![None::<&str>, None, None]);
    let out = derive_index_array(&all_null, Some(&[0u8; 20]), "", 0, 4).unwrap();
    assert_eq!(out.len(), 3);
    assert_eq!(out.null_count(), 3);

    let empty = StringArray::from(Vec::<Option<&str>>::new());
    let out = derive_index_array(&empty, Some(&[0u8; 20]), "", -1, 4).unwrap();
    assert_eq!(out.len(), 0);
}

/// Precedence (frozen contract + reference): canon(first non-null row) > pool_size > seed/ns.
#[test]
fn derive_index_precedence_canon_then_pool_then_seed() {
    let key_ok = [0u8; 32];
    let key_bad = [0u8; 20];
    let clean = StringArray::from(vec![Some("alice"), Some("bob")]);
    let code = |a: &dyn Array, k: &[u8], p: i64| {
        derive_index_array(a, Some(k), "ns", p, 4)
            .unwrap_err()
            .code()
            .to_string()
    };

    // clean + bad pool -> pool; clean + bad seed -> seed; bad pool + bad seed -> pool wins.
    assert_eq!(code(&clean, &key_ok, 0), "pool_size_invalid");
    assert_eq!(code(&clean, &key_bad, 1000), "seed_wrong_length");
    assert_eq!(code(&clean, &key_bad, 0), "pool_size_invalid");

    // bad-data FIRST non-null row (tz overflow) + bad pool -> CANON wins.
    let bad_first =
        arrow_array::TimestampSecondArray::from(vec![Some(i64::MAX), Some(0)]).with_timezone("UTC");
    assert_eq!(code(&bad_first, &key_ok, 0), "mixed_object_not_native");
    // bad-data at a LATER row + bad pool -> POOL wins (pool is checked at the first non-null row,
    // whose canon succeeds, before the later bad row is reached).
    let bad_later =
        arrow_array::TimestampSecondArray::from(vec![Some(0), Some(i64::MAX)]).with_timezone("UTC");
    assert_eq!(code(&bad_later, &key_ok, 0), "pool_size_invalid");
}

/// A NON-int pool_size (`PoolSize::NotAnInteger`) must be ordered exactly where the numeric
/// pool guards are: after the all-null short-circuit (which skips it), after canon(first
/// non-null) (which outranks it), and it surfaces as the distinct `pool_size_type` code. This is
/// the Rust-level proof of the precedence the PyO3 boundary defers; the compiled-boundary
/// equivalent (a real non-int Python object -> TypeError) lives in test_derive_index_kat.py.
#[test]
fn derive_index_non_integer_pool_is_ordered_after_canon() {
    let key = [0u8; 32];
    let typed = |a: &dyn Array, p: PoolSize| derive_index_array_typed(a, Some(&key), "ns", p, 4);

    // All-null / empty validate NOTHING: a non-int pool is tolerated, same as a bad numeric one.
    let all_null = StringArray::from(vec![None::<&str>, None]);
    assert_eq!(
        typed(&all_null, PoolSize::NotAnInteger)
            .unwrap()
            .null_count(),
        2
    );
    let empty = StringArray::from(Vec::<Option<&str>>::new());
    assert_eq!(typed(&empty, PoolSize::NotAnInteger).unwrap().len(), 0);

    // A clean first non-null row -> the non-int is rejected as pool_size_type (its own code,
    // distinct from pool_size_invalid/overflow).
    let clean = StringArray::from(vec![Some("alice"), Some("bob")]);
    assert_eq!(
        typed(&clean, PoolSize::NotAnInteger).unwrap_err().code(),
        "pool_size_type"
    );

    // A canon fault on the FIRST non-null row outranks the non-int pool (canon > pool), exactly
    // as it outranks a bad numeric pool in `derive_index_precedence_canon_then_pool_then_seed`.
    let bad_first =
        arrow_array::TimestampSecondArray::from(vec![Some(i64::MAX), Some(0)]).with_timezone("UTC");
    assert_eq!(
        typed(&bad_first, PoolSize::NotAnInteger)
            .unwrap_err()
            .code(),
        "mixed_object_not_native"
    );
    // A canon fault at a LATER row does NOT outrank it: the pool is checked at the first
    // non-null row (canon-clean), so the non-int rejection wins before the later bad row.
    let bad_later =
        arrow_array::TimestampSecondArray::from(vec![Some(0), Some(i64::MAX)]).with_timezone("UTC");
    assert_eq!(
        typed(&bad_later, PoolSize::NotAnInteger)
            .unwrap_err()
            .code(),
        "pool_size_type"
    );
}

/// A present-but-empty mask key (`Some(&[])`) must fail closed with `mask_key_required`, exactly
/// like the string path -- the guard checks non-emptiness, not just presence.
#[test]
fn derive_index_present_but_empty_mask_key_fails_closed() {
    let array = StringArray::from(vec![Some("alice")]);
    let empty: &[u8] = &[];
    let err = derive_index_array(&array, Some(empty), "ns", 1000, 4).unwrap_err();
    assert_eq!(err.code(), "mask_key_required");
}

// --- derive_hex_raw_array (group_key) ---

/// The raw-hex kernel reproduces the oracle's `derive(mask_key, namespace,
/// str(value).encode())[:length//2].hex()` byte-for-byte over a string column, for the config
/// `length` bounds 8/16/64. This is the direct Rust-level parity oracle for the group_key path.
#[test]
fn derive_hex_raw_matches_reference_derive() {
    use crate::derive::derive;
    let array = StringArray::from(vec![Some("alice"), Some("bob"), Some("alice"), Some("")]);
    let key = [7u8; 32];
    for hex_chars in [8usize, 16, 64] {
        let out = derive_hex_raw_array(&array, Some(&key), "group_key/tgt", hex_chars, 4).unwrap();
        let output_bytes = hex_chars / 2;
        for row in 0..array.len() {
            let s = array.value(row);
            let digest = derive(&key, "group_key/tgt", s.as_bytes()).unwrap();
            let expected = digest[..output_bytes]
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>();
            assert_eq!(out.value(row), expected, "row {row} hex_chars {hex_chars}");
        }
        // Same group value -> same key (rows 0 and 2 are both "alice").
        assert_eq!(out.value(0), out.value(2));
    }
}

/// Canonicalization-FREE proof: for a decomposed-unicode string, the raw kernel must key on the
/// RAW bytes (matching the oracle), NOT on the NFC-normalized bytes the canonicalizing
/// `derive_array` uses. So `derive_hex_raw_array` must equal a raw `derive(...)` and must
/// DIFFER from `derive_array` on the same input -- proving the raw path is actually taken.
#[test]
fn derive_hex_raw_is_canonicalization_free() {
    use crate::derive::derive;
    // "é" as e + combining acute accent (NOT precomposed): NFC would fold it to U+00E9.
    let decomposed = "e\u{0301}";
    let array = StringArray::from(vec![Some(decomposed)]);
    let key = [3u8; 32];
    let hex_chars = 16usize;

    let raw = derive_hex_raw_array(&array, Some(&key), "ns", hex_chars, 1).unwrap();
    let reference = {
        let digest = derive(&key, "ns", decomposed.as_bytes()).unwrap();
        digest[..hex_chars / 2]
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>()
    };
    assert_eq!(
        raw.value(0),
        reference,
        "raw kernel must match the raw reference"
    );

    // The canonicalizing kernel NFC-normalizes the string, so it derives from different bytes
    // and its hex output must differ -- the guardrail that this test really is exercising the
    // no-canonicalization property, not a coincidental match.
    let canonicalizing =
        derive_array(&array, Some(&key), "ns", Some(hex_chars as isize), 1).unwrap();
    assert_ne!(
        raw.value(0),
        canonicalizing.value(0),
        "a decomposed-unicode string must derive differently under NFC canonicalization"
    );
}

/// EXIT GATE: the raw-hex output is byte-identical at every thread count (each row is
/// independent), including empty-string rows and a mid-column null carried through.
#[test]
fn derive_hex_raw_thread_count_never_changes_output() {
    let values: Vec<Option<String>> = (0..97)
        .map(|i| match i % 5 {
            0 => None,
            1 => Some(String::new()),
            n => Some(format!("row-{i}-{}", "x".repeat(n))),
        })
        .collect();
    let array = StringArray::from(values);
    let key = [9u8; 32];
    for hex_chars in [8usize, 16, 64] {
        let baseline = derive_hex_raw_array(&array, Some(&key), "ns", hex_chars, 1).unwrap();
        for threads in [2usize, 3, 4, 8, 16] {
            let out = derive_hex_raw_array(&array, Some(&key), "ns", hex_chars, threads).unwrap();
            assert_eq!(
                out, baseline,
                "diverged at threads={threads} hex_chars={hex_chars}"
            );
        }
        // A null carries through null; a non-null empty-string row is a valid empty output.
        assert!(baseline.is_null(0));
        assert!(baseline.is_valid(1) && baseline.value(1).len() == hex_chars);
    }
}

/// Guards: a missing/empty key fails closed before any derivation; an odd or out-of-range
/// `hex_chars` is rejected; a non-string array is refused; an empty/all-null column validates
/// nothing (tolerates a wrong-length key), matching the oracle.
#[test]
fn derive_hex_raw_guards_and_degenerate_shapes() {
    let array = StringArray::from(vec![Some("alice")]);
    let key = [0u8; 32];
    assert!(matches!(
        derive_hex_raw_array(&array, Some(&[]), "ns", 16, 1).unwrap_err(),
        BatchError::MaskKeyRequired
    ));
    assert_eq!(
        derive_hex_raw_array(&array, Some(&key), "ns", 15, 1)
            .unwrap_err()
            .code(),
        "group_key_hex_chars_invalid"
    );
    assert_eq!(
        derive_hex_raw_array(&array, Some(&key), "ns", 66, 1)
            .unwrap_err()
            .code(),
        "group_key_hex_chars_invalid"
    );
    // A non-string array declines with the coded reason (defensive: the caller stringifies).
    let ints = int64_array_local(vec![Some(1), Some(2)]);
    assert_eq!(
        derive_hex_raw_array(&ints, Some(&key), "ns", 16, 1)
            .unwrap_err()
            .code(),
        "group_key_input_not_string"
    );
    // Empty / all-null validate nothing: a wrong-length key must be tolerated.
    let empty = StringArray::from(Vec::<Option<&str>>::new());
    assert_eq!(
        derive_hex_raw_array(&empty, Some(&[0u8; 20]), "", 16, 4)
            .unwrap()
            .len(),
        0
    );
    let all_null = StringArray::from(vec![None::<&str>, None]);
    let out = derive_hex_raw_array(&all_null, Some(&[0u8; 20]), "", 16, 4).unwrap();
    assert_eq!(out.null_count(), 2);
    // A non-null row present -> the wrong-length key fails closed with the reference code.
    let err = derive_hex_raw_array(&array, Some(&[0u8; 20]), "ns", 16, 1).unwrap_err();
    assert_eq!(err.code(), "seed_wrong_length");
}

fn int64_array_local(v: Vec<Option<i64>>) -> arrow_array::Int64Array {
    arrow_array::Int64Array::from(v)
}

/// Type-agnostic: the parallel index path is byte-identical at threads {1,8} for int64 and bool,
/// same argument as the string case (the machinery branches only on the null mask).
#[test]
fn derive_index_thread_invariance_for_non_string_types() {
    use arrow_array::{BooleanArray, Int64Array};
    let key = [3u8; 32];
    let int64 = Int64Array::from(
        (0..60)
            .map(|i| {
                if i % 4 == 0 {
                    None
                } else {
                    Some(i as i64 * 7 - 3)
                }
            })
            .collect::<Vec<_>>(),
    );
    assert_eq!(
        derive_index_array(&int64, Some(&key), "ns", 997, 8).unwrap(),
        derive_index_array(&int64, Some(&key), "ns", 997, 1).unwrap(),
    );
    let boolean = BooleanArray::from(
        (0..60)
            .map(|i| if i % 3 == 0 { None } else { Some(i % 2 == 0) })
            .collect::<Vec<_>>(),
    );
    assert_eq!(
        derive_index_array(&boolean, Some(&key), "ns", 64, 8).unwrap(),
        derive_index_array(&boolean, Some(&key), "ns", 64, 1).unwrap(),
    );
}
