"""Self-tests for the physical-seam helpers in `_reexport_init.py`: the pure re-export rule and the
one physical-import scanner (relative and star imports included)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.sentry.layout._reexport_init import imports_physical, is_pure_reexport_init


def test_pure_reexport_init_is_detected(tmp_path: Path) -> None:
    init = tmp_path / "__init__.py"
    init.write_text(
        '"""Doc."""\n\nfrom __future__ import annotations\n\nimport os\n'
        "from a.b import C\n\n"
        '__all__ = ["C"]\n'
    )
    assert is_pure_reexport_init(init)
    init.write_text("from a import B\n__all__ = ('B',)\n")
    assert is_pure_reexport_init(init)
    init.write_text("")
    assert is_pure_reexport_init(init)
    other = tmp_path / "mod.py"
    other.write_text("from a import B\n")
    assert not is_pure_reexport_init(other)  # only __init__.py files
    assert not is_pure_reexport_init(tmp_path / "missing" / "__init__.py")


@pytest.mark.parametrize(
    "body",
    [
        "def f(): pass\n",
        "class C: pass\n",
        "from a import B\nregister(B)\n",
        "from a import B\nX = 1\n",
        "from a import B\n__all__ = build_exports()\n",
        "from a import B\n__all__ = [n for n in dir()]\n",
        "from a import B\n__all__ = [B]\n",
        "from a import B\n__all__ += ['B']\n",
        "try:\n    from a import B\nexcept ImportError:\n    B = None\n",
        "from a import B\n'stray string'\n",
        "from a import *\n",
        "from .physical import *\n",
        "def broken(:\n",
    ],
)
def test_init_with_code_is_not_pure(tmp_path: Path, body: str) -> None:
    init = tmp_path / "__init__.py"
    init.write_text(body)
    assert not is_pure_reexport_init(init)


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
    ],
)
def test_other_imports_are_not_the_seam(tmp_path: Path, rel: str, body: str) -> None:
    assert not _scan(tmp_path, rel, body)
