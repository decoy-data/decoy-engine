"""O1 sentry (AT-O1e, plus the set contents): one function names the integer columns that must
ingest losslessly, and only allowlisted functions call the ingestion helpers.

`lossless_int_columns` is the single construction of the set (FK keys, date-shift anchors,
`top_code`, `group_key` siblings, declared integers, and the integer columns a `when:` reads).
The sites that convert Arrow to pandas take that set; a site that builds it by hand drifts, as
`_chunked_carry.py` did before (it left out declared integers and anchors).

The key is the exact `(path, qualified function)` of the caller, never a bare function name, so a
new function that happens to share a name with an allowlisted one fails. Plain `.to_pandas()`
ingestion is a documented limit that this sentry does not claim.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from decoy_engine.contracts.column_shape import NO_SOURCES

ROOT = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"
FK = "_fk_keys.py"

# helper -> {(path under src/decoy_engine, qualified caller): reason}
ALLOWED: dict[str, dict[tuple[str, str], str]] = {
    "fk_columns_for_table": {
        ("execution/_fk_keys.py", "lossless_int_columns"): "the one construction of the set",
        ("execution/_pipeline_full_frame.py", "_raise_if_source_value_unrepresentable"): (
            "diagnostic only: it has no plan or registry and retries one column to attribute a failure"
        ),
    },
    "lossless_int_columns": {
        ("execution/_pandas_adapter.py", "PandasExecutionAdapter.run"): "whole-frame ingestion",
        ("execution/_sequential.py", "run_sequential"): "table-at-a-time ingestion",
        ("execution/_chunked_carry.py", "adapter_fk_safe_columns"): (
            "the chunked legs and the native when and Faker masks take the adapter's set from here"
        ),
    },
    "lossless_int_columns_from_config": {
        ("execution/_unified_slice_admission.py", "cheap_admission"): (
            "unified admission has the config, not a compiled plan"
        ),
    },
    "adapter_fk_safe_columns": {
        ("execution/chunked/_oracle_step.py", "oracle_chunk_step"): "diagnosis of a failed chunk",
        ("execution/native/_when_mask.py", "plan_when_masks"): "the native when mask's set",
        (
            "execution/native/_faker_null_mask.py",
            "plan_faker_null_masks",
        ): "the Faker null mask's set",
    },
    "to_pandas_fk_safe": {
        ("execution/_pandas_adapter.py", "PandasExecutionAdapter.run"): "ingestion",
        ("execution/_sequential.py", "run_sequential"): "ingestion",
        ("execution/_unified_slice_admission.py", "cheap_admission"): "ingestion",
        ("execution/native/_when_mask.py", "when_mask"): "converts the columns a predicate reads",
        ("execution/native/_faker_null_mask.py", "faker_missing_mask"): "converts one column",
        ("execution/_chunked_carry.py", "CarryPlan.diagnose_adapter"): "diagnosis: indirect caller",
        ("execution/_pipeline_full_frame.py", "_raise_if_source_value_unrepresentable"): (
            "diagnostic only, as above"
        ),
        (
            "execution/_mixed_fk_bridge.py",
            "_write_back_fk_column",
        ): "narrow purpose: one key column",
        ("execution/_transforms_table.py", "to_transform_frame"): "narrow purpose: transforms",
        (
            "execution/native/_group_key_kernel.py",
            "_stringify_sibling",
        ): "narrow purpose: one sibling",
    },
}


def _aliases(tree: ast.AST, helper: str) -> set[str]:
    """Every local name `helper` is bound to by an import in this module (`import x as y` forms)."""
    names = {helper}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(a.asname for a in node.names if a.name == helper and a.asname)
    return names


def _is_all_assignment(node: ast.AST) -> bool:
    return isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
    )


def _walk(
    node: ast.AST,
    scope: tuple[str, ...],
    names: set[str],
    helper: str,
    rel: str,
    found: set[tuple[str, str]],
) -> None:
    """Record every REFERENCE to the helper, not only calls: a call, a bare name (including an
    import alias), an attribute through any receiver, a `partial` or `map` argument, or a string
    handed to `getattr`. Import statements, `def` names and `__all__` are not references."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.Import, ast.ImportFrom)) or _is_all_assignment(child):
            continue
        inner = scope
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            inner = (*scope, child.name)
        hit = (
            (isinstance(child, ast.Name) and child.id in names)
            or (isinstance(child, ast.Attribute) and child.attr in names)
            or (isinstance(child, ast.Constant) and child.value == helper)
        )
        if hit:
            found.add((rel, ".".join(scope)))
        _walk(child, inner, names, helper, rel, found)


def references(source: str, rel: str, helper: str) -> set[tuple[str, str]]:
    tree = ast.parse(source)
    found: set[tuple[str, str]] = set()
    _walk(tree, (), _aliases(tree, helper), helper, rel, found)
    return found


