"""Arrow-native profiling: column walks that read Arrow data without converting to pandas."""

from __future__ import annotations

from decoy_engine.profile.arrow._walk_arrow import arrow_column_profile

__all__ = ["arrow_column_profile"]
