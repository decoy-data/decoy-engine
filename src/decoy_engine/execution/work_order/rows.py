"""The one reader of the pre-mask snapshots, by row position.

A gate selects rows by position, so every consumer takes the same positions: the snapshot rows come
back as a `Series` on a fresh `RangeIndex`, which no caller can align to the frame by label. Label
lookup was the source of the duplicate-index defect (a frame with repeated labels read both source
keys for one gated row).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

import pandas as pd

from decoy_engine import reasons
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution.work_order.operations import gate_reads

if TYPE_CHECKING:
    from decoy_engine.execution._adapter import StrategyContext
    from decoy_engine.execution.work_order.compile import WorkOrder


def snapshot_rows(
    ctx: StrategyContext,
    table: str,
    column: str,
    expected_len: int,
    misaligned: Callable[[str], Exception],
) -> pd.Series | None:
    """The pre-mask copy of `table.column` for the rows the handler sees, or None when the run
    built no snapshot (the reader raises its own coded error for that).

    A gated call (`ctx.gate_positions` set) takes the gate's rows, after checking the snapshot
    against `ctx.source_row_count` (the full frame the gate ran on); any other call takes the whole
    snapshot. Either way the rows taken must number `expected_len`, the frame the handler holds.
    A mismatch raises `misaligned(message)`, the reader's own coded error, never an `IndexError`;
    no value is ever aligned by label.
    """
    snapshot = ctx.group_anchor_snapshots.get((table, column))
    if snapshot is None:
        return None
    positions = getattr(ctx, "gate_positions", None)  # test doubles omit it
    if positions is None:
        rows = snapshot
    else:
        if len(snapshot) != getattr(ctx, "source_row_count", None):
            raise misaligned(misaligned_message(table))
        rows = snapshot.iloc[positions]
    if len(rows) != expected_len:
        raise misaligned(misaligned_message(table))
    return pd.Series(rows.array, index=pd.RangeIndex(len(rows)), name=rows.name)


def take_source_snapshots(
    order: WorkOrder,
    snapshot_cols: Mapping[str, frozenset[str]],
    table: str,
    frame: pd.DataFrame,
) -> dict[tuple[str, str], pd.Series]:
    """The pre-mask copies for `table`, after checking its evaluated `when:` reads.

    The one step both routes run on a table's masking frame before its first handler. Every
    column an evaluated gate reads (`gate_reads`) must be a column label of `frame`, the converted
    input; otherwise `when_expression_error`. A column that only a node creates is not in the
    frame, so it has no original value to select rows by. The message names the table only.
    `snapshot_cols` is `source_snapshot_columns(order)`, computed once per order by the caller; the
    map is sparse, so a table with no entry gets no copies.
    """
    present = set(frame.columns)
    for op in order.ops.values():
        if op.table == table and gate_reads(op) - present:
            raise StrategyError(
                code=reasons.runtime.WHEN_EXPRESSION_ERROR,
                strategy=op.node.strategy,
                message=(
                    f"when: on table {table!r} names a column the table does not hold "
                    "before masking starts"
                ),
            )
    return {
        (table, col): frame[col].copy() for col in snapshot_cols.get(table, ()) if col in present
    }


def positional_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Index]:
    """`frame` with a fresh `RangeIndex`, plus the index it arrived with.

    Masking addresses rows by position (a `when:` gate selects positions, snapshots are read by
    position), so label and position must coincide, even when the source stored duplicate,
    unsorted or stepped labels. The stored index goes back at output assembly
    (`table_from_pandas_keeping_source_types(kept_index=)`).
    """
    kept = frame.index
    frame.index = pd.RangeIndex(len(frame))
    return frame, kept


def misaligned_message(table: str) -> str:
    """The message for a snapshot whose row count differs from the frame. It names the table only:
    a column or predicate can carry user data."""
    return (
        f"a pre-mask source snapshot for table {table!r} does not row-align with the "
        "frame being masked; the run fails closed."
    )
