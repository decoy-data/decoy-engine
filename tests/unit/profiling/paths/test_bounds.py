"""F07 82-E2b: memory bounds of path observation (the cell cap and native containers)."""

from __future__ import annotations

import tracemalloc
from collections.abc import Callable, Iterator
from typing import Any

import numpy as np
import pandas as pd
import pytest

from decoy_engine._canonical import SCAN_CELL_BYTES, SCAN_MAX_CELLS
from decoy_engine.profiling import paths
from decoy_engine.profiling.paths import _observe, _walk


def _high_water(work: Callable[[], Any]) -> int:
    """The most memory Python objects held at once while `work` ran, in bytes."""
    tracemalloc.start()
    try:
        work()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_cells_stop_at_the_cap_without_copying_the_column() -> None:
    # One million rows that all hold the same text, so the column itself costs nothing here.
    series = pd.Series(np.full(1_000_000, '{"a": 1}', dtype=object))
    found: list[Any] = []
    high = _high_water(lambda: found.extend(_observe._cells(series)))
    assert len(found) == SCAN_MAX_CELLS
    assert high < 1_000_000  # a copy of the column alone is 8 MB


def test_cells_skip_nulls_and_keep_container_cells() -> None:
    mixed = [None, float("nan"), pd.NA, {"a": 1}, [1, 2], np.array([1, 2]), "text", (3,)]
    cells = _observe._cells(pd.Series(mixed, dtype=object))
    assert len(cells) == 5 and cells[0] == {"a": 1}
    long = pd.Series([None] * 100 + ["{}"] * (SCAN_MAX_CELLS + 10), dtype=object)
    assert len(_observe._cells(long)) == SCAN_MAX_CELLS


def _column(odd: Any) -> pd.Series:
    return pd.Series([{"a": 1}, {"a": 2}, {"a": 3}, odd], dtype=object)


@pytest.mark.parametrize(
    "odd",
    [
        {"a": "x" * SCAN_CELL_BYTES},
        {"a": ["y"] * SCAN_CELL_BYTES},
        [0] * (SCAN_CELL_BYTES + 1),
        np.zeros(SCAN_CELL_BYTES + 1, dtype=np.int8),
        {f"k_{n}": 0 for n in range(SCAN_CELL_BYTES // 8)} | {"z": "x" * SCAN_CELL_BYTES},
    ],
    ids=["long-text", "long-list-below-a-key", "long-list", "long-array", "keys-and-text"],
)
def test_a_native_cell_over_the_byte_limit_is_oversized(odd: Any) -> None:
    obs = paths.observe_column(_column(odd))
    assert obs is not None and obs.cells_oversized == 1 and obs.cells_parsed == 3


def test_a_native_cell_under_the_byte_limit_is_read() -> None:
    obs = paths.observe_column(_column({"a": "x" * (SCAN_CELL_BYTES // 2), "b": [0] * 1000}))
    assert obs is not None and obs.cells_oversized == 0 and obs.cells_parsed == 4


def test_a_huge_native_mapping_is_refused_before_it_is_visited() -> None:
    class Wide(dict[str, int]):
        visited = 0

        def __len__(self) -> int:
            return 10**9

        def items(self) -> Iterator[tuple[str, int]]:  # type: ignore[override]
            for n in range(2000):
                Wide.visited += 1
                yield f"k_{n}", n

    obs = paths.observe_column(_column(Wide()))
    assert obs is not None and obs.cells_oversized == 1
    assert Wide.visited == 0


def test_a_big_native_mapping_is_walked_without_building_its_pairs() -> None:
    # 80,000 members that fit the byte limit. Building a pair for each is megabytes; a lazy walk
    # holds none of them.
    mapping = {f"k{n:06d}": n for n in range(80_000)}

    def observe_once() -> None:
        levels = _walk.Levels()
        levels.cell = 0
        _walk.walk(mapping, levels.scout, lambda pattern, value: True)
        levels.finalize()
        tally = _walk.Tally()
        _walk.walk(mapping, levels.settle, tally.record)

    assert _high_water(observe_once) < 1_500_000
