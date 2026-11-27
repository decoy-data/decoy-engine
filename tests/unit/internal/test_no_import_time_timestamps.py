"""No module builds an out-of-range pandas `Timestamp` at import time (DATE-RANGE-SENTINEL S5 remediation
round 2, V1-1).

pandas 1.x holds nanosecond timestamps only, so a module-level `pd.Timestamp("1677-09-21 ...")`
raised `OutOfBoundsDatetime` while `decoy_engine` was importing, on every job. A timestamp
constant is built inside the function that needs it."""

from __future__ import annotations

import ast
from pathlib import Path

import decoy_engine

_SRC = Path(decoy_engine.__file__).parent


def _outside_nanosecond_range(call: ast.Call) -> bool:
    """True when the first argument is a date string pandas 1.x's nanosecond range (years 1678
    to 2261) cannot hold, so building it at import raised on the floor."""
    first = call.args[0] if call.args else None
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        return False
    year = first.value[:4]
    return year.isdigit() and not 1678 <= int(year) <= 2261


def module_level_timestamp_calls(text: str) -> list[int]:
    """Line numbers of statements that run at import and build a `Timestamp` outside the range: the
    module body and class bodies, not function bodies."""
    found: list[int] = []

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if isinstance(node, ast.ClassDef):
                visit(node.body)
                continue
            for call in ast.walk(node):
                if isinstance(call, ast.Call):
                    func = call.func
                    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                    if name == "Timestamp" and _outside_nanosecond_range(call):
                        found.append(call.lineno)

    visit(ast.parse(text).body)
    return found


def test_no_engine_module_builds_a_timestamp_when_it_is_imported() -> None:
    bad = {
        path.relative_to(_SRC).as_posix(): lines
        for path in sorted(_SRC.rglob("*.py"))
        if (lines := module_level_timestamp_calls(path.read_text()))
    }
    assert bad == {}


def test_the_scan_sees_a_module_level_timestamp() -> None:
    assert module_level_timestamp_calls('import pandas as pd\nX = pd.Timestamp("1677-09-21")\n')
    assert module_level_timestamp_calls("class C:\n    X = pd.Timestamp(1)\n")
    assert module_level_timestamp_calls("def f():\n    return pd.Timestamp(1)\n") == []
