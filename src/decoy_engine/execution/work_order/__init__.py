"""Work order: what each node does, and in what order.

`operations` resolves every node once (the one write authority), `compile` makes the one ordering
decision every entry point shares (main's `order_work`), `commits` is the gated write-back and
per-run state, and `rows` reads and takes the pre-mask snapshots by row position (and refuses a
`when:` on a column the input lacks).

Exports resolve lazily (PEP 562). `rows` is imported by strategies, and `operations` imports
`_column_access`, which reaches strategies: an eager import here made `import work_order.rows`
load the compiler, a cycle that broke `import decoy_engine` once `_column_access` imported another
package that reaches a strategy. Nothing in this `__init__` may import a submodule at module level
outside `TYPE_CHECKING`; tests/sentry/layout/test_execution_import_order.py holds that.
"""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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

# name -> submodule providing it, explicit so a typo fails at access time.
_LAZY_EXPORTS: dict[str, str] = {
    "ResolvedOperation": "operations",
    "Selection": "commits",
    "WorkOrder": "compile",
    "WorkOrderRun": "commits",
    "compile_plan_order": "compile",
    "compile_work_order": "compile",
    "resolve_operation": "operations",
    "resolve_operations": "operations",
}


def __getattr__(name: str) -> Any:
    submodule = _LAZY_EXPORTS.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{submodule}"), name)
    globals()[name] = value  # cache so later access skips __getattr__
    return value


def __dir__() -> list[str]:
    return sorted(list(globals()) + list(_LAZY_EXPORTS))


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
