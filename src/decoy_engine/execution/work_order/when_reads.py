"""The `when:` guard that needs the compiled order: a read of a column no source holds."""

from __future__ import annotations

from collections.abc import Iterable

from decoy_engine import reasons
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution.work_order.compile import WorkOrder
from decoy_engine.plan._types import ColumnSeed


def reject_when_on_created(order: WorkOrder, table: str, source_columns: Iterable[str]) -> None:
    """Raise `when_expression_error` for a `when:` that names a column an earlier node creates.

    Such a column is not in the source, so it has no pre-mask value to read. Main refused it with
    this code when the predicate ran; this raises it before any node runs, so no snapshot is
    ever asked for a column that does not exist (`when_source_snapshot_missing` stays for a route
    that forgot a snapshot). The message names the table only: a column can carry user data.
    """
    from decoy_engine.execution._runner import when_columns_of

    present = set(source_columns)
    created = {
        c for op in order.ops.values() if op.table == table and op.creates for c in op.writes
    }
    for op in order.ops.values():
        if op.table != table or not isinstance(op.node.plan_slice, ColumnSeed):
            continue
        if when_columns_of([op.node.plan_slice.when]) & (created - present):
            raise StrategyError(
                code=reasons.runtime.WHEN_EXPRESSION_ERROR,
                strategy=op.node.plan_slice.strategy,
                message=(
                    f"when: on table {table!r} names a column that an earlier node creates, "
                    "which the source does not hold"
                ),
            )
