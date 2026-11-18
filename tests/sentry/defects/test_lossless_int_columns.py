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


def _call_name(node: ast.Call) -> str:
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def _walk(
    node: ast.AST, scope: tuple[str, ...], helper: str, rel: str, found: set[tuple[str, str]]
) -> None:
    for child in ast.iter_child_nodes(node):
        inner = scope
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            inner = (*scope, child.name)
        if isinstance(child, ast.Call) and _call_name(child) == helper:
            found.add((rel, ".".join(scope)))
        _walk(child, inner, helper, rel, found)


def _callers(helper: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        _walk(tree, (), helper, path.relative_to(ROOT).as_posix(), found)
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

    cfg, tables = build_case(cls, tmp_path, "v == 5")
    seen: list[dict[str, set[str]]] = []
    real = _fk_keys.lossless_int_columns

    def spy(*args: object, **kwargs: object) -> dict[str, set[str]]:
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
    assert "v" in seen[0].get("t", set()), (cls, seen[0])
