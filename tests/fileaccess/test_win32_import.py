"""F26 AT-E14 (E1 cell): the descriptor leaf imports and runs where `fcntl` does not exist.

Plan `docs/plans/2026-11-16-f26-v1-rescope.md` 3.1 "Module layout" and 6.1 AT-E14. The leaf
is loaded a second time, from its file, in a fresh interpreter whose `fcntl` import fails, and it
must come up with no lock bound. The `test_win32_noop` cells for the reclaim functions join with
E2a and E3.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_CHILD = """
import importlib.util, os, sys
import decoy_engine.fileaccess._fdtree as shipped
sys.modules["fcntl"] = None  # `import fcntl` now raises ImportError
spec = importlib.util.spec_from_file_location("fdtree_nofcntl", shipped.__file__)
leaf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(leaf)
fd = os.open(".", os.O_RDONLY)
print(leaf.hold_stage_lock(fd), leaf.fcntl is None)
"""


def test_fileaccess_imports_without_fcntl(tmp_path: Path) -> None:
    done = subprocess.run(  # noqa: S603 -- static argv: sys.executable and a literal script
        [sys.executable, "-I", "-c", _CHILD],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["False", "True"]  # unlocked, and no fcntl bound
