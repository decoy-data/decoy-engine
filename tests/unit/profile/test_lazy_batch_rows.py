"""One `batch_rows` validator for every lazy backend: a real int >= 1, checked at the call."""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.profile._lazy_csv import CsvLazySource
from decoy_engine.profile._lazy_fixed_width import FixedWidthLazySource
from decoy_engine.profile._readers import LazySource

_LAYOUT = {"columns": [{"name": "a", "start": 0, "width": 3}]}


def _csv(tmp: Path) -> Any:
    path = tmp / "f.csv"
    path.write_bytes(b"a\n" + b"x\n" * 7)
    return CsvLazySource(path)


def _fixed(tmp: Path) -> Any:
    path = tmp / "f.dat"
    path.write_bytes(b"abc\n" * 7)
    return FixedWidthLazySource.from_descriptor({"path": str(path), "layout": _LAYOUT}, table="t")


def _parquet(tmp: Path) -> Any:
    path = tmp / "f.parquet"
    pq.write_table(pa.table({"a": ["x"] * 7}), path)
    return LazySource(path)


BACKENDS: dict[str, Callable[[Path], Any]] = {"csv": _csv, "fixed": _fixed, "parquet": _parquet}
BAD = [True, False, 1.5, 2.0, math.nan, math.inf, "2", None, 0, -1]


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("bad", BAD, ids=repr)
def test_a_bad_batch_size_is_refused_at_the_call(tmp_path: Path, backend: str, bad: Any) -> None:
    src = BACKENDS[backend](tmp_path)
    with pytest.raises(ValueError, match="batch_rows"):
        src.iter_batches(bad)  # not deferred to the first next()
    with pytest.raises(ValueError, match="batch_rows"):
        src.open_batches(bad)


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("good", [1, 3])
def test_a_real_int_batch_size_reads_every_row(tmp_path: Path, backend: str, good: int) -> None:
    src = BACKENDS[backend](tmp_path)
    sizes = [b.num_rows for b in src.iter_batches(good)]
    assert sum(sizes) == 7 and max(sizes) == good
    opened = src.open_batches(good)
    assert sum(b.num_rows for b in opened.batches) == 7
    opened.close()
