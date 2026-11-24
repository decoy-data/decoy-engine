"""Work order: what each node does, in what order, and which write wins each cell.

`operations` resolves every node once (the one write authority), `ranks` holds the ordering edges
and the ordinary sort, `compile` makes the one ordering decision every entry point shares, and
`commits` prepares creator targets and commits each column in rank order.
"""

from decoy_engine.execution.work_order.commits import Selection, WorkOrderRun
from decoy_engine.execution.work_order.compile import WorkOrder, compile_work_order
from decoy_engine.execution.work_order.operations import (
    ResolvedOperation,
    resolve_operation,
    resolve_operations,
)

__all__ = [
    "ResolvedOperation",
    "Selection",
    "WorkOrder",
    "WorkOrderRun",
    "compile_work_order",
    "resolve_operation",
    "resolve_operations",
]
