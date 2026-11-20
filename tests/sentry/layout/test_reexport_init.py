"""Self-tests for the physical-import scanner in `_reexport_init.py` (relative and star imports
included)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.sentry.layout._reexport_init import imports_physical


def _scan(tmp_path: Path, rel: str, body: str) -> bool:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return imports_physical(path, tmp_path)


@pytest.mark.parametrize(
    ("rel", "body"),
    [
        ("execution/x.py", "from decoy_engine.execution.physical import plan\n"),
        ("execution/x.py", "from decoy_engine.execution.physical._types import T\n"),
        ("execution/x.py", "import decoy_engine.execution.physical\n"),
        ("execution/x.py", "from decoy_engine.execution import physical\n"),
        ("execution/x.py", "def f():\n    from decoy_engine.execution.physical import p\n"),
        ("execution/__init__.py", "from .physical import compile_physical_plan\n"),
        ("execution/__init__.py", "from .physical import *\n"),
        ("execution/__init__.py", "from . import physical\n"),
        ("execution/sub/__init__.py", "from ..physical import plan\n"),
        ("execution/sub/mod.py", "from ..physical._types import T\n"),
        ("execution/sub/mod.py", "from ... execution.physical import T\n"),
        ("execution/x.py", "from .physical import (\n    a,\n)\n"),
        ("execution/x.py", "from . import (\n    physical,\n)\n"),
        ("execution/x.py", "from physical import (\n  a\n  # physical syntax error\n"),
        (
            "execution/x.py",
            'import importlib\nimportlib.import_module("decoy_engine.execution.physical")\n',
        ),
        (
            "execution/x.py",
            'import importlib as loader\nloader.import_module("decoy_engine.execution.physical._types")\n',
        ),
        (
            "execution/x.py",
            'import importlib.util\nimportlib.import_module("decoy_engine.execution.physical")\n',
        ),
        (
            "execution/x.py",
            'from importlib import import_module\nimport_module("decoy_engine.execution.physical")\n',
        ),
        (
            "execution/x.py",
            'from importlib import import_module as load\nload(name="decoy_engine.execution.physical")\n',
        ),
        (
            "execution/x.py",
            'import importlib\nif flag:\n    importlib.import_module(".physical", "decoy_engine.execution")\n',
        ),
        (
            "execution/sub/x.py",
            'import importlib\nimportlib.import_module("..physical", package="decoy_engine.execution.sub")\n',
        ),
        ("execution/x.py", '__import__("decoy_engine.execution.physical")\n'),
        ("execution/x.py", 'if flag:\n    __import__(name="decoy_engine.execution.physical")\n'),
        ("execution/x.py", '__import__("decoy_engine.execution", fromlist=["physical"])\n'),
    ],
)
def test_every_spelling_of_the_seam_import_is_found(tmp_path: Path, rel: str, body: str) -> None:
    assert _scan(tmp_path, rel, body)


@pytest.mark.parametrize(
    ("rel", "body"),
    [
        ("execution/x.py", "from decoy_engine.execution import chunked\n"),
        ("execution/x.py", "from .chunked import run\n"),
        ("execution/sub/mod.py", "from . import physical_notes\n"),
        ("execution/__init__.py", "from .other import physical_plan\n"),
        ("execution/x.py", '"""mentions physical in prose"""\n'),
        ("sub/x.py", "from .physical import a\n"),  # sub/physical is not the seam
        (
            "execution/x.py",
            'import importlib\nimportlib.import_module("decoy_engine.execution.chunked")\n',
        ),
        (
            "execution/x.py",
            'import importlib\nimportlib.import_module(".chunked", "decoy_engine.execution")\n',
        ),
        ("execution/x.py", '__import__("decoy_engine.execution", fromlist=["chunked"])\n'),
        ("execution/x.py", 'import json\njson.import_module("decoy_engine.execution.physical")\n'),
        (
            "execution/x.py",
            'import importlib\nimportlib.import_module("decoy_engine.exec" + "ution.physical")\n',
        ),  # built up: V2-LOG
    ],
)
def test_other_imports_are_not_the_seam(tmp_path: Path, rel: str, body: str) -> None:
    assert not _scan(tmp_path, rel, body)
