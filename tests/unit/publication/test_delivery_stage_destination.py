"""Destination agreement at `DeliveryStage.open` (DELIV E2b: AT-69).

The output folder must be the run's folder: its exact leaf is the run id and its parent is the
pointer's parent folder. The check runs before any pointer read, lock or stage.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.publication import (
    CurrentPointer,
    DeliveryStage,
    LocalPointerStore,
    PointerState,
)
from tests.fileaccess.publication._chain_support import anchor_at
from tests.fileaccess.publication._dirmode_support import POLICIES
from tests.unit.publication._publish_support import close_root, make_out

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX durable pointer")


class SpyStore(LocalPointerStore):
    """A pointer store that records every call, so a refusal can prove it read nothing."""

    def __init__(self, leaf: Any) -> None:
        super().__init__(leaf)
        self.calls: list[str] = []

    def read(self) -> PointerState:
        self.calls.append("read")
        return super().read()


class Setup:
    def __init__(self, policy: str, base: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.policy, self.base = policy, base
        if policy == "ambient":
            anchor_at(monkeypatch, base)
        for folder in ("out/n", "out/other"):
            (base / folder).mkdir(parents=True)
        (base / "out" / "alias").symlink_to("n")
        self.roots: list[int] = []
        leaf, root = make_out(policy, base, "out/n/LATEST")
        self.roots.append(root)
        self.store = SpyStore(leaf)
        self.pointer = CurrentPointer(self.store, leaf)

    def out(self, rel: str) -> Any:
        out, root = make_out(self.policy, self.base, rel)
        self.roots.append(root)
        return out

    def open(self, rel: str, run_id: str) -> DeliveryStage:
        return DeliveryStage.open(self.out(rel), self.pointer, run_id, "op-1")

    def stages(self) -> list[str]:
        return sorted(p.name for p in self.base.rglob("._decoy*"))


@pytest.fixture
def setup(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    made = Setup(request.param, tmp_path, monkeypatch)
    yield made
    for root in made.roots:
        close_root(root)


@pytest.mark.parametrize("setup", POLICIES, indirect=True)
@pytest.mark.parametrize(
    ("rel", "run_id"),
    [("out/n/foo\\r1", "r1"), ("out/other/r1", "r1"), ("out/n/r2", "r1")],
    ids=["tail-after-backslash", "other-parent", "other-leaf"],
)
def test_a_destination_that_is_not_the_run_folder_is_refused_before_anything_happens(
    setup: Setup, rel: str, run_id: str
) -> None:
    with pytest.raises(ValueError) as caught:
        setup.open(rel, run_id)
    assert caught.value.__context__ is None and "foo" not in str(caught.value)
    assert setup.store.calls == [] and setup.stages() == []


@pytest.mark.parametrize("setup", POLICIES, indirect=True)
def test_the_real_parent_and_exact_leaf_open(setup: Setup) -> None:
    stage = setup.open("out/n/r1", "r1")
    assert setup.store.calls == ["read"] and len(setup.stages()) == 2
    stage.abort()
    assert setup.stages() == []


@pytest.mark.parametrize("setup", POLICIES[1:], indirect=True)
def test_ambient_access_opens_a_symlinked_spelling_of_the_same_parent(setup: Setup) -> None:
    stage = setup.open("out/alias/r1", "r1")
    assert setup.store.calls == ["read"]
    stage.abort()


@pytest.mark.parametrize("setup", POLICIES[:1], indirect=True)
def test_a_strict_root_refuses_a_symlink_beneath_it_before_any_read(setup: Setup) -> None:
    with pytest.raises(ValueError):
        setup.open("out/alias/r1", "r1")
    assert setup.store.calls == [] and setup.stages() == []
