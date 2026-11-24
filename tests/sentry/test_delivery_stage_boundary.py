"""The delivery stage makes no file-system call of its own (DELIV E2b: AT-72).

`publication/_stage.py` reaches the file system only through `StageDir`, `OutputTxn` and
`OutputDir`. An exact-name AST check: no `os`, `shutil` or `pathlib` import outside a
`TYPE_CHECKING` block (where `Path` is allowed for annotations), no `os` or `shutil` name use,
and no call of the builtin `open`. The check is run on seeded sources too, so it can fail.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

STAGE = Path(__file__).parents[2] / "src" / "decoy_engine" / "publication" / "_stage.py"
BANNED = {"os", "shutil", "pathlib"}


def _type_checking_nodes(tree: ast.AST) -> set[int]:
    inside: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and (
            (isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING")
            or (isinstance(node.test, ast.Attribute) and node.test.attr == "TYPE_CHECKING")
        ):
            for child in node.body:
                inside.update(id(n) for n in ast.walk(child))
    return inside


def violations(source: str) -> list[str]:
    tree = ast.parse(source)
    typing_only = _type_checking_nodes(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if id(node) in typing_only:
            continue
        if isinstance(node, ast.Import):
            found += [f"import {a.name}" for a in node.names if a.name.split(".")[0] in BANNED]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in BANNED:
            found.append(f"from {node.module} import")
        elif isinstance(node, ast.Name) and node.id in ("os", "shutil"):
            found.append(f"name {node.id}")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open"
        ):
            found.append("call open")
    return found


def test_the_delivery_stage_makes_no_file_system_call_of_its_own() -> None:
    assert violations(STAGE.read_text()) == []


@pytest.mark.parametrize(
    "source",
    [
        "import os\n",
        "import shutil\n",
        "import os.path\n",
        "from pathlib import Path\n",
        "from os import path\n",
        "x = os.stat('a')\n",
        "with open('a') as fh:\n    pass\n",
    ],
)
def test_the_check_catches_each_seeded_violation(source: str) -> None:
    assert violations(source) != []


def test_a_type_checking_import_of_path_is_the_one_exception() -> None:
    allowed = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from pathlib import Path\n"
    assert violations(allowed) == []
    assert violations("from pathlib import Path\n") != []
