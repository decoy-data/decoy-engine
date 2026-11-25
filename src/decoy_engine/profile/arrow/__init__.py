"""Arrow-native profiling: column walks that read Arrow data without converting to pandas, and
`profile_frame`, the one place a profile read converts an Arrow table to pandas."""

from __future__ import annotations

from decoy_engine.profile.arrow._frame import profile_frame
from decoy_engine.profile.arrow._walk_arrow import arrow_column_profile

__all__ = ["arrow_column_profile", "profile_frame"]
