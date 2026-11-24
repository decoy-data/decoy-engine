"""Work order: what each node does, and in what order.

`operations` resolves every node once (the one write authority), `compile` makes the one ordering
decision every entry point shares (main's `order_work`), `commits` is the gated write-back and
per-run state, and `rows` reads and takes the pre-mask snapshots by row position (and refuses a
`when:` on a column the input lacks).
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
