"""Resume of a failed chunked run: the fingerprint, the two store records and the keep/rerun plan.

Public surface: `RunFingerprint`, `build_fingerprint`, `binding_digest`; `RunRecord`,
`TableRecord`, `TableEntry` and the four encoders and decoders of `decoy-resume-run/v1` and
`decoy-resume-table/v1`; `plan_resume`, `ResumePlan`, `TableCheck` and `ResumeRefusedError`.
Everything here is pure and value-free. The store files and the checks that feed `TableCheck`
belong to the caller.
"""

from __future__ import annotations

from decoy_engine.delivery.resume._fingerprint import (
    RunFingerprint,
    binding_digest,
    build_fingerprint,
)
from decoy_engine.delivery.resume._plan import (
    ResumePlan,
    ResumeRefusedError,
    ResumeWarning,
    TableCheck,
    plan_resume,
)
from decoy_engine.delivery.resume._records import (
    ROUTE_CHUNKED,
    RunRecord,
    TableEntry,
    TableRecord,
    decode_run_record,
    decode_table_record,
    encode_run_record,
    encode_table_record,
)

__all__ = [
    "ROUTE_CHUNKED",
    "ResumePlan",
    "ResumeRefusedError",
    "ResumeWarning",
    "RunFingerprint",
    "RunRecord",
    "TableCheck",
    "TableEntry",
    "TableRecord",
    "binding_digest",
    "build_fingerprint",
    "decode_run_record",
    "decode_table_record",
    "encode_run_record",
    "encode_table_record",
    "plan_resume",
]
