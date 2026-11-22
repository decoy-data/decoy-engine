"""O1 sentry: a `group_key` sibling is read from `provider_config["group_by"]` in one place.

`group_by_sibling` decides that an empty or non-string `group_by` is not a column. The plan walker,
unified admission and the chunked gates all go through it. A second reader drifts: the plan-side
set and the config-side set then disagree about which columns ingest losslessly.

Any other direct read in `execution/` fails unless its exact `(path, function)` is listed with a
reason. The listed readers are not `group_key` siblings or validate the raw value on purpose.
"""

from __future__ import annotations

import ast
from pathlib import Path

from decoy_engine.contracts.column_shape import NO_SOURCES

ROOT = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"
KEY = "group_by"
HELPER = ("execution/_runner.py", "group_by_sibling")

ALLOWED: dict[tuple[str, str], str] = {
    HELPER: "the one reader",
    (
        "execution/_transforms.py",
        "_structured_references",
    ): "date_shift anchors, not a group_key sibling",
    ("execution/_strategies/_date_shift.py", "DateShiftStrategyHandler.run"): "date_shift anchor",
    ("execution/native/_operator_config_rejections.py", "date_shift_config_rejection"): (
        "date_shift: any truthy value declines the native lane"
    ),
    ("execution/native/_operator_config_rejections.py", "group_key_config_rejection"): (
        "reports the exact rejection reason for a missing or malformed value"
    ),
    ("execution/native/_operator_params.py", "resolve_operator_params"): (
        "config gate has already proved the value"
    ),
}


def _is_read(node: ast.AST) -> bool:
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value == KEY
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("get", "pop", "setdefault")
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == KEY
    )


def _walk(node: ast.AST, scope: tuple[str, ...], rel: str, out: set[tuple[str, str]]) -> None:
    for child in ast.iter_child_nodes(node):
        inner = scope
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            inner = (*scope, child.name)
        if _is_read(child):
            out.add((rel, ".".join(scope)))
        _walk(child, inner, rel, out)


def readers(source: str, rel: str) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    _walk(ast.parse(source), (), rel, out)
    return out


def _all_readers() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in sorted((ROOT / "execution").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        found |= readers(path.read_text(encoding="utf-8"), rel)
    return found


def test_no_second_direct_group_by_reader() -> None:
    extra = _all_readers() - ALLOWED.keys()
    assert not extra, f"read the group_by sibling through group_by_sibling: {sorted(extra)}"


def test_every_allowed_reader_still_exists() -> None:
    stale = ALLOWED.keys() - _all_readers()
    assert not stale, f"drop stale allowlist rows: {sorted(stale)}"


def test_seeded_spellings_are_found() -> None:
    for src in (
        "def f(c):\n    return c.get('group_by')\n",
        "def f(c):\n    return c['group_by']\n",
        "def f(c):\n    return (c or {}).get('group_by', None)\n",
        "def f(c):\n    return c.pop('group_by')\n",
    ):
        assert readers(src, "execution/x.py") == {("execution/x.py", "f")}, src
    assert readers("def f(c):\n    return c.get('other')\n", "x.py") == set()


def test_the_plan_side_set_names_the_sibling(tmp_path: Path) -> None:
    """Absolute, not relative to the config route: a reader that finds nothing would still
    make the two routes agree."""
    from decoy_engine.execution._chunked_profile import first_chunk_profile
    from decoy_engine.execution._runner import group_key_group_by_columns
    from decoy_engine.plan import compile_plan
    from decoy_engine.providers_v2 import get_default_registry
    from tests.unit.execution._o1_when_support import build_case

    cfg, tables = build_case("group_key", tmp_path, "id == 5")
    profile = first_chunk_profile(tables["t"], table="t", engine_version="o1")
    plan = compile_plan(
        cfg, profile, decoy_engine_version="o1", no_profile=True, sources=NO_SOURCES
    )
    assert group_key_group_by_columns(plan, get_default_registry()) == {"t": {"v"}}
