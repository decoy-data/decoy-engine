"""CODE-SET-NATIVE S1 (AT-4): the handler memo against the pre-memo loop.

Both run in one process on the same sample: 200,000 rows over 2,000 distinct
codes. Only the ratio is asserted, since the default gate runs `perf`.
"""

from __future__ import annotations

import time

import pandas as pd
import pytest

from decoy_engine.execution._strategies._code_set import CodeSetHandler
from tests.unit.execution.test_code_set_memo import _base_run, _ctx, _seed

pytestmark = pytest.mark.perf


def _timed(fn, df: pd.DataFrame, plan) -> float:
    start = time.perf_counter()
    fn(df.copy(deep=True), "c", plan, _ctx())
    return time.perf_counter() - start


def test_memo_is_at_least_15x_faster_on_repeated_codes() -> None:
    plan = _seed({"code_set": "icd10", "mode": "mask", "chapter_preserve": False})
    codes = [f"A{i // 100:02d}.{i % 100}" for i in range(2_000)]
    df = pd.DataFrame({"c": pd.Series([codes[i % 2_000] for i in range(200_000)], dtype=object)})
    base = _timed(_base_run, df, plan)
    memo = _timed(CodeSetHandler().run, df, plan)
    ratio = base / memo
    print(f"code_set memo: base {base:.2f}s memo {memo:.2f}s ratio {ratio:.1f}x")
    assert ratio >= 15
