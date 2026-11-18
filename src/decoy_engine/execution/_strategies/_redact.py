"""redact strategy (engine-v2 S9): replace non-null values with a constant.

Logic carried from V1 `transforms/redact.py` (config key `redact_with`, default
"REDACTED"; nulls preserved; extension dtype dropped to object so the string
writes cleanly). No backend, no determinism keying.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd
import pyarrow as pa

from decoy_engine.execution._adapter import (
    StrategyContext,
    StrategyOption,
    option,
    provider_config_to_dict,
)
from decoy_engine.generation.pool._events import QualityWarning
from decoy_engine.kernel import redact_array
from decoy_engine.plan._types import ColumnSeed

_DEFAULT_REDACT_WITH = "REDACTED"


def redact_with_of(cfg: dict[str, Any]) -> Any:
    """The replacement value `run` writes: `redact_with`, else the default."""
    return cfg.get("redact_with", _DEFAULT_REDACT_WITH)


class RedactHandler:
    """Replace every non-null value in the column with a fixed string."""

    name: str = "redact"
    namespace_required: bool = False
    join_safe: bool = False
    wizard_options: tuple[StrategyOption, ...] = (option("redact_with", "str", "XXXX"),)
    offer_in_wizard: bool = True

    def output_string_width(self, provider_config: Sequence[tuple[str, Any]]) -> int | None:
        """The UTF-8 width of every non-null cell `run` writes, None when it is not a str."""
        value = redact_with_of(provider_config_to_dict(provider_config))
        return len(value.encode("utf-8")) if isinstance(value, str) else None

    def run(
        self,
        df: pd.DataFrame,
        column: str,
        plan: ColumnSeed,
        ctx: StrategyContext,
    ) -> tuple[pd.DataFrame, list[QualityWarning]]:
        cfg = provider_config_to_dict(plan.provider_config)
        redact_with = redact_with_of(cfg)
        col = df[column]
        try:
            masked = redact_array(pa.array(col, from_pandas=True), redact_with=redact_with)
            df[column] = masked.to_pylist()
        except pa.ArrowException:
            if pd.api.types.is_extension_array_dtype(col.dtype):
                col = col.astype(object)
            df[column] = col.where(col.isna(), redact_with)
        return df, []
