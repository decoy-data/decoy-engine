"""`decoy_engine.support`: pseudonymised support-bundle types (F32).

A support bundle describes a run's structure (versions, limits, routes, timings, coded errors,
topology) with no cell value, name, path or free text. Names become ordinal labels from a
per-build `LabelAllocator`. Decoy never uploads a bundle; the operator reviews and sends it.

The runtime lock (`lock/v1`) records the versions and data digests masked bytes depend on, and the
synthetic probe digest (`run_probe`, `probe_status`) that shows a host reproduces the engine's bytes.

The engine enums a bundle carries (`RouteDeclineCode`, `PIIClass`, `Severity`, `Outcome`,
`RetryClass`) are re-exported here so consumers never import a private module.
"""

from __future__ import annotations

from decoy_engine.execution.native._route_decline_codes import RouteDeclineCode
from decoy_engine.profile import PIIClass
from decoy_engine.reasons import Outcome, RetryClass, Severity
from decoy_engine.support._labels import LabelAllocator
from decoy_engine.support._probe import ProbeError, probe_status, run_probe
from decoy_engine.support._runtime_lock import (
    LockDifference,
    RuntimeLock,
    build_runtime_lock,
    compare_runtime_locks,
    read_runtime_lock,
)
from decoy_engine.support._shape import (
    BundleSchema,
    ColumnShape,
    CountKey,
    DtypeClass,
    EdgeShape,
    ErrorFact,
    EventFact,
    Label,
    Limits,
    NativeStatus,
    NodeTiming,
    OrphanPolicy,
    Phase,
    PhaseTiming,
    PlatformFamily,
    RatioBucket,
    RouteFact,
    RouteKind,
    StrategyKind,
    SupportBundle,
    TableShape,
    Timings,
    Topology,
    Version,
    Versions,
)

__all__ = [
    "BundleSchema",
    "ColumnShape",
    "CountKey",
    "DtypeClass",
    "EdgeShape",
    "ErrorFact",
    "EventFact",
    "Label",
    "LabelAllocator",
    "Limits",
    "LockDifference",
    "NativeStatus",
    "NodeTiming",
    "OrphanPolicy",
    "Outcome",
    "PIIClass",
    "Phase",
    "PhaseTiming",
    "PlatformFamily",
    "ProbeError",
    "RatioBucket",
    "RetryClass",
    "RouteDeclineCode",
    "RouteFact",
    "RouteKind",
    "RuntimeLock",
    "Severity",
    "StrategyKind",
    "SupportBundle",
    "TableShape",
    "Timings",
    "Topology",
    "Version",
    "Versions",
    "build_runtime_lock",
    "compare_runtime_locks",
    "probe_status",
    "read_runtime_lock",
    "run_probe",
]
