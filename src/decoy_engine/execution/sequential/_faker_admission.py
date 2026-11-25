"""Sequential faker admission: the live provider variant, and the kernels that variant runs.

A faker column runs one of two native legs. A pool column selects through the index kernel. A
`uuid` draw keys a hash, so it needs the hash kernel instead. The kernels load once for the run
and each is self-tested when it loads (`load_compiled_*_kernel`), so a column is admitted only
when the kernel its resolved variant will run is bound and passed that test. A column the
variant cannot run stays on pandas, which draws the same bytes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from decoy_engine.execution._adapter import provider_config_to_dict
from decoy_engine.execution.native._crypto_ext import (
    CryptoExtensionUnavailableError,
    KeyedDerivationKernel,
)
from decoy_engine.execution.native._index_ext import IndexDerivationKernel
from decoy_engine.execution.native._provider_class import resolve_faker_variant
from decoy_engine.execution.native._real_type_admission import (
    faker_provider_decline,
    string_source_type_rejection,
)
from decoy_engine.execution.native._requirements import faker_pool_precondition_met_seed
from decoy_engine.execution.native.draw import BoundFakerKernel
from decoy_engine.execution.out_of_core._hash_native import REASON_UNAVAILABLE

if TYPE_CHECKING:
    from decoy_engine.plan._types import ColumnSeed
    from decoy_engine.providers_v2 import ProviderRegistry

__all__ = ["bound_decline", "faker_admit", "load_faker_kernels"]


def load_faker_kernels(
    native_threads: int | None,
    *,
    load_index: Callable[[], IndexDerivationKernel],
    load_hash: Callable[[], KeyedDerivationKernel],
) -> BoundFakerKernel:
    """Bind the index kernel and the hash kernel, each on its own.

    The caller passes the two loaders so they resolve through its module globals at call time,
    which is how a test swaps the companion load (`_sequential_native._load_faker`). A kernel
    that is unavailable binds the byte-identical reference (index) or None (hash), and
    `BoundFakerKernel.ready` then declines the columns that variant cannot run natively, so a
    missing index kernel does not discard a healthy hash kernel or the reverse."""
    try:
        index: IndexDerivationKernel | None = load_index()
    except CryptoExtensionUnavailableError:
        index = None
    try:
        hash_kernel: KeyedDerivationKernel | None = load_hash()
    except CryptoExtensionUnavailableError:
        hash_kernel = None
    return BoundFakerKernel.bind(index, native_threads, hash_kernel)


def faker_admit(
    column: str,
    input_type: pa.DataType,
    seed: ColumnSeed,
    *,
    registry: ProviderRegistry | None = None,
    bound: Any = None,
) -> str | None:
    """Why a faker column stays on Python, or None.

    Composed from the predicates the chunked route already gates on: the live provider variant,
    the ColumnSeed-level deterministic-REUSE precondition, and the exact-`string` source. The
    non-deterministic leg is the REUSE mode only; UNIQUE, MATCH and SCALE need whole-column
    RNG state. A deterministic config the oracle rejects (no namespace) also declines, so the
    handler raises its own coded error. `bound` is the run's kernels: a `uuid` variant needs the
    hash kernel among them."""
    cfg = provider_config_to_dict(seed.provider_config)
    provider_decline = faker_provider_decline(
        column, seed.provider, cfg, runs_computed=True, registry=registry
    )
    if provider_decline is not None:
        return provider_decline[0]
    variant = resolve_faker_variant(seed.provider, cfg, registry)
    spec = variant.spec
    if isinstance(bound, BoundFakerKernel) and not bound.ready(spec):
        return REASON_UNAVAILABLE
    if seed.deterministic:
        if not faker_pool_precondition_met_seed(seed):
            return f"faker_not_deterministic_reuse_variant:{column}"
    elif seed.cardinality_mode != "reuse":
        return f"faker_nondeterministic_mode_stays_python:{column}:{seed.cardinality_mode}"
    return string_source_type_rejection("faker", column, pa.schema([pa.field(column, input_type)]))


def bound_decline(
    registry: ProviderRegistry | None,
    admit: Callable[..., str | None],
    bound: Any,
    column: str,
    input_type: pa.DataType,
    seed: ColumnSeed,
) -> str | None:
    """Why `column` stays on Python for this run's bound kernels, or None to run native.

    Only the faker operator reads the run's registry and kernels: its variant is the live
    registry's, and the kernel it needs depends on that variant."""
    if bound is None:
        return REASON_UNAVAILABLE
    if isinstance(bound, BoundFakerKernel):
        return admit(column, input_type, seed, registry=registry, bound=bound)
    return admit(column, input_type, seed)
