"""Fixtures for the publication unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fileaccess.publication._chain_support import anchor_at
from tests.unit.publication._stage_support import Run


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Run:
    anchor_at(monkeypatch, tmp_path)
    return Run(tmp_path)
