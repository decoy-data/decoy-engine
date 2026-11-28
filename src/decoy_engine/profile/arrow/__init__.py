"""Arrow-native profiling: column walks and samples that read Arrow data, and the bounded
Parquet profile's recovery for dates and times pandas cannot hold."""

from __future__ import annotations

from decoy_engine.profile.arrow._arrow_sample import (
    ArrowSampleSource,
    head_table_from_batches,
    sample_table_frame,
)
from decoy_engine.profile.arrow._recovery import recover_temporal_profile
from decoy_engine.profile.arrow._walk_arrow import arrow_column_profile

__all__ = [
    "ArrowSampleSource",
    "arrow_column_profile",
    "head_table_from_batches",
    "recover_temporal_profile",
    "sample_table_frame",
]
