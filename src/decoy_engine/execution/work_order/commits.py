"""Gated write-back and per-run state.

Each node runs in place and in order, as on main. A creator's column (`derived`, `group_key`)
is created when its node writes it, so column order and dtype are main's.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from decoy_engine.execution.work_order.compile import WorkOrder
from decoy_engine.execution.work_order.when_reads import reject_when_on_created

if TYPE_CHECKING:
    from decoy_engine.execution._runner import WorkNode
    from decoy_engine.generation.pool import QualityWarning


def stitch_rows(
    df: pd.DataFrame, column: str, produced: pd.Series, positions: np.ndarray[Any, Any]
) -> None:
    """Write a handler's `produced` values for the gated rows into `df[column]` by position.

    The k-th produced value belongs to row `positions[k]`; labels play no part. An existing
    column keeps its dtype rules (`iloc` assignment). A column the frame lacks (a creator such as
    `group_key`) is created with a missing value on every row the gate did not select, the dtype
    pandas gives a partial fill (`df.loc[mask, column] = ...` on main).
    """
    if column in df.columns:
        df.iloc[positions, df.columns.get_loc(column)] = produced.array
    else:
        df[column] = pd.Series(produced.array, index=positions).reindex(range(len(df))).array


class Selection:
    """The positions a gated handler replaced, set by `run_with_when_gate`; None = every row."""

    positions: np.ndarray[Any, Any] | None = None


class WorkOrderRun:
    """Per-run state for one `WorkOrder`; created before the first dispatch."""

    def __init__(self, order: WorkOrder) -> None:
        self.order = order
        self.selection = Selection()

    def begin_table(self, table: str, source_columns: Iterable[str]) -> None:
        """Refuse a `when:` that names a column a node creates (see `reject_when_on_created`)."""
        reject_when_on_created(self.order, table, source_columns)

    def dispatch(
        self,
        call: Callable[..., list[QualityWarning]],
        node: WorkNode,
        frames: dict[str, pd.DataFrame],
        *args: Any,
        **kwargs: Any,
    ) -> list[QualityWarning]:
        """Run `call(node, frames, ...)` (the adapter's node dispatch) with a fresh selection."""
        self.selection = Selection()
        return call(node, frames, *args, **kwargs)
