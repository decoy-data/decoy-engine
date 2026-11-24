"""Arrow-native profiling: walks and samples that read Arrow data without converting to pandas."""

from __future__ import annotations

from decoy_engine.profile.arrow._arrow_sample import ArrowSampleSource, head_table_from_batches
from decoy_engine.profile.arrow._walk_arrow import arrow_column_profile, walk_arrow_table

__all__ = [
    "ArrowSampleSource",
    "arrow_column_profile",
    "head_table_from_batches",
    "walk_arrow_table",
]
