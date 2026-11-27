"""One spy over every `PooledSelector` pick entry point (test-side only).

The pooled draw has two public entry points, `select` (Python list, for list consumers) and
`take` (Arrow array), both listed in `PooledSelector.PICK_METHODS`. An observer that names only
one of them goes blind to a column that reaches the batch through the other. This spy reads the
constant, so a new entry point is seen as soon as it is listed.

Only the outermost entry is reported: if one entry point calls another, the pick is counted once.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from decoy_engine.generation import _faker_pool

OnPick = Callable[[str, "_faker_pool.PooledSelector", int, Any], None]


def picked_values(out: Any) -> list[Any]:
    """A pick's values as a Python list, whichever form the entry point returned."""
    to_pylist = getattr(out, "to_pylist", None)
    return list(to_pylist() if to_pylist is not None else out)


def install_pick_spy(mp: pytest.MonkeyPatch, on_pick: OnPick) -> None:
    """Wrap every pick method; `on_pick(method, selector, size, result)` runs per outer pick."""
    active = False

    def wrap(name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def spy(selector: Any, size: int) -> Any:
            nonlocal active
            if active:
                return real(selector, size)
            active = True
            try:
                out = real(selector, size)
            finally:
                active = False
            on_pick(name, selector, size, out)
            return out

        return spy

    for name in _faker_pool.PooledSelector.PICK_METHODS:
        mp.setattr(
            _faker_pool.PooledSelector, name, wrap(name, getattr(_faker_pool.PooledSelector, name))
        )


def count_picks(mp: pytest.MonkeyPatch) -> list[str]:
    """The entry point name of each outer pick, in order."""
    seen: list[str] = []
    install_pick_spy(mp, lambda name, _selector, _size, _out: seen.append(name))
    return seen
