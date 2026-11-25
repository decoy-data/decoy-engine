"""Shared pieces for the AT-X2, AT-X3 and AT-X4 tests: a rooted tree whose files sit under a
directory carrying a sentinel, a spy on the locator handed to each library, and renderers."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from decoy_engine.fileaccess import _rooted
from tests.fileaccess.support import RootRelative
from tests.security._surfaces import rendered  # noqa: F401 - re-exported for the X tests

LOCATOR_SENTINEL = "LOCSENT" + uuid.uuid4().hex[:10]


@dataclass
class XWorld:
    root: Path
    sub: Path
    policy: RootRelative
    library_paths: list[str] = field(default_factory=list)

    def forbidden(self) -> list[str]:
        """Every string that must never appear: the sentinel directory, the root, the path
        handed to each library (`/proc/self/fd/<n>`), and the descriptor directory itself."""
        return [LOCATOR_SENTINEL, str(self.root), "/proc/self/fd", *self.library_paths]


@pytest.fixture
def xworld(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[XWorld]:
    root = tmp_path / "root"
    sub = root / LOCATOR_SENTINEL
    sub.mkdir(parents=True)
    policy = RootRelative(root)
    world = XWorld(root, sub, policy)
    real = _rooted.FdHandle.library_path

    def spy(self: _rooted.FdHandle) -> str:
        value = real(self)
        world.library_paths.append(value)
        return value

    monkeypatch.setattr(_rooted.FdHandle, "library_path", spy)
    try:
        yield world
    finally:
        policy.close()


def assert_no_locator(world: XWorld, texts: list[str]) -> None:
    for text in texts:
        for needle in world.forbidden():
            assert needle not in text, f"{needle!r} leaked in: {text[:300]!r}"
