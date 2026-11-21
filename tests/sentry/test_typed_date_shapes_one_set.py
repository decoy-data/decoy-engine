"""Sentry: the shapes a date strategy reads with no format are written in one place.

`contracts/column_shape.py` owns `TYPED_DATE_SHAPES`. Compile, the date preserve rules, the plan
boundary and the strategy requirements all read it. A second copy (a literal or an `or` that
names both shapes outside the home file) is a place that can
drift from the first, so it fails here.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from decoy_engine.contracts.column_shape import TYPED_DATE_SHAPES, ColumnShape
from decoy_engine.contracts.strategy_requirements import (
    SHAPE_REQUIREMENTS_BY_STRATEGY,
    shape_declaration_needed,
)
from decoy_engine.declared_casting._boundary import plan_column_shapes
from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.generation.pool._cache import PoolCache
from decoy_engine.relationships._graph import RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceRegistry

SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
HOME = "contracts/column_shape.py"
S = ColumnShape


def _shape_names(node: ast.AST) -> set[str]:
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)} & {
        S.DATE.name,
        S.TIMESTAMP_TZ.name,
    }


def test_no_second_copy_of_the_typed_date_set() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel == HOME:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.Set, ast.Tuple, ast.List, ast.BoolOp))
                and len(_shape_names(node)) == 2
            ):
                offenders.append(f"{rel}:{node.lineno}: lists both date shapes itself")
    assert not offenders, offenders


def test_the_set_is_the_two_date_shapes() -> None:
    assert {S.DATE, S.TIMESTAMP_TZ} == TYPED_DATE_SHAPES


def test_date_shift_requirement_is_derived_from_the_set() -> None:
    shaped = SHAPE_REQUIREMENTS_BY_STRATEGY["date_shift"]
    assert shaped.admitted == TYPED_DATE_SHAPES | {S.TEXT, S.UNKNOWN}
    for shape in S:
        needed = shape_declaration_needed(shaped, shape, config_only=False)
        assert needed is (shape not in TYPED_DATE_SHAPES and shape in shaped.admitted)


def test_the_plan_boundary_lists_exactly_the_set() -> None:
    plan = SimpleNamespace(
        column_shapes=tuple(SimpleNamespace(table="t", column=s.value, shape=s) for s in S)
    )
    ctx = StrategyContext(
        registry=None,  # type: ignore[arg-type]
        pool_cache=PoolCache(),
        relationship_graph=RelationshipGraph(edges=(), ordering=()),
        namespace_registry=NamespaceRegistry(bindings=()),
        job_seed=(0x42).to_bytes(8, "big"),
        column_shapes=plan_column_shapes(plan),
    )
    assert set(ctx.native_date_columns.values()) == TYPED_DATE_SHAPES
    assert len(ctx.native_date_columns) == len(TYPED_DATE_SHAPES)
