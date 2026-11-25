"""GEN-STREAM-ALL S1a A2: the take path and the moved batch assembler change no output byte.

The digests below were captured at engine `origin/main` `9f7bb1f4a`, before `pool_take` and
`generation/stream/_batches.py` existed, for each legacy pooled type at 120,000 rows with
`null_probability: 0.1`.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.generation import _faker_pool, _streamed
from tests.parity import _f0_fixtures as fx
from tests.parity._fr0_support import run_resident, run_streamed
from tests.unit.generation.stream._support import LEGACY_TEN, faker_config, table_digest

MAIN_DIGESTS = {
    "first_name": "d588c77fcaa5f125020b6d1ba9e0e7f79bf1af2f3616527f998d2f533519e81a",
    "last_name": "97739c264eebf9146405e33cb58e3cf67c31cde8f500d1e4e887a7f7da0617c8",
    "name": "9732663fc0edcc7985b028a8bb5fec75130d1ac6fef4689ea59340f11b7844f7",
    "prefix": "298d37f761fce438dd5d53c3990da4425e5ea694c8f82473172a9ceeb67ad949",
    "suffix": "a5cb83ba4abaf3805e9af89d2639cd30fa0efdecc3f43482d6d64e0d19c255c2",
    "city": "d92cadef1014a5ee8561b885b3379f1720b6c6573866238401a1437075d751aa",
    "state": "3b64d474a83250713f8bb4f9b7039780b375adcc70f55ac749601697dc7d3f6d",
    "country": "4e3c25d343bb7434b46c2c506e614d3727c09a11efaee217052cfbcf2b4943d0",
    "job": "8641d3499f4e10aad3fcb4a6edb8ffc5edbcb46386116540ae9ec19f3e397b75",
    "company": "233d450472fbe0c0c3d279e10a0cf5d57f52ccf9fc59514a01e76d97b04747d3",
}
_ROWS = 120_000


def test_every_legacy_type_has_a_captured_digest() -> None:
    assert set(MAIN_DIGESTS) == set(LEGACY_TEN)


@pytest.mark.parametrize("faker_type", LEGACY_TEN)
def test_resident_bytes_equal_the_pre_take_digest(faker_type: str) -> None:
    cfg = faker_config(faker_type, _ROWS, null_probability=0.1)
    table = run_resident(cfg, batch_rows=4096)["t"]
    assert table_digest(table) == MAIN_DIGESTS[faker_type]


@pytest.mark.parametrize("faker_type", ["first_name", "company", "state"])
def test_sink_bytes_equal_the_pre_take_digest(faker_type: str, tmp_path: Path) -> None:
    cfg = faker_config(faker_type, _ROWS, null_probability=0.1)
    _, tables = run_streamed(cfg, tmp_path)
    assert table_digest(tables["t"]) == MAIN_DIGESTS[faker_type]


def test_the_assembler_lives_in_the_stream_package() -> None:
    batches = importlib.import_module("decoy_engine.generation.stream._batches")
    assert callable(getattr(batches, "table_batches", None))
    assert callable(getattr(batches, "check_width", None))
    assert not hasattr(_streamed, "_table_batches")
    assert not hasattr(_streamed, "_check_width")


def _count(monkeypatch: pytest.MonkeyPatch, name: str) -> list[int]:
    calls: list[int] = []
    real = getattr(_faker_pool.PooledSelector, name)

    def spy(self: Any, size: int) -> Any:
        calls.append(size)
        return real(self, size)

    monkeypatch.setattr(_faker_pool.PooledSelector, name, spy)
    return calls


def test_a_plain_pooled_column_reaches_the_batch_as_an_arrow_array_with_no_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    takes = _count(monkeypatch, "take")
    selects = _count(monkeypatch, "select")
    run_resident(faker_config("city", _ROWS), batch_rows=40_000)
    assert sum(takes) == _ROWS
    assert selects == []


def test_a_collected_key_column_still_hands_the_batch_a_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A referenced parent column feeds a key collector, which reads Python values."""
    selects = _count(monkeypatch, "select")
    parent = fx.table("parent", _ROWS, [{"name": "k", "type": "faker", "faker_type": "city"}])
    child = fx.table(
        "child",
        10,
        [
            {
                "name": "pk",
                "type": "reference",
                "reference_table": "parent",
                "reference_column": "k",
            }
        ],
    )
    run_resident(fx.config([parent, child]), batch_rows=40_000)
    assert sum(selects) == _ROWS


def test_the_declared_width_bound_is_enforced_on_the_arrow_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pool value over the `city` cap (256 bytes) is caught when the batch is assembled, and
    the message names the column, never the value."""
    from decoy_engine.generation._budget_ledger import GenerationBudgetExceeded
    from decoy_engine.generation._streamed import run_generation
    from tests.parity._fr0_support import prepared_config

    real = _faker_pool.build_pool_values

    def wide(*args: Any, **kwargs: Any) -> Any:
        values, exact, custom = real(*args, **kwargs)
        return ["w" * 400, *values[1:]], exact, custom

    monkeypatch.setattr(_faker_pool, "build_pool_values", wide)
    selects = _count(monkeypatch, "select")
    config = prepared_config(faker_config("city", _ROWS))
    with pytest.raises(GenerationBudgetExceeded) as err:
        run_generation(config, budget_bytes=1 << 30, batch_rows=40_000)
    assert err.value.code == "value_exceeds_declared_bound"
    assert "wwww" not in str(err.value)
    assert selects == []
