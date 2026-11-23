"""ValuePool: frozen, deterministically-built array of synthetic values + identity.

Built by PoolBuilder, sampled by PoolSampler, cached by PoolCache. Frozen
because mutating a pool mid-job would shift sampling output silently
(no-silent-shift contract per the operating model).

Per S5 spec §2, the **identity tuple** is `(provider, locale, config_hash,
seed, size)`. Five fields. NOT `backend_version` (a Faker patch shifting
output produces a different pool, but caching on backend_version would
force every job to rebuild on every Faker patch; the manifest records
the version separately for audit).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class ValuePool:
    """Frozen synthetic-value array with identity metadata.

    Per S5 spec §2: numpy `setflags(write=False)` on `values` after build
    so a buggy strategy that tries to sort in-place fails loudly rather
    than silently re-keying the deterministic sampler.

    `backend_type` + `backend_version` are sourced from
    `ProviderRegistry.get_capabilities(provider)` (per S4's H1 path),
    NOT from the adapter directly.
    """

    values: np.ndarray[Any, Any]
    provider: str
    locale: str
    config_hash: str
    seed: bytes = field(repr=False)
    size: int
    build_time_ms: float
    backend_type: str
    backend_version: str
    distinct_count: int

    @property
    def identity(self) -> tuple[str, str, str, bytes, int]:
        """The cache key per S5 spec §2 + cross-sprint contracts §2.5."""
        return (self.provider, self.locale, self.config_hash, self.seed, self.size)


def _freeze_array(values: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """Mark a numpy array read-only after build.

    Per S5 spec §2 "Why frozen": a strategy that sorts in place for
    binary search would re-key the deterministic sampler. setflags
    makes the attempt raise rather than silently mutate.
    """
    values.setflags(write=False)
    return values


# The smallest a pool value can cost: CPython's empty `str` object plus its 8-byte array slot.
# `measured_pool_bytes` charges every value at least this much, so `pool_size` times it is a
# true floor for the resident pool.
MIN_BYTES_PER_VALUE = sys.getsizeof("") + 8

# `PoolBuilder.build` holds these at once per value, on top of the string object itself:
# the adapter's result list, `list(raw_values)`, the object array and `tolist()` (four 8-byte
# pointers), and one `set` slot for the distinct count (CPython stores a pointer and a cached
# hash, 16 bytes, and never fewer slots than entries). The string objects are shared across
# these containers, so they count once. `MIN_BYTES_PER_VALUE` already holds one of the four
# pointers; this adds the other three and the set slot.
_POINTER_BYTES = 8
_SET_SLOT_BYTES = 16
BUILD_HELD_BYTES_PER_VALUE = MIN_BYTES_PER_VALUE + 3 * _POINTER_BYTES + _SET_SLOT_BYTES


def measured_pool_bytes(pool: ValuePool) -> int:
    """Resident bytes of a built pool: each string object's own size plus its 8-byte array slot.

    The one pool-byte function: `PoolCache` budgets with it and the out-of-core run reserves
    with it, so a pool that fits one ledger fits the other. A character-count estimate measured
    from 0.5x to 2.6x off the real size depending on string length, which let the two ledgers
    disagree."""
    values = pool.values
    if values.dtype != object:
        return int(values.nbytes)
    return sum(sys.getsizeof(v) for v in values) + 8 * len(values)


def construction_floor(size: int) -> int:
    """A floor on the peak bytes `PoolBuilder.build` holds while it builds `size` values.

    Larger than the final pool because the builder keeps four pointer copies and a set of
    the values until it returns. Used to refuse a pool before building it, so it is a floor:
    a pool whose floor exceeds the budget cannot fit however short its strings are."""
    return size * BUILD_HELD_BYTES_PER_VALUE


__all__ = [
    "BUILD_HELD_BYTES_PER_VALUE",
    "MIN_BYTES_PER_VALUE",
    "ValuePool",
    "_freeze_array",
    "construction_floor",
    "measured_pool_bytes",
]


def _typing_compat() -> Any:
    """Stub for mypy; not used at runtime."""
    return None
