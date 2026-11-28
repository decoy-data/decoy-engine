"""The one effective-width rule the bucketize handler, compile check and shape rule share."""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine.contracts.bucketize_width import (
    BUCKETIZE_PRESETS,
    is_oversized_integer,
    is_oversized_integer_width,
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
        ({"width": 2**53 - 1}, 2**53 - 1),
        ({"width": 2**53}, None),  # an integer width the label arithmetic cannot hold
        ({"width": 2**70}, None),
        ({"width": float(2**53)}, float(2**53)),  # a float width never needs the exact bound
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


@pytest.mark.parametrize(
    ("raw", "oversized"),
    [
        (2**53 - 1, False),
        (2**53, True),
        (2**70, True),
        (float(2**53), False),  # a float width never exits
        (True, False),
        ("9007199254740992", False),
        (None, False),
    ],
)
def test_oversized_integer_predicate_boundary(raw: Any, oversized: bool) -> None:
    assert is_oversized_integer(raw) is oversized


@pytest.mark.parametrize("width", [2**53 - 1, 2**53, float(2**53)])
def test_each_caller_agrees_with_the_predicate(width: int | float) -> None:
    """Resolver, decimal-deferral check and kernel all follow the one predicate at the boundary."""
    import pyarrow as pa

    from decoy_engine.kernel import bucketize_array

    oversized = is_oversized_integer(width)
    cfg = {"width": width}
    assert (resolve_bucketize_width(cfg) is None) is oversized
    assert is_oversized_integer_width(cfg) is oversized
    assert is_oversized_integer_width({"preset": "by_decade", "width": width}) is False
    if oversized:
        with pytest.raises(ValueError, match="exact integer bound"):
            bucketize_array(pa.array([1]), width, "lower")
    else:
        bucketize_array(pa.array([1]), width, "lower")


def test_boundary_width_is_refused_by_every_entry_point() -> None:
    """One eligibility rule: the resolver, the plan check, the handler and the kernel agree."""
    import pyarrow as pa

    from decoy_engine.execution._strategies._bucketize import resolve_bucketize_settings
    from decoy_engine.kernel import bucketize_array
    from decoy_engine.plan._checks_bucketize import check_bucketize_config
    from decoy_engine.plan._errors import PlanCompileError

    cfg = {"width": 2**53, "format": "lower"}
    assert unresolvable_width_field(cfg) == "width"
    config = {
        "tables": [
            {
                "name": "t",
                "columns": [{"name": "c", "strategy": "bucketize", "provider_config": cfg}],
            }
        ]
    }
    with pytest.raises(PlanCompileError):
        check_bucketize_config(config)
    with pytest.raises(Exception, match="width") as handler_err:
        resolve_bucketize_settings(cfg, "c")
    assert type(handler_err.value).__name__ == "StrategyError"
    with pytest.raises(ValueError):
        bucketize_array(pa.array([1]), 2**53, "lower")
    # the largest width all four accept
    ok = {"width": 2**53 - 1, "format": "lower"}
    assert unresolvable_width_field(ok) is None
    assert resolve_bucketize_settings(ok, "c").width == 2**53 - 1
    assert bucketize_array(pa.array([1]), 2**53 - 1, "lower").labels.to_pylist() == ["0"]