def _callers(helper: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in sorted(ROOT.rglob("*.py")):
        found |= references(
            path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix(), helper
        )
    return found


@pytest.mark.parametrize("helper", sorted(ALLOWED))
def test_only_allowlisted_functions_call_the_helper(helper: str) -> None:
    got = _callers(helper)
    allowed = set(ALLOWED[helper])
    assert got == allowed, {"unlisted": sorted(got - allowed), "stale": sorted(allowed - got)}


def test_every_allowlist_row_has_a_reason() -> None:
    assert all(reason.strip() for rows in ALLOWED.values() for reason in rows.values())


# -- the set's contents -------------------------------------------------------------------------


@pytest.mark.parametrize("cls", ["plain", "fk", "declared", "anchor", "top_code", "group_key"])
def test_the_adapter_ingests_with_the_union_of_every_role(tmp_path: Path, cls: str) -> None:
    """Spy on the one construction: the column `v` is in the set `PandasExecutionAdapter.run`
    converts with, whichever role it plays (or none: a `when:` reads it)."""
    from unittest import mock

    from decoy_engine.execution import _fk_keys, _pandas_adapter
    from decoy_engine.execution._pipeline import run_pipeline
    from tests.native._chunked_entry_support import key_provider
    from tests.unit.execution._o1_when_support import build_case

    # Only the `plain` column is in the set because a `when:` reads it; every other role must put
    # `v` there by itself, so the predicate reads `id` instead.
    cfg, tables = build_case(cls, tmp_path, "v == 5" if cls == "plain" else "id == 5")
    seen: list[_fk_keys.LosslessInts] = []
    real = _fk_keys.lossless_int_columns

    def spy(*args: object, **kwargs: object) -> _fk_keys.LosslessInts:
        out = real(*args, **kwargs)
        seen.append(out)
        return out

    with mock.patch.object(_pandas_adapter, "lossless_int_columns", spy):
        run_pipeline(
            cfg,
            tables,
            engine_version="o1",
            key_provider=key_provider(),
            execution_mode="full_frame",
            auto_chunk=False,
            unified_slice_enabled=False,
        )
    assert seen, "the adapter did not build its ingestion set through lossless_int_columns"
    assert "v" in seen[0].for_table("t"), (cls, seen[0])


# -- seeded bypass spellings: each must be seen by the scanner ----------------------------------

_SEEDS = {
    "alias import, call": (
        "from decoy_engine.execution._fk_keys import to_pandas_fk_safe as tp\n"
        "def f(t):\n    return tp(t, set())\n"
    ),
    "alias import, value": (
        "from decoy_engine.execution._fk_keys import to_pandas_fk_safe as tp\n"
        "def f(ts):\n    return list(map(tp, ts))\n"
    ),
    "functools.partial": (
        "import functools\nfrom decoy_engine.execution._fk_keys import to_pandas_fk_safe\n"
        "def f():\n    return functools.partial(to_pandas_fk_safe, cols=set())\n"
    ),
    "module attribute": (
        "import decoy_engine.execution._fk_keys as fk\ndef f(t):\n    return fk.to_pandas_fk_safe(t, set())\n"
    ),
    "getattr string": (
        "import decoy_engine.execution._fk_keys as fk\n"
        "def f():\n    return getattr(fk, 'to_pandas_fk_safe')\n"
    ),
}


@pytest.mark.parametrize("name", sorted(_SEEDS))
def test_the_scanner_sees_each_bypass_spelling(name: str) -> None:
    assert references(_SEEDS[name], "x.py", "to_pandas_fk_safe") == {("x.py", "f")}, name


def test_imports_definitions_and_all_are_not_references() -> None:
    src = (
        "from m import to_pandas_fk_safe\n__all__ = ['to_pandas_fk_safe']\n"
        "def to_pandas_fk_safe_other():\n    pass\n"
    )
    assert references(src, "x.py", "to_pandas_fk_safe") == set()


# -- the config-side construction agrees with the plan-side one --------------------------------


@pytest.mark.parametrize(
    ("cls", "expression"),
    [
        ("plain", "v == 5"),  # a null-bearing integer a `when:` reads
        ("plain", "id == 5"),  # a null-free integer a `when:` reads: not converted
        ("declared", "id == 5"),
        ("group_key", "id == 5"),
        ("group_key", "v == 5"),
    ],
)
def test_the_unified_config_set_equals_the_plan_set(
    tmp_path: Path, cls: str, expression: str
) -> None:
    """`lossless_int_columns_from_config` (unified admission has no plan) must return what
    `lossless_int_columns` returns for the same job, so the two cannot drift."""
    from decoy_engine.execution._chunked_profile import first_chunk_profile
    from decoy_engine.execution._fk_keys import (
        lossless_int_columns,
        lossless_int_columns_from_config,
    )
    from decoy_engine.plan import compile_plan
    from decoy_engine.providers_v2 import get_default_registry
    from decoy_engine.relationships import RelationshipGraph
    from tests.unit.execution._o1_when_support import build_case

    cfg, tables = build_case(cls, tmp_path, expression)
    source = tables["t"]
    profile = first_chunk_profile(source, table="t", engine_version="o1")
    plan = compile_plan(
        cfg, profile, decoy_engine_version="o1", no_profile=True, sources=NO_SOURCES
    )
    graph = RelationshipGraph(edges=(), ordering=())
    want = lossless_int_columns(plan, get_default_registry(), graph).for_table("t", source)
    assert lossless_int_columns_from_config(cfg, "t", source) == want, (cls, expression)
    # Only the null-free `when:` read is legitimately empty; every other case must name `v`.
    assert bool(want) == (expression != "id == 5" or cls != "plain"), (cls, expression, want)


@pytest.mark.parametrize(
    ("config", "want"),
    [
        ({"group_by": "g"}, "g"),
        ({"group_by": ""}, None),
        ({"group_by": 3}, None),
        ({}, None),
        (None, None),
    ],
)
def test_group_by_sibling_is_the_one_reader(
    config: dict[str, object] | None, want: str | None
) -> None:
    """An empty or non-string `group_by` is never a real column, on the plan and config routes."""
    from decoy_engine.execution._runner import group_by_sibling

    assert group_by_sibling(config) == want
