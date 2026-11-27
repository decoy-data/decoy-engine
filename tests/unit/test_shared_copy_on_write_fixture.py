"""`copy_on_write` is a shared fixture: it resolves for a test outside `tests/unit/execution`,
so a run that names paths from several directories finds it for every file."""

from __future__ import annotations

import pandas as pd


def test_the_fixture_sets_the_pandas_option(copy_on_write: bool) -> None:
    assert pd.get_option("mode.copy_on_write") is copy_on_write
