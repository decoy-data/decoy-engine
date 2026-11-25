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
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc


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
    # The same values as one Arrow array, for the vectorized take (`pool_take`). Set only by
    # generation's faker pool, which holds both forms on purpose: the frozen object array stays
    # for the keyed and bundle paths that gather one value at a time.
    # Keyword-only so a subclass's positional field (`BundlePool.output_columns`) keeps its place.
    arrow: pa.Array[Any] | None = field(default=None, repr=False, compare=False, kw_only=True)

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


# The smallest a STRING pool value can cost: CPython's empty `str` object plus its 8-byte array
# slot. Only a pool known to hold strings may be floored with it: an int, float or None can
# cost less (small ints and None are shared singletons that cost nothing beyond the slot).
MIN_BYTES_PER_VALUE = sys.getsizeof("") + 8

# `PoolBuilder.build` holds these at once per value, on top of the value object itself:
# the adapter's result list, `list(raw_values)`, the object array and `tolist()` (four 8-byte
# pointers), and one `set` slot for the distinct count (CPython stores a pointer and a cached
# hash, 16 bytes, and never fewer slots than entries). The value objects are shared across
# these containers, so they count once. The array slot is the first of the four pointers; this
# adds the other three and the set slot.
_POINTER_BYTES = 8
_SET_SLOT_BYTES = 16
_HELD_OVERHEAD_BYTES = 3 * _POINTER_BYTES + _SET_SLOT_BYTES
# Floor per value for a pool of strings.
BUILD_HELD_BYTES_PER_VALUE = MIN_BYTES_PER_VALUE + _HELD_OVERHEAD_BYTES
# Floor per value for a pool of any other type: the array slot and the held overhead, with the
# values themselves counted as free because they may be shared singletons.
BUILD_HELD_BYTES_PER_VALUE_ANY = _POINTER_BYTES + _HELD_OVERHEAD_BYTES


def measured_pool_bytes(pool: ValuePool) -> int:
    """Resident bytes of a built pool: each string object's own size plus its 8-byte array slot.

    The one pool-byte function: `PoolCache` budgets with it and the out-of-core run reserves
    with it, so a pool that fits one ledger fits the other. A character-count estimate measured
    from 0.5x to 2.6x off the real size depending on string length, which let the two ledgers
    disagree. A pool that retains its Arrow form counts the root buffers it keeps alive."""
    values = pool.values
    arrow_bytes = 0 if pool.arrow is None else _arrow_retained_bytes(pool.arrow)
    if values.dtype != object:
        return int(values.nbytes) + arrow_bytes
    return sum(sys.getsizeof(v) for v in values) + 8 * len(values) + arrow_bytes


def _arrow_retained_bytes(array: pa.Array[Any]) -> int:
    """Bytes of every distinct root buffer ``array`` keeps alive.

    A sliced or IPC-read buffer is a zero-copy view that holds its parent (Arrow's memory model,
    `pyarrow.Buffer.parent`), so a one-value view of a large message body keeps the whole body.
    """
    roots: dict[tuple[int, int], int] = {}
    _collect_arrow_roots(array, roots)
    return sum(roots.values())


# Accessors pyarrow gives a nested array for its child arrays. `Array.buffers()` already flattens
# every child's buffers, so the walk exists only to reach what it skips: a dictionary, wherever it
# sits. A layout pyarrow adds later is covered by its accessor name or by `field(i)`, and the
# type-parametrized test in test_value_pool.py fails when one is not.
_VISITS = [0]  # child-visit counter read by the linearity test
_CHILD_ACCESSORS = ("dictionary", "storage", "values", "run_ends", "keys", "items")


def _child_arrays(array: pa.Array[Any]) -> Iterator[pa.Array[Any]]:
    is_map = pa.types.is_map(array.type)
    for name in _CHILD_ACCESSORS:
        if is_map and name == "values":
            continue  # a map's entries struct repeats its keys and items: walking it doubles each level
        try:
            child = getattr(array, name)
        except (AttributeError, NotImplementedError, pa.ArrowException):
            continue
        if isinstance(child, pa.Array):
            yield child
    for i in range(getattr(array.type, "num_fields", 0)):
        try:
            child = array.field(i)
        except (AttributeError, NotImplementedError, TypeError, pa.ArrowException):
            continue
        if isinstance(child, pa.Array):
            yield child


def _collect_arrow_roots(array: pa.Array[Any], roots: dict[tuple[int, int], int]) -> None:
    """Add every root buffer of ``array`` and of everything nested under it to ``roots``.

    A shared root counts once, whichever path reaches it. Each child is visited once per path,
    so the walk is linear in the number of arrays."""
    _VISITS[0] += 1
    for buf in array.buffers():
        if buf is None:
            continue
        while buf.parent is not None:
            buf = buf.parent
        roots[(buf.address, buf.size)] = buf.size
    for child in _child_arrays(array):
        _collect_arrow_roots(child, roots)


def construction_floor(size: int, *, strings: bool) -> int:
    """A floor on the peak bytes `PoolBuilder.build` holds while it builds `size` values.

    Larger than the final pool because the builder keeps four pointer copies and a set of
    the values until it returns. Used to refuse a pool before building it, so it is a floor:
    a pool whose floor exceeds the budget cannot fit however small its values are. `strings`
    is True only when the provider is known to return strings; any other pool uses the
    smaller type-free floor so a pool of ints that fits is never refused."""
    return size * (BUILD_HELD_BYTES_PER_VALUE if strings else BUILD_HELD_BYTES_PER_VALUE_ANY)


def pool_take(pool: pa.Array[Any], indices: np.ndarray[Any, Any]) -> pa.Array[Any]:
    """Gather `pool[indices]` as an Arrow array: the one pooled pick.

    Arrow's `take` is the documented gather for an index array over a value array (the dictionary
    decode pattern). A null in the pool stays null in the output. `PooledSelector.take` and the
    REUSE sampler both pick through this, so a later change to the pick is one edit.
    """
    return pc.take(pool, indices)  # type: ignore[no-untyped-call, unused-ignore]


def _arrow_gather_is_exact(arrow: pa.Array[Any]) -> bool:
    """True when `to_numpy` returns the pool's values and nulls unchanged.

    Only string arrays qualify: they convert to `str` objects with `None` for a null. An integer
    array with a null converts to float64 (rounding values past 2**53, null becomes NaN), and
    temporal types convert to numpy datetimes, so those gather from the object array instead.
    """
    return bool(pa.types.is_string(arrow.type) or pa.types.is_large_string(arrow.type))


def pool_pick(pool: ValuePool, indices: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """The REUSE gather of a built pool as a numpy object array.

    A string pool that carries its Arrow form picks through `pool_take`; any other pool (every
    pool built by `PoolBuilder`, and non-string Arrow forms whose numpy conversion would change
    values or nulls) gathers from the frozen object array. Both give the same values.
    """
    if pool.arrow is not None and _arrow_gather_is_exact(pool.arrow):
        picked: np.ndarray[Any, Any] = pool_take(pool.arrow, indices).to_numpy(zero_copy_only=False)
        return picked
    gathered: np.ndarray[Any, Any] = pool.values[indices]
    return gathered


__all__ = [
    "BUILD_HELD_BYTES_PER_VALUE",
    "BUILD_HELD_BYTES_PER_VALUE_ANY",
    "MIN_BYTES_PER_VALUE",
    "ValuePool",
    "_freeze_array",
    "construction_floor",
    "measured_pool_bytes",
    "pool_pick",
    "pool_take",
]


def _typing_compat() -> Any:
    """Stub for mypy; not used at runtime."""
    return None
