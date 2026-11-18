"""hash strategy (engine-v2 S9): joinability-preserving deterministic token.

Re-keyed onto S3 (S9 spec §8 path #1): the masked token is
`derive(job_seed, namespace, _canonicalize_source(value)).hex()`, optionally
truncated. Same source value -> same token within a namespace (joinability
preserved), byte-stable across runs/processes. NOT the legacy
`hmac_hex(column_key, ...)` / `deterministic_hash(s, seed:int)` path.

The canonical source bytes come from S5's `_canonicalize_source` (R3); the
strategy does not do its own `.encode`. A namespace is required (the token is
keyed on it); a hash column without one is a wiring error.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from decoy_engine import reasons
from decoy_engine.determinism import derive
from decoy_engine.execution._adapter import (
    StrategyContext,
    StrategyOption,
    pandas_column_to_kernel_input,
    provider_config_to_dict,
)
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._exact_int_sources import exact_int_arrow
from decoy_engine.generation.pool._events import QualityWarning
from decoy_engine.kernel import hash_array
from decoy_engine.plan._types import ColumnSeed

# The hex length of the HMAC-SHA256 digest `derive` returns: no token is longer.
_DIGEST_HEX_LENGTH = 64


def hash_truncate(cfg: dict[str, Any]) -> int | None:
    """The positive `truncate` the kernel slices tokens to, or None for the full digest."""
    raw = cfg.get("truncate")
    return raw if isinstance(raw, int) and raw > 0 else None


class HashStrategyHandler:
    """Deterministic joinability-preserving hash via derive(...)."""

    name: str = "hash"
    namespace_required: bool = True
    join_safe: bool = True
    wizard_options: tuple[StrategyOption, ...] = ()
    offer_in_wizard: bool = True

    def output_string_width(self, provider_config: Sequence[tuple[str, Any]]) -> int | None:
        """The UTF-8 width of every non-null token `run` writes (the lifecycle estimate)."""
        truncate = hash_truncate(provider_config_to_dict(provider_config))
        return _DIGEST_HEX_LENGTH if truncate is None else min(truncate, _DIGEST_HEX_LENGTH)

    def run(
        self,
        df: pd.DataFrame,
        column: str,
        plan: ColumnSeed,
        ctx: StrategyContext,
    ) -> tuple[pd.DataFrame, list[QualityWarning]]:
        if plan.namespace is None:
            raise StrategyError(
                code=reasons.runtime.HASH_REQUIRES_NAMESPACE,
                strategy="hash",
                message=f"column {column!r} uses the hash strategy but has no namespace.",
            )
        cfg = provider_config_to_dict(plan.provider_config)
        truncate = hash_truncate(cfg)

        # An ungated integer column with nulls was widened to float64 in the frame; its exact
        # typed Arrow values were recorded at ingest and key the hash instead.
        exact = exact_int_arrow(ctx, getattr(ctx, "current_table", ""), column, df[column])

        # getattr: handlers are also driven with hand-built contexts that predate this field.
        seq = getattr(ctx, "seq_native", None)
        if seq is not None:
            tokens = seq.hash_column(
                ctx,
                df,
                column,
                namespace=plan.namespace,
                mask_key=ctx.mask_key,
                truncate=truncate,
                exact=exact,
            )
            if tokens is not None:
                df[column] = tokens
                return df, []

        masked = hash_array(
            exact if exact is not None else pandas_column_to_kernel_input(df[column]),
            seed=ctx.mask_key,
            namespace=plan.namespace,
            truncate=truncate,
            derive_func=derive,
        )
        df[column] = masked.to_pylist()
        return df, []
