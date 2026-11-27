"""`PooledSelector.PICK_METHODS` lists every public method that draws pool indices.

Observers and mutants of the pooled pick (the F0 witness, the bench worker's vacuity guard, the
F-audit mutants) read that list. A public method that draws but is not listed would be invisible
to all of them, so this sentry calls each public method and checks the list against `_indices`.
"""

from __future__ import annotations

import inspect
from typing import Any

import numpy as np
import pytest

from decoy_engine.generation._faker_pool import PooledSelector


def _selector() -> PooledSelector:
    return PooledSelector(np.array(["a", "b", "c", "d"], dtype=object), b"\x01" * 8)


def _public_methods() -> list[str]:
    return [
        name
        for name, member in inspect.getmembers(PooledSelector)
        if not name.startswith("_") and inspect.isfunction(member)
    ]


def _reached_indices(monkeypatch: pytest.MonkeyPatch, method: str) -> bool:
    reached: list[int] = []
    real = PooledSelector._indices

    def spy(self: PooledSelector, size: int) -> Any:
        reached.append(size)
        return real(self, size)

    monkeypatch.setattr(PooledSelector, "_indices", spy)
    getattr(_selector(), method)(3)
    return bool(reached)


def test_the_pick_methods_are_the_list_and_arrow_entry_points() -> None:
    assert PooledSelector.PICK_METHODS == ("select", "take")


def test_no_public_method_draws_indices_outside_the_pick_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unlisted = [
        name
        for name in _public_methods()
        if name not in PooledSelector.PICK_METHODS and _reached_indices(monkeypatch, name)
    ]
    assert unlisted == []


def test_every_listed_method_is_a_public_method_that_draws_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in PooledSelector.PICK_METHODS:
        assert name in _public_methods()
        assert _reached_indices(monkeypatch, name), name
