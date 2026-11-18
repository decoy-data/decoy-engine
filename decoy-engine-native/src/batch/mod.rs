//! The pure row-loop: validate, canonicalize, derive, hex-encode every row of one Arrow array.
//!
//! Split out from `arrow_ffi` so it has no PyO3 dependency at all: the allocation-bound test
//! (`tests/allocation_bound.rs`) and any other Rust-only harness calls this directly, over a
//! real arrow-rs array, with no Python interpreter involved.

mod error;
mod index;
mod ranges;
mod raw;
mod string;

#[cfg(test)]
mod tests;

pub use error::{BatchError, PoolSize};
pub use index::{derive_index_array, derive_index_array_typed};
pub use raw::derive_hex_raw_array;
pub use string::derive_array;
