"""Resident-table authority cannot be forgotten: `compile_plan`, `compile_native_plan` and
`build_column_shapes` require `sources: SourceFacts` with no default, and every call under
`src/` passes it. A caller with no tables passes `NO_SOURCES` on purpose."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from decoy_engine.execution.native._plan import compile_native_plan
from decoy_engine.plan import compile_plan
from decoy_engine.plan.checks import check_required_strategy_settings
from decoy_engine.plan.checks._column_shapes import build_column_shapes

SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
GUARDED = {
    "compile_plan",
    "compile_native_plan",
    "build_column_shapes",
    "check_required_strategy_settings",
}


def _name(func: ast.expr) -> str | None:
    return func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)


def _calls_without_sources(root: Path) -> list[str]:
    bad: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and _name(node.func) in GUARDED:
                if "sources" not in {k.arg for k in node.keywords}:
                    bad.append(f"{path.relative_to(root)}:{node.lineno}")
    return bad


@pytest.mark.parametrize(
    "fn", [compile_plan, compile_native_plan, build_column_shapes, check_required_strategy_settings]
)
def test_sources_is_a_required_keyword(fn: object) -> None:
    param = inspect.signature(fn).parameters["sources"]  # type: ignore[arg-type]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty


def test_every_call_site_passes_sources() -> None:
    assert _calls_without_sources(SRC) == []


def test_the_scan_flags_a_call_that_omits_it(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("compile_plan(c, p, decoy_engine_version='v')\n")
    (tmp_path / "ok.py").write_text("compile_plan(c, p, sources=NO_SOURCES)\n")
    assert _calls_without_sources(tmp_path) == ["m.py:1"]
