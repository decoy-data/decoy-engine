//! Error and pool-size types shared by every batch kernel.

use crate::canonicalize::CanonError;
use crate::derive::DeriveError;

/// Everything that can go wrong deriving a batch, independent of how the array arrived (Python
/// FFI import or a Rust-constructed array in a test).
///
/// Seed-length and namespace validation are NOT here: they live inside `derive::derive`, fired
/// per non-null row, because the reference (`_ReferenceKeyedDerivation.derive_batch`) only
/// validates them there too. An empty or all-null batch never calls `derive()` in the
/// reference, so it must never raise here either; a batch with at least one non-null row still
/// surfaces `BatchError::Derive` with the reference's own `seed_wrong_length` /
/// `namespace_empty` code the moment that row is reached.
#[derive(Debug)]
pub enum BatchError {
    Canon(CanonError),
    Derive(DeriveError),
    /// Missing or empty mask key (fail-before-output; no row has been touched yet). Mirrors
    /// `_require_mask_key`, which the reference calls once, unconditionally, before its loop
    /// -- unlike seed length, this check does not depend on there being a non-null row.
    MaskKeyRequired,
    /// The total output size for the batch would exceed `i32::MAX`, which a `StringArray`'s i32
    /// offset buffer cannot represent. The pre-1.5 `StringBuilder` path had the same i32 ceiling
    /// (a >2GB batch is already outside this kernel's per-batch contract; the engine chunks well
    /// under it), but silent wrapping would corrupt offsets, so we fail closed instead.
    OffsetOverflow,
    /// `pool_size < 1` (zero or negative) for `derive_index_batch`. Mirrors the Python
    /// `derive_index`'s `pool_size_invalid`, kept distinct from overflow so a caller inspecting the
    /// code can tell underflow from overflow.
    PoolSizeInvalid,
    /// `pool_size > 2**56` for `derive_index_batch` (the modulo-bias ceiling; `2**56` is accepted).
    /// Mirrors the Python `derive_index`'s `pool_size_overflow`.
    PoolSizeOverflow,
    /// `pool_size` was not a Python `int`. For a non-COMPARABLE non-int (a `str`, an object), the
    /// reference raises `TypeError` from its own `pool_size > _POOL_SIZE_MAX` comparison INSIDE
    /// `derive_index` -- called per non-null row, after that row is canonicalized, and never for an
    /// all-null batch. The boundary is deliberately STRICTER for an out-of-contract non-int NUMERIC
    /// (e.g. `1.5`, which the reference would compare and then modulo): it requires an actual int.
    /// That is sound under the frozen `pool_size: int` contract; what matters for parity is the
    /// ORDERING, which this variant fixes -- the rejection lands exactly where the numeric pool
    /// guards are (after canon(first non-null), skipped when nothing is non-null), NOT eagerly at
    /// the PyO3 boundary, and the boundary maps it to `TypeError` rather than a coded `ValueError`.
    PoolSizeType,
    /// `derive_hex_raw_batch` received an array that is not an Arrow `Utf8` (`pa.string()`) column.
    /// The group_key native path stringifies its sibling column in Python (`Series.astype(str)`)
    /// and hands the kernel a `pa.string()` array, so any other type is a wiring error, not a
    /// route the raw-hex kernel supports. Defensive: fails closed rather than mis-reading buffers.
    RawInputNotString,
    /// `derive_hex_raw_batch` received a `hex_chars` that is not an even count in `[2, 64]`. The
    /// Python wrapper resolves it from the config's even `length` in `[8, 64]` before the call,
    /// so this is a defensive fail-closed for an out-of-contract truncation width.
    RawHexCharsInvalid,
}

/// The `pool_size` argument to `derive_index_array_typed`. `NotAnInteger` carries a DEFERRED
/// rejection: a non-int `pool_size` must not short-circuit ahead of the Arrow import and the
/// first-non-null canonicalization (see `BatchError::PoolSizeType`), so the boundary passes the
/// non-int case through as data and lets the pool guard reject it in the correct precedence slot.
#[derive(Clone, Copy, Debug)]
pub enum PoolSize {
    Int(i64),
    NotAnInteger,
}

impl From<i64> for PoolSize {
    fn from(n: i64) -> Self {
        PoolSize::Int(n)
    }
}

impl From<CanonError> for BatchError {
    fn from(e: CanonError) -> Self {
        BatchError::Canon(e)
    }
}

impl From<DeriveError> for BatchError {
    fn from(e: DeriveError) -> Self {
        BatchError::Derive(e)
    }
}

impl BatchError {
    pub fn code(&self) -> &str {
        match self {
            BatchError::Canon(e) => e.code,
            BatchError::Derive(e) => e.code,
            BatchError::MaskKeyRequired => "mask_key_required",
            BatchError::OffsetOverflow => "native_offset_overflow",
            BatchError::PoolSizeInvalid => "pool_size_invalid",
            BatchError::PoolSizeOverflow => "pool_size_overflow",
            BatchError::PoolSizeType => "pool_size_type",
            BatchError::RawInputNotString => "group_key_input_not_string",
            BatchError::RawHexCharsInvalid => "group_key_hex_chars_invalid",
        }
    }

    pub fn detail(&self) -> String {
        match self {
            BatchError::Canon(e) => e.detail.clone(),
            BatchError::Derive(e) => e.detail.clone(),
            BatchError::MaskKeyRequired => {
                "mask_key is required and must be non-empty; refusing to emit unkeyed output"
                    .to_string()
            }
            BatchError::OffsetOverflow => {
                "batch output exceeds the i32 StringArray offset limit (~2GB); split the batch"
                    .to_string()
            }
            BatchError::PoolSizeInvalid => "pool_size must be >= 1".to_string(),
            BatchError::PoolSizeOverflow => "pool_size exceeds the maximum of 2**56".to_string(),
            BatchError::PoolSizeType => "pool_size must be an int".to_string(),
            BatchError::RawInputNotString => {
                "derive_hex_raw_batch accepts only a pa.string() array; got another Arrow type"
                    .to_string()
            }
            BatchError::RawHexCharsInvalid => {
                "hex_chars must be an even count in [2, 64]".to_string()
            }
        }
    }
}
