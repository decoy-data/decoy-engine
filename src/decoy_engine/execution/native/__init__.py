"""Native columnar-streaming execution package (engine-efficiency program).

Phase 0 landed evidence and contracts only. Phases 1-2 built the compiled
kernels, the config/type-aware eligibility query, and (Task 2.7, this module's
re-export) the dispatch that routes an admitted table's masking through them
inside the Phase 1 streaming coordinator. ``_determinism_protocol`` still holds
the machine-checkable RNG draw-site inventory the whole package is built to
preserve exactly.
"""

from __future__ import annotations

from typing import Any

from decoy_engine.execution.native._dispatch import (
    NativeRouteEvidence,
    NodeRouteRecord,
    plan_native_route,
    run_native_or_oracle_chunked,
)

__all__ = [
    "MAX_NATIVE_THREADS",
    "NativeRouteEvidence",
    "NodeRouteRecord",
    "plan_native_route",
    "run_native_or_oracle_chunked",
]


def __getattr__(name: str) -> Any:
    # Lazy: `_chunked_entry` imports `execution._chunked`, which imports this package, so an
    # eager import here is a cycle.
    if name == "MAX_NATIVE_THREADS":
        from decoy_engine.execution.native import _chunked_entry

        return _chunked_entry.MAX_NATIVE_THREADS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
