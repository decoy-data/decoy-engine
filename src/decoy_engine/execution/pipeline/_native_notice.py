"""Whether a run fell back to Python because the compiled companion is missing.

One decision, made once per run from the compiled plan: the CLI reads the answer off
`ExecutionResult.native_fallback_code` and prints it, so no caller keeps its own copy of the
strategy-to-kernel map. A static plan-and-probe predicate is used because SEQ and OOC write no
lane evidence for `route_summary`, so only this predicate answers the same on every route.
The result carries a registered reason code and never a column, table or value.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any

from decoy_engine import reasons
from decoy_engine.execution._operator_registry import OPERATORS
from decoy_engine.execution.native._companion_status import (
    KernelAvailability,
    native_kernel_availability,
)

_LOG = logging.getLogger(__name__)

if TYPE_CHECKING:
    from decoy_engine.plan._types import Plan


def _needed_kernels(plan: Plan) -> frozenset[str]:
    """The compiled kernels the plan's mask columns ask for; generate columns do not count."""
    needed: set[str] = set()
    for _table, table_seed in plan.seed_envelope.per_table:
        for _column, seed in table_seed.per_column:
            spec = OPERATORS.get(seed.strategy)
            if spec is not None and spec.required_kernel is not None:
                needed.add(spec.required_kernel)
    return frozenset(needed)


def native_fallback_code(plan: Plan, availability: KernelAvailability | None = None) -> str | None:
    """`native_companion_missing` when the plan needs a compiled kernel and none of the kernels
    it needs is available; else None.

    `availability` is a test seam. Without it the companion is probed once, and only when the
    plan needs a kernel at all, so a Python-only plan pays nothing."""
    needed = _needed_kernels(plan)
    if not needed:
        return None
    probe = availability if availability is not None else native_kernel_availability()
    if any(getattr(probe, kernel) for kernel in needed):
        return None
    # A registered `ReasonCode` is the wire string itself; `str` drops the namespace carrier.
    return str(reasons.warning.NATIVE_COMPANION_MISSING)


def with_native_notice(result: Any, plan: Plan) -> Any:
    """`result` with `native_fallback_code` set, for the one call after `execute_route`.

    Setting it there, not inside a route, makes every route report the same way, and a run
    refused before it starts never claims a fallback. The notice is advisory and the job is
    done by now, so a failure here is logged without detail and leaves the field None."""
    try:
        code = native_fallback_code(plan)
    except Exception as exc:
        _LOG.debug("native fallback notice skipped (%s)", type(exc).__name__)
        return result
    return dataclasses.replace(result, native_fallback_code=code)
