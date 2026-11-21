"""The per-strategy plan checks refuse a nested child the way they refuse a top-level column.

Each of these checks reads its columns through the strategy-site walker. The cases pin the code
and the path of a refusal for a child in the single form and in the `rules` form, so a check that
walks columns on its own and misses a nested form fails here. The top-level refusals are pinned
by each check's own test file.
"""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine.plan import PlanCompileError, run_config_only_checks

COL = "tables.t.columns.c"


def _config(form: str, strategy: str, cfg: dict[str, Any]) -> dict[str, Any]:
    child = {"target": "$.d", "strategy": strategy, "strategy_config": cfg}
    pc = child if form == "single" else {"rules": [child]}
    column = {"name": "c", "namespace": "ns", "strategy": "nested", "provider_config": pc}
    return {
        "tables": [
            {
                "name": "t",
                "columns": [{"name": "id", "strategy": "hash", "namespace": "i"}, column],
            }
        ]
    }


def _at(form: str) -> str:
    return f"{COL}.provider_config" + (".rules[0]" if form == "rules" else "")


CASES = [
    # bucket_perturb: date format and preserve_values
    (
        "bucket_perturb",
        {"date_format": "abc"},
        "bucket_perturb_date_format_unsupported",
        "strategy_config.date_format",
    ),
    (
        "bucket_perturb",
        {"date_format": "%Y", "preserve_values": ["x"]},
        "bucket_perturb_preserve_values_invalid",
        "strategy_config.preserve_values",
    ),
    # top_code: not allowed as a nested child at all
    ("top_code", {"cap": 100, "over_label": "100+"}, "top_code_unsupported_in_nested", "strategy"),
    # date_shift: group_by, window, preserve_values and the required date_format
    (
        "date_shift",
        {"group_by": "id"},
        "date_shift_group_by_unsupported_in_nested",
        "strategy_config.group_by",
    ),
    (
        "date_shift",
        {"jitter_days": 3, "min_days": 1},
        "date_shift_window_invalid",
        "strategy_config.jitter_days",
    ),
    (
        "date_shift",
        {"preserve_values": 5},
        "date_shift_preserve_values_invalid",
        "strategy_config.preserve_values",
    ),
    (
        "date_shift",
        {"min_days": 1.5},
        "date_shift_requires_date_format",
        "strategy_config.date_format",
    ),
]


@pytest.mark.parametrize("form", ["single", "rules"])
@pytest.mark.parametrize(("strategy", "cfg", "code", "leaf"), CASES)
def test_a_nested_child_is_refused_with_its_own_code_and_path(
    form: str, strategy: str, cfg: dict[str, Any], code: str, leaf: str
) -> None:
    with pytest.raises(PlanCompileError) as err:
        run_config_only_checks(_config(form, strategy, cfg))
    assert err.value.code == code
    assert err.value.path == f"{_at(form)}.{leaf}"


@pytest.mark.parametrize("form", ["single", "rules"])
def test_a_clean_nested_child_passes_every_check(form: str) -> None:
    run_config_only_checks(_config(form, "date_shift", {"date_format": "%Y-%m-%d"}))
