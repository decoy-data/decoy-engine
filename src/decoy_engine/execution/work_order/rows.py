"""The one reader of the pre-mask snapshots, by row position.

A gate selects rows by position, so every consumer takes the same positions: the snapshot rows come
back as a `Series` on a fresh `RangeIndex`, which no caller can align to the frame by label. Label
lookup was the source of the duplicate-index defect (a frame with repeated labels read both source
keys for one gated row).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from decoy_engine.execution._errors import StrategyError

if TYPE_CHECKING:
    from decoy_engine.execution._adapter import StrategyContext


def snapshot_rows(
    ctx: StrategyContext, table: str, column: str, n_rows: int, *, strategy: str, misaligned: str
) -> pd.Series | None:
    """The pre-mask copy of `table.column` for the rows the handler sees, or None when the run
    built no snapshot (the reader raises its own coded error for that).

    A gated call (`ctx.gate_positions` set) takes the gate's rows; any other call takes the whole
    snapshot. The count must equal `n_rows` (the frame the handler holds), else `misaligned` is
    raised. Messages name the table only: a column or predicate can carry user data.
    """
    snapshot = ctx.group_anchor_snapshots.get((table, column))
    if snapshot is None:
        return None
    positions = getattr(ctx, "gate_positions", None)  # test doubles omit it
    rows = snapshot if positions is None else snapshot.iloc[positions]
    if len(rows) != n_rows or (positions is None and len(snapshot) != n_rows):
        raise StrategyError(
            code=misaligned,
            strategy=strategy,
            message=(
                f"a pre-mask source snapshot for table {table!r} does not row-align with the "
                "frame being masked; the run fails closed."
            ),
        )
    return pd.Series(rows.array, index=pd.RangeIndex(n_rows), name=rows.name)
