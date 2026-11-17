"""Live helpers of `transforms/date_shift.py` and the removal pin for its dead V1 class.

The V1 `DateShiftStrategy` class (with an MD5 fallback offset) and its helpers had no caller in
`src/` and were deleted (roadmap row 24zb). The module keeps `_detect_format` and
`_COMMON_FORMATS`, which the engine-v2 handler, `bucket_perturb` and `text_mask` import.
"""

from __future__ import annotations

import pytest


def test_legacy_md5_class_and_helpers_are_gone():
    import decoy_engine.transforms.date_shift as module

    for name in (
        "DateShiftStrategy",
        "_shift_for_value_md5",
        "_shift_for_value_keyed",
        "_parse_date",
    ):
        assert not hasattr(module, name), name


def test_live_helpers_still_import():
    from decoy_engine.transforms.date_shift import _COMMON_FORMATS, _detect_format

    assert callable(_detect_format)
    assert _COMMON_FORMATS[0] == "%Y-%m-%d"
    assert "%m/%d/%Y" in _COMMON_FORMATS


class TestDetectFormat:
    """Direct oracles for the live `_detect_format` helper (reused by the
    engine-v2 date_shift handler, bucket_perturb, and the out-of-core path).
    The V1 class that shared this module was removed (tq-findings #11)."""

    def test_detect_iso_format(self) -> None:
        import pandas as pd

        from decoy_engine.transforms.date_shift import _detect_format

        # A column all of one format must be detected as that format (a broken
        # accept/append would return None instead).
        assert _detect_format(pd.Series(["2020-01-15", "2021-06-30"])) == "%Y-%m-%d"

    def test_detect_non_first_candidate_format(self) -> None:
        import pandas as pd

        from decoy_engine.transforms.date_shift import _detect_format

        # The first candidate (%Y-%m-%d) fails on these; detection must skip it
        # and keep scanning, not accept-on-fail or bail out at the first miss.
        assert _detect_format(pd.Series(["01/15/2020", "06/30/2021"])) == "%m/%d/%Y"

    def test_ambiguous_column_warns(self) -> None:
        import pandas as pd

        from decoy_engine.transforms.date_shift import _detect_format

        # Dates that parse under more than one format must emit the ambiguity
        # warning (the threshold is "> 1 candidate").
        with pytest.warns(UserWarning, match="multiple formats"):
            _detect_format(pd.Series(["01/02/2020", "03/04/2021"]))

    def test_unambiguous_column_does_not_warn(self) -> None:
        import warnings

        import pandas as pd

        from decoy_engine.transforms.date_shift import _detect_format

        # A single-candidate column must NOT warn (guards the ">1" threshold
        # against a ">=1" drift that would warn on every column).
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert _detect_format(pd.Series(["2020-01-15", "2021-06-30"])) == "%Y-%m-%d"

    def test_sample_cap_limits_detection_to_200_rows(self) -> None:
        import pandas as pd

        from decoy_engine.transforms.date_shift import _detect_format

        # The sample is capped at 200 rows (F9); a format that holds for the
        # first 200 rows is detected even if a later row would break it. Pins
        # both the cap value and that the cap is applied (head(200), not all).
        values = ["2020-01-15"] * 200 + ["not-a-date"]
        assert _detect_format(pd.Series(values)) == "%Y-%m-%d"
