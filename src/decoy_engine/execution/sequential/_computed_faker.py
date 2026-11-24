"""The sequential native leg of a computed Faker draw (`uuid`, exact-string `random_choice`).

A computed draw has no pool. Its native value is the keyed kernel's output, taken through the
entries the pool operator and the hash operator already use. The deterministic draw is the one
`deterministic_computed_array` shares with the out-of-core route; the positional twin gathers
from the element table by row number, or keys a uuid from it. The key namespace is the column's
plus the provider, as on the pandas route, so every route draws the same bytes.

Only an exact-`string` output reaches here: admission (`faker_admit`) declines every other
computed output type with `faker_computed_output_type_unsupported`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc

from decoy_engine import reasons
from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._positional_keys import positional_key_array
from decoy_engine.execution._sequential_native_ops import FAKER
from decoy_engine.execution._strategies._faker_positional import resolve_selection_namespace
from decoy_engine.execution.native._operator_step import sample_faker_array_positional
from decoy_engine.execution.native.draw import deterministic_computed_array, keyed_uuid_array
from decoy_engine.generation.pool import ComputedDrawSpec, computed_selection_namespace
from decoy_engine.providers_v2 import FAMILY_UUID

if TYPE_CHECKING:
    from decoy_engine.execution._sequential_native import SeqNativeRun
    from decoy_engine.execution.sequential._faker_admission import BoundFakerKernels
    from decoy_engine.plan._types import ColumnSeed

__all__ = ["computed_faker_array", "computed_faker_column"]

_POSITION_CODE = reasons.runtime.COMPUTED_DRAW_POSITION_OUT_OF_DOMAIN


def computed_faker_column(
    run: SeqNativeRun,
    ctx: StrategyContext,
    df: pd.DataFrame,
    column: str,
    plan: ColumnSeed,
    spec: ComputedDrawSpec,
) -> list[Any] | None:
    """The computed values for `df[column]`, positionally, or None when the pandas draw runs.

    Every computed column is offered, so a declined one still books its rows. The run's
    decision for the column came from `faker_admit`; the kernel is the faker operator's."""
    gate = run.admitted(ctx, column, FAKER, len(df))
    if gate is None:
        return None
    decision, bound = gate
    values = run._pinned_array(df[column], decision)
    drawn = computed_faker_array(bound, values, spec, ctx, column, plan)
    decision.native_calls += 1  # each leg makes one batch call
    return drawn.to_pylist()


def computed_faker_array(
    bound: BoundFakerKernels,
    values: pa.Array | pa.ChunkedArray,
    spec: ComputedDrawSpec,
    ctx: StrategyContext,
    column: str,
    plan: ColumnSeed,
) -> pa.Array:
    """One batch's exact-string computed values: deterministic keys each source value under the
    mask key (the draw shared with the out-of-core route), positional keys each row's full-table
    number under the job seed.

    A null source stays null; in positional mode it still consumes its row number."""
    if plan.deterministic:
        return deterministic_computed_array(
            values,
            spec,
            column_namespace=str(plan.namespace),
            mask_key=ctx.mask_key,
            index_kernel=bound.kernel,
            hash_kernel=bound.hash_kernel,
            native_threads=bound.native_threads,
        )
    namespace = computed_selection_namespace(
        resolve_selection_namespace(ctx, column, plan.namespace), spec.provider
    )
    gate_positions = getattr(ctx, "gate_positions", None)
    if spec.family != FAMILY_UUID:
        return sample_faker_array_positional(
            values,
            pool=spec,
            row_offset=ctx.row_offset,
            job_seed=ctx.job_seed,
            namespace=namespace,
            index_kernel=bound.kernel,
            native_threads=bound.native_threads,
            missing_mask=None,
            gate_positions=gate_positions,
            code=_POSITION_CODE,
        )
    keys = positional_key_array(
        ctx.row_offset, len(values), code=_POSITION_CODE, gate_positions=gate_positions
    )
    drawn = keyed_uuid_array(
        keys,
        key=ctx.job_seed,
        namespace=namespace,
        hash_kernel=bound.hash_kernel,
        native_threads=bound.native_threads,
    )
    valid = pc.is_valid(values)  # type: ignore[attr-defined, unused-ignore]
    return pc.if_else(valid, drawn, pa.scalar(None, pa.string()))  # type: ignore[attr-defined, unused-ignore]
