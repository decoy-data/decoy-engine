"""The one effective-width rule the bucketize handler, compile check and shape rule share."""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine.contracts.bucketize_width import (
    BUCKETIZE_PRESETS,
    resolve_bucketize_width,
    unresolvable_width_field,
)


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({"preset": "by_decade"}, 10),
        ({"preset": "by_decade", "width": 3}, 10),  # a known preset wins; width is ignored
        ({"preset": "by_decade", "width": "x"}, 10),
        ({"preset": "(custom)"}, None),
        ({"preset": "(custom)", "width": 10}, None),  # an unknown preset never falls to width
        ({"preset": 5}, None),
        ({"preset": ["by_year"]}, None),
        ({"width": 10}, 10),
        ({"width": 2.5}, 2.5),
        ({"width": True}, None),
        ({"width": 0}, None),
        ({"width": -5}, None),
        ({"width": "10"}, None),
        ({"width": None}, None),
        ({}, None),
    ],
)
def test_one_resolution(config: dict[str, Any], expected: int | float | None) -> None:
    assert resolve_bucketize_width(config) == expected


def test_every_preset_is_an_integer_from_1_to_10000() -> None:
    assert all(type(w) is int and 1 <= w <= 10_000 for w in BUCKETIZE_PRESETS.values())
    assert all(resolve_bucketize_width({"preset": n}) == w for n, w in BUCKETIZE_PRESETS.items())


@pytest.mark.parametrize(
    ("config", "field"),
    [
        ({"preset": "by_year"}, None),
        ({"width": 4}, None),
        ({"preset": "nope"}, "preset"),
        ({"preset": "nope", "width": 4}, "preset"),
        ({"width": 0}, "width"),
        ({}, "width"),
    ],
)
def test_the_field_that_leaves_the_width_unresolved(
    config: dict[str, Any], field: str | None
) -> None:
    assert unresolvable_width_field(config) == field
