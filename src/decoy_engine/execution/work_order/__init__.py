"""Work order: what each node does, and in what order.

`operations` resolves every node once (the one write authority), `compile` makes the one ordering
decision every entry point shares (main's `order_work`), and `commits` prepares creator targets.
"""

from decoy_engine.execution.work_order.commits import Selection, WorkOrderRun
from decoy_engine.execution.work_order.compile import (
    WorkOrder,
    compile_plan_order,
    compile_work_order,
)
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
    "compile_plan_order",
    "compile_work_order",
    "resolve_operation",
    "resolve_operations",
]
