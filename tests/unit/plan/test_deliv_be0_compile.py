"""BE0 AT-10: `compile_plan` on a raw mapping refuses `delivery.mode: best_effort`.

`compile_plan` never builds a `PipelineConfig`, so the pipeline validator does not see it. The
raw guard runs before the subset guard, which raises for any non-null `subset` block.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from decoy_engine import reasons
from decoy_engine.contracts.column_shape import NO_SOURCES
from decoy_engine.errors import PipelineValidationError
from decoy_engine.plan import compile_plan
from decoy_engine.profile import profile_source
from tests.unit.execution import _c8_iii_c_support as sup

CODE = reasons.config.DELIVERY_BEST_EFFORT_UNRELEASED


def _compile(config: dict[str, Any], profile: Any) -> Any:
    return compile_plan(
        config, profile, decoy_engine_version="0.1.0", no_profile=True, sources=NO_SOURCES
    )


@pytest.fixture
def job(tmp_path: Path) -> tuple[dict[str, Any], Any]:
    config, _sources = sup.single_table_config(tmp_path)
    return config, profile_source(config, seed=7)


def _with(config: dict[str, Any], **blocks: Any) -> dict[str, Any]:
    out = copy.deepcopy(config)
    out.update(blocks)
    return out


@pytest.mark.parametrize("subset", [None, {"fraction": 0.5}], ids=["plain", "with_subset"])
def test_at10_best_effort_is_refused_before_the_subset_guard(
    job: tuple[dict[str, Any], Any], subset: Any
) -> None:
    config, profile = job
    raw = _with(config, delivery={"mode": "best_effort"})
    if subset is not None:
        raw["subset"] = subset
    with pytest.raises(PipelineValidationError) as info:
        _compile(raw, profile)
    assert info.value.code == CODE
    assert info.value.path == "delivery"
    assert "best_effort" in str(info.value)


def test_at10_strict_compiles_as_before(job: tuple[dict[str, Any], Any]) -> None:
    config, profile = job
    assert _compile(_with(config, delivery={"mode": "strict"}), profile) is not None
