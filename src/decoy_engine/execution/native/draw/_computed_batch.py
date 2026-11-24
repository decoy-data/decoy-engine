"""One batch of a deterministic computed Faker draw, shared by the sequential and out-of-core routes.

A computed draw (`uuid`, exact-string `random_choice`) has no pool. Its value is the keyed
kernel's output for the source value: the key namespace is the column's plus the provider, a
choice gathers from the element table through the index kernel, and a uuid takes 32 hex digits
from the keyed hash and lays them out as an RFC 9562 version 4 string. The routes differ only in
how they bind their kernels and where their keys come from, so the choice of namespace, the
uuid-or-choice branch and the hash width live here and nowhere else.

`hash_kernel` is the bound compiled hash kernel, or None to use the reference hash, which is
byte-identical (the keyed-derivation known-answer vectors). A route that must not run a
reference declines at admission before it reaches this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa

from decoy_engine.execution.native._operator_step import sample_faker_array
from decoy_engine.generation.pool import (
    ComputedDrawSpec,
    computed_selection_namespace,
    uuid_from_hex,
)
from decoy_engine.kernel import hash_array
from decoy_engine.providers_v2 import FAMILY_UUID

if TYPE_CHECKING:
    from decoy_engine.execution.native._crypto_ext import KeyedDerivationKernel
    from decoy_engine.execution.native._index_ext import IndexDerivationKernel

__all__ = ["UUID_HEX_DIGITS", "deterministic_computed_array", "keyed_uuid_array"]

UUID_HEX_DIGITS = 32


def keyed_uuid_array(
    values: pa.Array | pa.ChunkedArray,
    *,
    key: bytes,
    namespace: str,
    hash_kernel: KeyedDerivationKernel | None,
    native_threads: int | None,
) -> pa.Array:
    """UUID strings from `values` keyed under `key` and the selection `namespace`; null stays null."""
    try:
        if hash_kernel is None:
            digits = hash_array(values, seed=key, namespace=namespace, truncate=UUID_HEX_DIGITS)
        else:
            digits = hash_kernel.derive_batch(
                values,
                mask_key=key,
                namespace=namespace,
                truncate=UUID_HEX_DIGITS,
                native_threads=native_threads,
            )
        return uuid_from_hex(digits)
    except BaseException:
        del key
        raise


def deterministic_computed_array(
    values: pa.Array | pa.ChunkedArray,
    spec: ComputedDrawSpec,
    *,
    column_namespace: str,
    mask_key: bytes,
    index_kernel: IndexDerivationKernel,
    hash_kernel: KeyedDerivationKernel | None,
    native_threads: int | None,
) -> pa.Array:
    """The exact-string computed values of one batch, each source value keyed under the mask key."""
    try:
        namespace = computed_selection_namespace(column_namespace, spec.provider)
        if spec.family == FAMILY_UUID:
            return keyed_uuid_array(
                values,
                key=mask_key,
                namespace=namespace,
                hash_kernel=hash_kernel,
                native_threads=native_threads,
            )
        return sample_faker_array(
            values,
            pool=spec,
            namespace=namespace,
            mask_key=mask_key,
            index_kernel=index_kernel,
            native_threads=native_threads,
        )
    except BaseException:
        del mask_key
        raise
