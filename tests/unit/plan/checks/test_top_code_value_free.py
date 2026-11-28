"""validate_plan never returns a submitted top_code value in its error text."""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine.plan.validate import validate_plan
from tests.unit.plan.test_validate import _VERSION, _profile

SECRET = "https://user:hunter2@host.example/x"
BIG = 10**20 + 12345
LOW = 7777771
HIGH = 8888881

CASES: list[tuple[str, dict[str, Any], str]] = [
    ("cap_str", {"cap": SECRET, "over_label": "o"}, "cap"),
    ("cap_nan", {"cap": float("nan"), "over_label": "o"}, "cap"),
    ("cap_big", {"cap": BIG, "over_label": "o"}, "cap"),
    ("preset", {"preset": SECRET}, "preset"),
    ("over_label", {"cap": 5, "over_label": [SECRET]}, "over_label"),
    ("floor_str", {"cap": 50, "over_label": "o", "floor": SECRET, "under_label": "u"}, "floor"),
    ("floor_big", {"cap": 50, "over_label": "o", "floor": -BIG, "under_label": "u"}, "floor"),
    ("under_label", {"cap": 50, "over_label": "o", "floor": 1, "under_label": [SECRET]}, "under"),
    ("floor_ge_cap", {"cap": LOW, "over_label": "o", "floor": HIGH, "under_label": "u"}, "floor"),
]


@pytest.mark.parametrize(("name", "provider_config", "field"), CASES, ids=[c[0] for c in CASES])
def test_validate_plan_error_omits_submitted_values(
    name: str, provider_config: dict[str, Any], field: str
) -> None:
    config = {
        "global_settings": {"seed": 1},
        "tables": [
            {
                "name": "t",
                "columns": [
                    {"name": "c", "strategy": "top_code", "provider_config": provider_config}
                ],
            }
        ],
    }
    result = validate_plan(config, _profile(), decoy_engine_version=_VERSION)
    assert result.ok is False and result.error is not None, name
    text = f"{result.error.message} {result.error.path}"
    # "cap nan" is how the old message echoed a submitted NaN ("non-finite cap nan").
    for canary in ("hunter2", "host.example", str(BIG), str(LOW), str(HIGH), "cap nan"):
        assert canary not in text, (name, canary)
    assert field in text
