"""Every `when/` test runs under copy-on-write off and on."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _both_copy_on_write_modes(copy_on_write: bool) -> None:
    return None
