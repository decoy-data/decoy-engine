"""The top_code, bucketize and truncate refusals carry a path from the config root.

A host that validates one column at a time wraps the call in `fileaccess.at_position`. These
checks already build the full `tables.<t>.columns.<c>...` path, so the active position must not
be prepended a second time.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from decoy_engine import fileaccess
from decoy_engine.plan._checks_bucketize import check_bucketize_config
from decoy_engine.plan._checks_top_code import check_top_code_config
from decoy_engine.plan._checks_truncate import check_truncate_config
from decoy_engine.plan._errors import PlanCompileError

_COLUMN = "tables.orders.columns.age"
_LABELS = {"over_label": "o"}

CASES: list[tuple[str, Callable[[dict[str, Any]], None], str, dict[str, Any], str]] = [
    ("cap_type", check_top_code_config, "top_code", {"cap": "5", **_LABELS}, "cap"),
    ("cap_nonfinite", check_top_code_config, "top_code", {"cap": float("inf"), **_LABELS}, "cap"),
    ("cap_range", check_top_code_config, "top_code", {"cap": 2**53, **_LABELS}, "cap"),
    ("preset", check_top_code_config, "top_code", {"preset": "nope"}, "preset"),
    ("over_label", check_top_code_config, "top_code", {"cap": 5}, "over_label"),
    (
        "floor_type",
        check_top_code_config,
        "top_code",
        {"cap": 50, **_LABELS, "floor": "1", "under_label": "u"},
        "floor",
    ),
    (
        "under_label",
        check_top_code_config,
        "top_code",
        {"cap": 50, **_LABELS, "floor": 1},
        "under_label",
    ),
    (
        "floor_ge_cap",
        check_top_code_config,
        "top_code",
        {"cap": 5, **_LABELS, "floor": 9, "under_label": "u"},
        "floor",
    ),
    ("width", check_bucketize_config, "bucketize", {"width": "5"}, "width"),
    ("mask_char", check_truncate_config, "truncate", {"length": 3, "mask_char": "ab"}, "mask_char"),
]


def _config(strategy: str, provider_config: dict[str, Any]) -> dict[str, Any]:
    column = {"name": "age", "strategy": strategy, "provider_config": provider_config}
    return {"tables": [{"name": "orders", "columns": [column]}]}


@pytest.mark.parametrize("active", ["", _COLUMN], ids=["no_position", "at_position"])
@pytest.mark.parametrize(
    ("name", "check", "strategy", "provider_config", "field"), CASES, ids=[c[0] for c in CASES]
)
def test_refusal_path_is_root_relative(
    name: str,
    check: Callable[[dict[str, Any]], None],
    strategy: str,
    provider_config: dict[str, Any],
    field: str,
    active: str,
) -> None:
    with fileaccess.at_position(active), pytest.raises(PlanCompileError) as caught:
        check(_config(strategy, provider_config))
    assert caught.value.path == f"{_COLUMN}.provider_config.{field}", name
