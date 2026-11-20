"""The one date_shift window resolver: rules, refusals and native admission agreement.

`legacy_window` is the window rule of the date_shift handler on origin/main
75fba3d855d71e3980a62afc3ce7f1187b72073d, copied here so non-jitter configs keep exactly their
old window (strings, floats, bools and numpy integers all go through `int()`).
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np
import pytest

from decoy_engine.execution.native._operator_config_rejections import date_shift_config_rejection
from decoy_engine.plan._checks_date_shift import check_date_shift_window
from decoy_engine.plan._compile import run_config_only_checks
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.transforms.date_shift import (
    MAX_ABS_SHIFT_DAYS,
    WINDOW_PROBLEMS,
    shift_window,
    shift_window_problem,
)


def legacy_window(cfg: dict[str, Any]) -> tuple[int, int]:
    low = int(cfg.get("min_days", -365))
    high = int(cfg.get("max_days", 365))
    return (high, low) if low > high else (low, high)


# --- 1. The rules -----------------------------------------------------------------------------


@pytest.mark.parametrize("n", [0, 1, 30, MAX_ABS_SHIFT_DAYS])
def test_jitter_days_is_a_symmetric_window(n: int) -> None:
    assert shift_window({"jitter_days": n}) == (-n, n)
    assert shift_window_problem({"jitter_days": n}) is None


@pytest.mark.parametrize(
    ("cfg", "want"),
    [
        ({}, (-365, 365)),
        ({"min_days": -5}, (-5, 365)),
        ({"max_days": 9}, (-365, 9)),
        ({"min_days": -5, "max_days": 9}, (-5, 9)),
        ({"min_days": 9, "max_days": -5}, (-5, 9)),
        ({"jitter_days": None}, (-365, 365)),
    ],
)
def test_bounds_default_and_swap(cfg: dict[str, Any], want: tuple[int, int]) -> None:
    assert shift_window(cfg) == want


@pytest.mark.parametrize(
    "value",
    ["7", " -8 ", "+3", 7.0, 7.9, -7.9, True, False, np.int64(5), np.int32(-3), np.uint8(4)],
)
def test_non_jitter_coercion_keeps_todays_window(value: Any) -> None:
    for cfg in (
        {"min_days": value},
        {"max_days": value},
        {"min_days": value, "max_days": 40},
        {"min_days": -40, "max_days": value},
    ):
        assert shift_window(cfg) == legacy_window(cfg), cfg


def test_non_jitter_coercion_matches_on_a_generated_set() -> None:
    rng = random.Random(20261119)
    makers: list[Any] = [int, str, float, lambda v: f" {v} ", np.int64]
    for _ in range(400):
        low, high = rng.randint(-5000, 5000), rng.randint(-5000, 5000)
        cfg = {
            "min_days": rng.choice(makers)(low),
            "max_days": rng.choice(makers)(high),
        }
        assert shift_window(cfg) == legacy_window(cfg), cfg


@pytest.mark.parametrize(
    ("cfg", "problem"),
    [
        ({"jitter_days": 5, "min_days": -1}, "jitter_days_with_bounds"),
        ({"jitter_days": 5, "max_days": 1}, "jitter_days_with_bounds"),
        ({"jitter_days": -1}, "jitter_days_invalid"),
        ({"jitter_days": True}, "jitter_days_invalid"),
        ({"jitter_days": False}, "jitter_days_invalid"),
        ({"jitter_days": "7"}, "jitter_days_invalid"),
        ({"jitter_days": 7.0}, "jitter_days_invalid"),
        ({"jitter_days": [7]}, "jitter_days_invalid"),
        ({"jitter_days": MAX_ABS_SHIFT_DAYS + 1}, "jitter_days_out_of_range"),
        ({"min_days": MAX_ABS_SHIFT_DAYS + 1}, "min_days_out_of_range"),
        ({"min_days": -MAX_ABS_SHIFT_DAYS - 1}, "min_days_out_of_range"),
        ({"max_days": MAX_ABS_SHIFT_DAYS + 1}, "max_days_out_of_range"),
        ({"max_days": "106752"}, "max_days_out_of_range"),
        ({"min_days": "abc"}, "min_days_invalid"),
        ({"max_days": None}, "max_days_invalid"),
        ({"min_days": [1]}, "min_days_invalid"),
        ({"max_days": float("inf")}, "max_days_invalid"),
        ({"min_days": float("nan")}, "min_days_invalid"),
    ],
)
def test_bad_window_is_a_fixed_problem_and_a_value_free_error(
    cfg: dict[str, Any], problem: str
) -> None:
    assert shift_window_problem(cfg) == problem
    with pytest.raises(PlanCompileError) as exc:
        shift_window(cfg)
    key, message = WINDOW_PROBLEMS[problem]
    assert exc.value.code == "date_shift_window_invalid"
    assert exc.value.path == f"provider_config.{key}"
    assert isinstance(exc.value, ValueError)
    assert message in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None


# --- 3. Refusal at compile (top level and nested) and at native admission ---------------------

_REFUSED: list[tuple[dict[str, Any], str]] = [
    ({"jitter_days": 5, "min_days": -1}, "jitter_days"),
    ({"jitter_days": 5, "max_days": 1}, "jitter_days"),
    ({"jitter_days": "7"}, "jitter_days"),
    ({"jitter_days": True}, "jitter_days"),
    ({"jitter_days": -1}, "jitter_days"),
    ({"jitter_days": MAX_ABS_SHIFT_DAYS + 1}, "jitter_days"),
    ({"min_days": -MAX_ABS_SHIFT_DAYS - 1}, "min_days"),
    ({"max_days": MAX_ABS_SHIFT_DAYS + 1}, "max_days"),
    ({"min_days": "abc"}, "min_days"),
    ({"max_days": float("nan")}, "max_days"),
]


def _top(provider_config: dict[str, Any]) -> dict[str, Any]:
    column = {
        "name": "dob",
        "strategy": "date_shift",
        "namespace": "ds_ns",
        "provider_config": {"date_format": "%Y-%m-%d", **provider_config},
    }
    return {"tables": [{"name": "t", "columns": [column]}]}


def _nested(provider_config: dict[str, Any]) -> dict[str, Any]:
    column = {
        "name": "payload",
        "strategy": "nested",
        "namespace": "ds_ns",
        "provider_config": {
            "target": "$.dob",
            "strategy": "date_shift",
            "strategy_config": {"date_format": "%Y-%m-%d", **provider_config},
        },
    }
    return {"tables": [{"name": "t", "columns": [column]}]}


@pytest.mark.parametrize(("provider_config", "key"), _REFUSED)
@pytest.mark.parametrize("shape", [_top, _nested], ids=["top_level", "nested"])
def test_window_invalid_refused_at_compile(
    provider_config: dict[str, Any], key: str, shape: Any
) -> None:
    config = shape(provider_config)
    with pytest.raises(PlanCompileError) as exc:
        check_date_shift_window(config)
    assert exc.value.code == "date_shift_window_invalid"
    assert exc.value.path is not None
    assert exc.value.path.endswith(f".{key}")
    assert "tables.t.columns." in exc.value.path
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None
    # The profile-free compile entry runs the same check, before any source is read.
    with pytest.raises(PlanCompileError) as entry:
        run_config_only_checks(config)
    assert entry.value.code == "date_shift_window_invalid"


@pytest.mark.parametrize(
    "provider_config",
    [{}, {"jitter_days": 15}, {"min_days": -30, "max_days": 30}, {"min_days": "7"}],
)
@pytest.mark.parametrize("shape", [_top, _nested], ids=["top_level", "nested"])
def test_valid_windows_compile(provider_config: dict[str, Any], shape: Any) -> None:
    check_date_shift_window(shape(provider_config))


@pytest.mark.parametrize(("provider_config", "key"), _REFUSED)
def test_native_admission_agrees_with_compile(provider_config: dict[str, Any], key: str) -> None:
    reason = date_shift_config_rejection(
        "dob",
        "t",
        None,
        namespace="ds_ns",
        provider_config={"date_format": "%Y-%m-%d", **provider_config},
    )
    assert reason is not None and reason.startswith("date_shift_"), reason
    assert reason.endswith(":dob")


@pytest.mark.parametrize("provider_config", [{"jitter_days": 106_751}, {"jitter_days": 0}, {}])
def test_native_admission_takes_a_valid_window(provider_config: dict[str, Any]) -> None:
    assert (
        date_shift_config_rejection(
            "dob",
            "t",
            None,
            namespace="ds_ns",
            provider_config={"date_format": "%Y-%m-%d", **provider_config},
        )
        is None
    )
