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


# Every read of TYPED_DATE_SHAPES outside its home file, as (path, enclosing function). The
# native-date view (shapes minus declared date columns) has one producer, ``native_date_shapes``;
# a caller that derives it inline would stay green on the literal check above, so any new read
# must be added here by a reviewer who has checked it is a single-shape test and not that view.
ALLOWED_TYPED_DATE_READS = frozenset(
    {
        ("contracts/strategy_requirements.py", "<module>"),
        ("plan/checks/_required_settings.py", "column_shape_warnings"),
        ("transforms/date_preserve.py", "preserve_config_problem"),
        ("transforms/date_preserve.py", "preserve_set_from_config"),
    }
)


def _typed_date_reads(rel: str, source: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()

    def walk(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = (
                child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope
            )
            if isinstance(child, ast.Name) and child.id == "TYPED_DATE_SHAPES":
                found.add((rel, scope))
            walk(child, inner)

    walk(ast.parse(source), "<module>")
    return found


def _unlisted_reads(sources: dict[str, str]) -> set[tuple[str, str]]:
    reads: set[tuple[str, str]] = set()
    for rel, text in sources.items():
        if rel != HOME:
            reads |= _typed_date_reads(rel, text)
    return reads - ALLOWED_TYPED_DATE_READS


def test_typed_date_shapes_is_read_only_at_allowlisted_sites() -> None:
    sources = {
        p.relative_to(SRC).as_posix(): p.read_text(encoding="utf-8") for p in SRC.rglob("*.py")
    }
    assert not _unlisted_reads(sources)
    stale = ALLOWED_TYPED_DATE_READS - {
        r for rel, text in sources.items() for r in _typed_date_reads(rel, text)
    }
    assert not stale, f"allowlist entries that no longer read the set: {sorted(stale)}"


# The plan-level native-date view is `declared_casting.plan_native_date_shapes`. Composing it
# again from its parts (`native_date_shapes` over `plan_column_shapes` or
# `declared_date_shift_columns`) outside `declared_casting/` is a second producer.
_VIEW_PARTS = frozenset({"plan_column_shapes", "declared_date_shift_columns"})


def _callee(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
    return None


def _composed_views(sources: dict[str, str]) -> set[tuple[str, int]]:
    found: set[tuple[str, int]] = set()
    for rel, text in sources.items():
        if rel.startswith("declared_casting/"):
            continue
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call) or _callee(node) != "native_date_shapes":
                continue
            if any(_callee(arg) in _VIEW_PARTS for arg in node.args):
                found.add((rel, node.lineno))
    return found


def test_the_plan_native_date_view_is_composed_only_in_declared_casting() -> None:
    sources = {
        p.relative_to(SRC).as_posix(): p.read_text(encoding="utf-8") for p in SRC.rglob("*.py")
    }
    assert not _composed_views(sources)


def test_restoring_the_old_composition_in_a_caller_is_red() -> None:
    """Mutation: the expression `typed_date_columns` held before `plan_native_date_shapes`."""
    rel = "execution/_chunked_bucket_perturb.py"
    text = (SRC / rel).read_text(encoding="utf-8")
    old = "    return frozenset(column for (t, column) in plan_native_date_shapes(plan) if t == table)"
    assert old in text
    restored = text.replace(
        old,
        "    native = native_date_shapes(plan_column_shapes(plan), declared_date_shift_columns(plan))\n"
        "    return frozenset(column for (t, column) in native if t == table)",
    )
    assert len(_composed_views({rel: restored})) == 1


def test_an_inline_native_date_derivation_in_a_caller_is_red() -> None:
    """Mutation: the producer's body pasted into a caller (the StrategyContext property)."""
    path = SRC / "execution/_adapter.py"
    inline = path.read_text(encoding="utf-8").replace(
        "return native_date_shapes(self.column_shapes, self.declared_date_columns)",
        "return {k: v for k, v in self.column_shapes.items()"
        " if v in TYPED_DATE_SHAPES and k not in self.declared_date_columns}",
    )
    assert "TYPED_DATE_SHAPES and k not in" in inline
    assert _unlisted_reads({"execution/_adapter.py": inline}) == {
        ("execution/_adapter.py", "native_date_columns")
    }
    gate = (SRC / "execution/_chunked_bucket_perturb.py").read_text(encoding="utf-8")
    gate_inline = gate.replace(
        "for (t, column) in plan_native_date_shapes(plan) if t == table",
        "for (t, column), v in plan_column_shapes(plan).items()"
        " if t == table and v in TYPED_DATE_SHAPES",
    )
    assert gate_inline != gate
    assert _unlisted_reads({"execution/_chunked_bucket_perturb.py": gate_inline}) == {
        ("execution/_chunked_bucket_perturb.py", "typed_date_columns")
    }
