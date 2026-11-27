"""The `copy_on_write` fixture, registered once from `tests/conftest.py`.

It lives here, not in `tests/unit/execution/conftest.py`, so a run that names test paths from
several directories finds it for every file (the same route `_scratch_env` takes). A directory
conftest is loaded only by the files collected under it, and a run given explicit paths hit
`fixture 'copy_on_write' not found` for a file whose directory conftest was not applied.
"""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd
import pytest


@pytest.fixture(params=[False, True], ids=["cow-off", "cow-on"])
def copy_on_write(request: pytest.FixtureRequest) -> Iterator[bool]:
    """Run the test under pandas `mode.copy_on_write` off and on. The engine does not pin the
    option for masking runs, and pandas 3 makes it the only mode, so execution must give the same
    output either way (plan revision 2.6, I3)."""
    with pd.option_context("mode.copy_on_write", request.param):
        yield request.param
