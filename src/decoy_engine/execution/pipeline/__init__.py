"""Pipeline-spine route clusters. RUN-STREAM's strict `stream` requirement lives in `_stream`.

The host CPU probe, the route summary, the resident lower bound and verdict, and the shared cgroup mapping are exported here so other packages do not import
the private modules.
"""

from decoy_engine.execution.pipeline._cgroup import (
    CgroupMappingError,
    Mount,
    parse_membership,
    parse_mountinfo,
    relative_to_root,
    select_mount,
)
from decoy_engine.execution.pipeline._host import detect_usable_cpus, native_thread_clamp
from decoy_engine.execution.pipeline._resident_bytes import (
    TableBytesSpec,
    lazy_spec,
    lower_bound_bytes,
    resident_spec,
)
from decoy_engine.execution.pipeline._resident_fit import (
    ResidentFit,
    check_pre_read,
    check_pre_transform,
    require_resident_fit,
    store_resident_fit,
)
from decoy_engine.execution.pipeline._route_summary import RouteSummary, route_summary

__all__ = [
    "CgroupMappingError",
    "Mount",
    "ResidentFit",
    "RouteSummary",
    "TableBytesSpec",
    "check_pre_read",
    "check_pre_transform",
    "detect_usable_cpus",
    "lazy_spec",
    "lower_bound_bytes",
    "native_thread_clamp",
    "parse_membership",
    "parse_mountinfo",
    "relative_to_root",
    "require_resident_fit",
    "resident_spec",
    "route_summary",
    "select_mount",
    "store_resident_fit",
]
