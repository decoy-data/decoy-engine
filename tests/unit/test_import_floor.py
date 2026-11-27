"""AT-V11 (DATE-RANGE-SENTINEL S5, section 4.4b item 7): the engine imports on the declared
pyarrow floor.

The metadata rebuilder table named list-view predicates that pyarrow added after the floor, so
`import decoy_engine` raised on pyarrow 14 before any checked read ran. This test starts a fresh
interpreter outside the checkout and imports the installed engine. It uses nothing but the
standard library, so it collects on any pyarrow; the floor leg sets `DECOY_FLOOR_PYARROW` to the
exact version it expects the interpreter to report."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROGRAM = (
    "import pyarrow; print(pyarrow.__version__); "
    "import decoy_engine; from decoy_engine.io import check_source_dates; print('imported')"
)


def test_the_installed_engine_imports_in_a_fresh_interpreter_outside_the_checkout(
    tmp_path: Path,
) -> None:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    done = subprocess.run(  # noqa: S603 - fixed argv, no input
        [sys.executable, "-I", "-c", PROGRAM],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-400:]
    version, marker = done.stdout.split()
    assert marker == "imported"
    expected = os.environ.get("DECOY_FLOOR_PYARROW")
    if expected:
        assert version == expected
