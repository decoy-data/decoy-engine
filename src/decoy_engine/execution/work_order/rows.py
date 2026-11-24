"""The one reader of the pre-mask snapshots, by row position.

A gate selects rows by position, so every consumer takes the same positions: the snapshot rows come
back as a `Series` on a fresh `RangeIndex`, which no caller can align to the frame by label. Label
lookup was the source of the duplicate-index defect (a frame with repeated labels read both source
keys for one gated row).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from decoy_engine.execution._adapter import StrategyContext


def snapshot_rows(ctx: StrategyContext, table: str, column: str) -> pd.Series | None:
    """The pre-mask copy of `table.column` for the rows the handler sees, or None when the run
    built no snapshot (the reader raises its own coded error for that).

    A gated call (`ctx.gate_positions` set) takes the gate's rows; any other call takes the whole
    snapshot. The caller compares `len()` with the frame it holds and raises its own coded
    `..._misaligned` error on a mismatch (`misaligned_message`); no value is ever aligned by label.
    """
    snapshot = ctx.group_anchor_snapshots.get((table, column))
    if snapshot is None:
        return None
    positions = getattr(ctx, "gate_positions", None)  # test doubles omit it
    rows = snapshot if positions is None else snapshot.iloc[positions]
    return pd.Series(rows.array, index=pd.RangeIndex(len(rows)), name=rows.name)


def misaligned_message(table: str) -> str:
    """The message for a snapshot whose row count differs from the frame. It names the table only:
    a column or predicate can carry user data."""
    return (
        f"a pre-mask source snapshot for table {table!r} does not row-align with the "
        "frame being masked; the run fails closed."
    )
