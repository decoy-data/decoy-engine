"""Backend-neutral deterministic masking kernel.

The kernel is the shared Arrow boundary for deterministic per-value masking
logic. It does not define FK equality semantics; those live in
``decoy_engine.execution._fk_keys``.
"""

from decoy_engine.kernel._bucket import (
    BucketizeResult,
    SparseLabels,
    TopCodeResult,
    bucketize_array,
    floor_multiple,
    integer_width_exit_mask,
    python_float_str,
    top_code_array,
)
from decoy_engine.kernel._canonicalize import canonicalize_derive_source, encode_int
from decoy_engine.kernel._scalar import (
    hash_array,
    passthrough_array,
    redact_array,
    truncate_array,
)

__all__ = [
    "BucketizeResult",
    "SparseLabels",
    "TopCodeResult",
    "bucketize_array",
    "canonicalize_derive_source",
    "encode_int",
    "floor_multiple",
    "hash_array",
    "integer_width_exit_mask",
    "passthrough_array",
    "python_float_str",
    "redact_array",
    "top_code_array",
    "truncate_array",
]
