"""F26 AT-E14 (E1 cell): the descriptor leaf imports and runs where `fcntl` does not exist.

Plan `docs/plans/2026-11-16-f26-v1-rescope.md` 3.1 "Module layout" and 6.1 AT-E14. The leaf is
loaded from its file in a fresh interpreter whose `fcntl` import fails and whose `sys.platform`
reads win32. Loading it by file, with no package import, also proves it needs only the standard
library. The `test_win32_noop` cells for the reclaim functions join with E2a and E3.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import decoy_engine

LEAF = Path(decoy_engine.__file__).parent / "fileaccess" / "_fdtree.py"

_CHILD = """
import importlib.util, os, sys
sys.modules["fcntl"] = None  # `import fcntl` now raises ImportError
sys.platform = "win32"
spec = importlib.util.spec_from_file_location("fdtree_leaf", sys.argv[1])
leaf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(leaf)
assert not [m for m in sys.modules if m.startswith("decoy_engine")], "leaf imported the package"
fd = os.open(".", os.O_RDONLY)
print(leaf.hold_stage_lock(fd), "fcntl" in vars(leaf))
"""


def test_fileaccess_imports_without_fcntl(tmp_path: Path) -> None:
    done = subprocess.run(  # noqa: S603 -- static argv: sys.executable and a literal script
        [sys.executable, "-I", "-c", _CHILD, str(LEAF)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["False", "False"]  # unlocked, and fcntl was never bound


def test_win32_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AT-E14 (E2a cell): on win32 the stage reclaim returns an empty report and touches nothing."""
    from decoy_engine.fileaccess import ReclaimReport, reclaim_stages
    from tests.fileaccess.publication._reclaim_support import make_stage, snapshot

    make_stage(tmp_path)
    before = snapshot(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    assert reclaim_stages(tmp_path, apply=False, min_age_s=0) == ReclaimReport()
    assert snapshot(tmp_path) == before
