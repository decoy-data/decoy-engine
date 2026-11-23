"""Position-keyed selection for non-deterministic REUSE Faker.

The pool is built exactly as before. Only the SELECTION changes: for the non-null row at
ordinal `g = ctx.row_offset + i` the value is
`pool.values[derive_index(job_seed, selection_namespace, encode_int(g), pool.size)]`.
`encode_int` is the integer encoding `derive_index_batch` applies to a uint64 key column,
so a native route can later reproduce the draw byte for byte.

The key is `job_seed`, never `mask_key`: non-deterministic mode generates fresh synthetic
values and does not re-identify a source value, so it stays off the secret-derived key.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd
import pyarrow as pa

from decoy_engine import reasons
from decoy_engine.execution._adapter import (
    column_draw_identity,
    context_draw_identity,
)
from decoy_engine.execution._positional_keys import positional_key_array
from decoy_engine.generation.pool import (
    ComputedDrawSpec,
    choice_from_index,
    computed_selection_namespace,
    derive_pool_indices,
    derive_validated_indices,
    int_from_index,
    uuid_from_hex,
)
from decoy_engine.kernel._scalar import hash_array

_DOMAIN_CODE = reasons.runtime.FAKER_POSITION_OUT_OF_DOMAIN
_COMPUTED_DOMAIN_CODE = reasons.runtime.COMPUTED_DRAW_POSITION_OUT_OF_DOMAIN


def faker_selection_namespace(table: str, column: str, namespace: str | None) -> str:
    """The namespace that keys the draw: the configured one, else a per-column default.

    The default is `column_draw_identity` under a `faker-nd/` prefix. `None` and `""` both
    mean "not configured"."""
    if namespace:
        return namespace
    return f"faker-nd/{column_draw_identity(table, column)}"


def resolve_selection_namespace(ctx: Any, column: str, namespace: str | None) -> str:
    """`faker_selection_namespace` from the context, failing closed on an unstamped table."""
    if namespace:
        return namespace
    return f"faker-nd/{context_draw_identity(ctx, column, strategy='faker')}"


def positional_pool_indices(
    n: int,
    *,
    row_offset: int,
    job_seed: bytes,
    namespace: str,
    pool_size: int,
    gate_positions: np.ndarray[Any, Any] | None = None,
    domain_code: str = _DOMAIN_CODE,
) -> np.ndarray[Any, Any]:
    """One pool index per full-table row, in one batch call.

    Without a `when:` gate the rows are `row_offset .. row_offset + n - 1`; under a gate they are
    the selected rows' full-table positions (C8-iii-d). Uses the compiled `derive_index_batch`
    when the native companion is present and the byte-identical reference otherwise, as
    `PoolSampler` does."""
    try:
        keys = positional_key_array(row_offset, n, code=domain_code, gate_positions=gate_positions)
        return derive_validated_indices(
            keys, mask_key=job_seed, namespace=namespace, pool_size=pool_size
        )
    except BaseException:
        del job_seed
        raise


def _expand_nulls(values: pa.Array, na_mask: np.ndarray[Any, Any], out: pa.DataType) -> pa.Array:
    """`values` (one per non-null row, or one per row when already full length) with source nulls
    re-emitted in place, typed `out`."""
    n = len(na_mask)
    if len(values) == n:
        items = values.to_pylist()
        return pa.array([None if na_mask[i] else items[i] for i in range(n)], type=out)
    full: list[Any] = [None] * n
    for pos, value in zip(np.flatnonzero(~na_mask).tolist(), values.to_pylist(), strict=True):
        full[pos] = value
    return pa.array(full, type=out)


def computed_mask_draw(
    source: pd.Series,
    *,
    spec: ComputedDrawSpec,
    mode: Literal["deterministic", "positional"],
    seed: bytes,
    namespace: str,
    row_offset: int = 0,
    gate_positions: np.ndarray[Any, Any] | None = None,
) -> pa.Array:
    """One computed value per source row: uuid, bounded integer or element choice.

    `deterministic` keys each value on the source value under `seed` (the mask key), so equal
    sources give equal outputs on both sides of a key. `positional` keys on the row's full-table
    number under `seed` (the job seed) and never reads a source value. A null source row stays null
    in both. Index draws go through the shared `derive_pool_indices` and `positional_pool_indices`;
    the uuid draw keys the same canonical source through `kernel.hash_array`. The key namespace is
    the column's plus the provider, so a computed draw never shares index material with a pool.
    """
    try:
        n = len(source)
        na_mask = source.isna().to_numpy()
        keyed_ns = computed_selection_namespace(namespace, spec.provider)
        nonnull = source.iloc[np.flatnonzero(~na_mask)]
        if spec.family == "uuid":
            if mode == "deterministic":
                tokens = hash_array(nonnull.tolist(), seed=seed, namespace=keyed_ns, truncate=32)
            else:
                keys = positional_key_array(
                    row_offset, n, code=_COMPUTED_DOMAIN_CODE, gate_positions=gate_positions
                )
                tokens = hash_array(keys, seed=seed, namespace=keyed_ns, truncate=32)
            return _expand_nulls(uuid_from_hex(tokens), na_mask, spec.output_type)
        if mode == "deterministic":
            idx = derive_pool_indices(nonnull, seed=seed, namespace=keyed_ns, pool_size=spec.count)
        else:
            idx = positional_pool_indices(
                n,
                row_offset=row_offset,
                job_seed=seed,
                namespace=keyed_ns,
                pool_size=spec.count,
                gate_positions=gate_positions,
                domain_code=_COMPUTED_DOMAIN_CODE,
            )
        if spec.family == "int":
            drawn = int_from_index(idx, lo=spec.lo, step=spec.step)
        else:
            drawn = pa.array(choice_from_index(idx, spec.elements), type=spec.output_type)
        return _expand_nulls(drawn, na_mask, spec.output_type)
    except BaseException:
        del seed
        raise


__all__ = [
    "computed_mask_draw",
    "faker_selection_namespace",
    "positional_pool_indices",
    "resolve_selection_namespace",
]
