"""Live helpers of `transforms/date_shift.py` and the removal pin for its dead V1 class.

The V1 `DateShiftStrategy` class (with an MD5 fallback offset) and its helpers had no caller in
`src/` and were deleted (roadmap row 24zb). `_detect_format` was deleted with the last strategy
that detected a column format at run time (COLUMN-SHAPE E2). The module keeps `_COMMON_FORMATS`,
which `text_mask` imports for date spans in free text.
"""

from __future__ import annotations


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
    import decoy_engine.transforms.date_shift as module
    from decoy_engine.transforms.date_shift import _COMMON_FORMATS

    assert not hasattr(module, "_detect_format")
    assert _COMMON_FORMATS[0] == "%Y-%m-%d"
    assert "%m/%d/%Y" in _COMMON_FORMATS
