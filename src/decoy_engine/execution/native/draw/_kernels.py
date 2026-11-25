"""The kernels one run binds for a computed Faker draw, and the backend that binding implies.

A computed draw runs one of two kernels: a `uuid` keys a hash (hash kernel), every other computed
draw gathers through the index kernel. A pool draw also uses the index kernel. The two kernels
load and self-test independently, so a run can hold either, both or neither. This record is the
one place that says which compiled kernel a variant needs and which backend it ran on; the
sequential route reads `ready` to decide admission and both routes read `backend` for the metric,
so the two can never disagree about what ran.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from decoy_engine.execution._operator_registry import PYTHON_SCALAR, RUST_COMPANION
from decoy_engine.execution.native._index_ext import reference_index_derivation
from decoy_engine.generation.pool import ComputedDrawSpec
from decoy_engine.providers_v2 import FAMILY_UUID

if TYPE_CHECKING:
    from decoy_engine.execution.native._crypto_ext import KeyedDerivationKernel
    from decoy_engine.execution.native._index_ext import IndexDerivationKernel

__all__ = ["BoundFakerKernel"]


@dataclass(frozen=True)
class BoundFakerKernel:
    """The index and hash kernels one run draws faker columns with, and the thread budget.

    `kernel` is the compiled index kernel when `compiled`, else the pure-Python reference; both
    derive byte-identical indices (INDEX_KAT). `hash_kernel` is the compiled hash kernel, or None
    when it did not load or failed its self-test (the reference hash is byte-identical too).
    A route that has no reference leg declines through `ready`."""

    kernel: IndexDerivationKernel
    native_threads: int | None
    compiled: bool
    hash_kernel: KeyedDerivationKernel | None = None

    @classmethod
    def bind(
        cls,
        index_kernel: IndexDerivationKernel | None,
        native_threads: int | None,
        hash_kernel: KeyedDerivationKernel | None = None,
    ) -> BoundFakerKernel:
        """Bind the run's kernels. A missing index kernel (None) binds the byte-identical
        reference and `compiled=False`, so the kernel and its status come from this one decision."""
        if index_kernel is None:
            return cls(reference_index_derivation(), native_threads, False, hash_kernel)
        return cls(index_kernel, native_threads, True, hash_kernel)

    def ready(self, spec: ComputedDrawSpec | None) -> bool:
        """True when the compiled kernel `spec`'s variant runs is bound (None means a pool draw)."""
        if isinstance(spec, ComputedDrawSpec) and spec.family == FAMILY_UUID:
            return self.hash_kernel is not None
        return self.compiled

    def backend(self, spec: ComputedDrawSpec | None) -> str:
        """The backend a draw of `spec` runs on: the compiled kernel its variant uses, else the
        reference."""
        return RUST_COMPANION if self.ready(spec) else PYTHON_SCALAR
