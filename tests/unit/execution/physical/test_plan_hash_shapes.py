"""`Plan.column_shapes` is a part of the physical plan hash.

A source-loader table has no descriptor and no profile entry, so its schema reaches the plan
only through the column shapes. Two runs that differ only in a loader schema must not share a
hash.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pyarrow as pa

from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.execution.physical import capture_physical_plan_inputs
from decoy_engine.plan._types import PlanColumnShape
from tests.acceptance._f06_support import column

S = ColumnShape


def _config(*names: str) -> dict[str, Any]:
    cols = [
        column(n, "date_shift", namespace="ns", provider_config={"date_format": "%Y-%m-%d"})
        for n in names
    ]
    return {
        "version": 2,
        "global_settings": {"seed": 7},
        "tables": [{"name": "t", "columns": cols}],
        "relationships": [],
        "namespaces": {},
    }


def _capture(config: dict[str, Any], schema: pa.Schema) -> Any:
    return capture_physical_plan_inputs(
        config,
        None,
        engine_version="t",
        source_loader=lambda name: schema.empty_table(),
        source_loader_schemas={"t": schema},
    )


def test_capture_passes_loader_schemas() -> None:
    inputs = _capture(_config("d"), pa.schema([("d", pa.date32())]))
    assert [(c.table, c.column, c.shape) for c in inputs.plan.column_shapes] == [("t", "d", S.DATE)]


def test_hash_differs_when_only_loader_schema_differs() -> None:
    as_date = _capture(_config("d"), pa.schema([("d", pa.date32())]))
    as_text = _capture(_config("d"), pa.schema([("d", pa.string())]))
    assert as_date.plan.profile_hash == as_text.plan.profile_hash
    assert as_date.plan.pipeline_config_hash == as_text.plan.pipeline_config_hash
    assert as_date.plan_hash() != as_text.plan_hash()


def test_hash_is_stable_for_the_same_schema() -> None:
    a = _capture(_config("d"), pa.schema([("d", pa.date32())]))
    b = _capture(_config("d"), pa.schema([("d", pa.date32())]))
    assert a.plan_hash() == b.plan_hash()


def test_hash_ignores_shape_order() -> None:
    inputs = _capture(_config("a", "b"), pa.schema([("a", pa.date32()), ("b", pa.string())]))
    shapes = inputs.plan.column_shapes
    assert len(shapes) == 2
    flipped = dataclasses.replace(
        inputs, plan=dataclasses.replace(inputs.plan, column_shapes=tuple(reversed(shapes)))
    )
    assert flipped.plan_hash() == inputs.plan_hash()


def test_hash_moves_with_one_shape() -> None:
    inputs = _capture(_config("d"), pa.schema([("d", pa.date32())]))
    other = (PlanColumnShape("t", "d", S.TIMESTAMP_NAIVE),)
    moved = dataclasses.replace(inputs, plan=dataclasses.replace(inputs.plan, column_shapes=other))
    assert moved.plan_hash() != inputs.plan_hash()
