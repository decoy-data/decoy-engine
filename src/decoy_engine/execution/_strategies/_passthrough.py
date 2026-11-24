"""passthrough strategy (engine-v2 S9): the column is left unchanged.

Exists for completeness + the dispatch-test surface (S9 spec §4 row 1).
"""

from __future__ import annotations

import pandas as pd

from decoy_engine.execution._adapter import StrategyContext, StrategyOption
from decoy_engine.generation.pool._events import QualityWarning
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.plan.column_access import PASSTHROUGH_OUTPUT_IS_INPUT


class PassthroughHandler:
    """No-op handler: returns the dataframe unchanged."""

    name: str = "passthrough"
    namespace_required: bool = False
    join_safe: bool = False
    wizard_options: tuple[StrategyOption, ...] = ()
    offer_in_wizard: bool = True
    # `run` returns the frame unchanged, so an output cell is the input cell. The fact is the
    # plan's, so the lifecycle estimate and the post-scan writer query read the same one.
    output_is_input: bool = PASSTHROUGH_OUTPUT_IS_INPUT

    def run(
        self,
        df: pd.DataFrame,
        column: str,
        plan: ColumnSeed,
        ctx: StrategyContext,
    ) -> tuple[pd.DataFrame, list[QualityWarning]]:
        return df, []
