"""composite routing for the execution adapter (engine-v2 S9).

A composite WorkNode (kind == "composite") writes multiple coherent output
columns in ONE pass via the S8 `CompositeGenerator.generate_bundle` (S9 spec
§6.2). The registry binding for a composite is a `CompositeAdapter` whose
`generate()` raises `composite_requires_bundle_path`; the actual generator is
built here via the factory + the whole-tuple namespace the S8 step-2.5
auto-binding produced (resolved through `namespace_registry.for_column(table,
sorted(output_columns))`). The deterministic key is the first (sorted) output
column's source values; non-deterministic mode ignores the source.
"""

from __future__ import annotations

import pandas as pd

from decoy_engine import reasons
from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution._runner import WorkNode
from decoy_engine.generation.composite import COMPOSITES
from decoy_engine.generation.pool._events import QualityWarning
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.providers_v2._adapter import ProviderSpec


class CompositeHandler:
    """Runs a composite node's generate_bundle and writes its output columns."""

    name: str = "<composite>"

    def run(
        self,
        df: pd.DataFrame,
        node: WorkNode,
        ctx: StrategyContext,
    ) -> tuple[pd.DataFrame, list[QualityWarning]]:
        coherent_namespace = ctx.namespace_registry.for_column(node.table, node.columns)
        if coherent_namespace is None:
            raise ExecutionError(
                code=reasons.runtime.COMPOSITE_NAMESPACE_UNRESOLVED,
                message=(
                    f"composite group ({node.table!r}, {node.columns}) has no namespace "
                    "binding; build_namespace_registry should auto-bind the whole tuple."
                ),
            )
        col_seed = node.plan_slice
        if not isinstance(col_seed, ColumnSeed):
            raise ExecutionError(
                code=reasons.runtime.UNSUPPORTED_STRATEGY,
                message=f"composite node {node.columns} has no ColumnSeed plan slice.",
            )

        descriptor = COMPOSITES.get(node.provider or "")
        if descriptor is None:
            raise ExecutionError(
                code=reasons.runtime.UNSUPPORTED_STRATEGY,
                message=f"unknown composite provider {node.provider!r}.",
            )
        provider_config = dict(col_seed.provider_config)
        if descriptor.variable_output:
            # The bundle declaration (a list of {column, provider, optional config} dicts) rides
            # in provider_config["bundle"]. Plan-compile has validated the wiring and the
            # generator's own constructor rejects a malformed bundle; only the container type is
            # checked here, because generation must not raise execution errors.
            bundle_decl = provider_config.get("bundle") or []
            if not isinstance(bundle_decl, list):
                raise ExecutionError(
                    code=reasons.runtime.COMPOSITE_CUSTOM_BUNDLE_SHAPE,
                    message=(
                        f"composite_custom on {node.columns}: provider_config['bundle'] "
                        f"must be a list, got {type(bundle_decl).__name__}."
                    ),
                )
        generator = descriptor.factory(coherent_namespace, ctx.registry, provider_config)

        deterministic = col_seed.deterministic
        # DE-02 seam: a deterministic composite maps a real source value to a
        # coherent synthetic bundle -- keyed re-identification surface, so it draws
        # from mask_key. Non-deterministic mode ignores the source (pure
        # generation) and stays on job_seed.
        spec = ProviderSpec(
            locale=None,
            deterministic=deterministic,
            namespace=coherent_namespace if deterministic else None,
            seed=ctx.mask_key if deterministic else ctx.job_seed,
            extra=dict(col_seed.provider_config),
        )
        source = df[node.columns[0]] if deterministic else None
        bundle = generator.generate_bundle(
            spec, len(df), source=source, deterministic=deterministic
        )
        for out_col, series in bundle.items():
            if out_col not in df.columns:
                # A composite that cannot write a declared output column is a
                # wiring error, not a silent partial-write (Dennis slice-2h M1).
                raise ExecutionError(
                    code=reasons.runtime.COMPOSITE_OUTPUT_COLUMN_MISSING,
                    message=(
                        f"composite {node.provider!r} produced output column {out_col!r} "
                        f"which is not in table {node.table!r}; columns={node.columns}."
                    ),
                )
            df[out_col] = list(series)
        return df, []
