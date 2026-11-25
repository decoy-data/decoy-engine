"""GEN-STREAM-ALL A14: the pool's resident bytes come from one helper, both forms counted.

The live ledger and the preflight both call `faker_pool_resident_bytes`. The helper must cover
the retained numpy object array, the retained Arrow array and the peak while the list becomes
Arrow, so the tests below hold it against a floor written out from those three parts.
"""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine.generation import _column_streams, _faker_pool, _streamed
from decoy_engine.generation._bounds import STR_OBJECT_OVERHEAD_BYTES, faker_pool_resident_bytes
from decoy_engine.generation._budget_ledger import (
    GenerationBudgetExceeded,
    GenerationBudgetLedger,
)
from tests.parity._fr0_support import prepared_config
from tests.unit.generation.stream._support import faker_config

_ROWS = 120_000
_POOL = 10_000
_PAYLOAD = 256  # the `city` cap in FAKER_VALUE_CAPS


def _floor(pool_size: int, payload: int) -> int:
    """The three parts, unslacked: object form, Arrow data plus 4-byte offsets, conversion list."""
    object_form = pool_size * (STR_OBJECT_OVERHEAD_BYTES + payload)
    arrow_form = pool_size * (payload + 4)
    conversion = pool_size * 8
    return object_form + arrow_form + conversion


def test_the_helper_covers_both_retained_forms_and_the_conversion_peak() -> None:
    got = faker_pool_resident_bytes(_POOL, _PAYLOAD)
    # With the 1.5 slack, leaving out either retained form lands below this floor.
    assert got >= _floor(_POOL, _PAYLOAD)


def test_the_helper_grows_with_pool_size_and_payload() -> None:
    small = faker_pool_resident_bytes(9, _PAYLOAD)
    assert small < faker_pool_resident_bytes(_POOL, _PAYLOAD)
    assert faker_pool_resident_bytes(_POOL, 8) < faker_pool_resident_bytes(_POOL, _PAYLOAD)


def _city_run(ledger: GenerationBudgetLedger, **kwargs: Any) -> Any:
    config = prepared_config(faker_config("city", _ROWS))
    return _streamed.run_generation(config, ledger=ledger, batch_rows=4096, **kwargs)


def test_live_reservation_is_the_helper_figure_and_preflight_calls_the_same_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, list[tuple[int, int]]] = {"preflight": [], "live": []}
    real = faker_pool_resident_bytes

    def spy(where: str) -> Any:
        def call(pool_size: int, payload: int) -> int:
            seen[where].append((pool_size, payload))
            return real(pool_size, payload)

        return call

    monkeypatch.setattr(_streamed, "faker_pool_resident_bytes", spy("preflight"))
    monkeypatch.setattr(_column_streams, "faker_pool_resident_bytes", spy("live"))
    ledger = GenerationBudgetLedger(1 << 40)
    _city_run(ledger)
    expected = real(_POOL, _PAYLOAD)
    assert seen["preflight"] == [(_POOL, _PAYLOAD)]
    assert seen["live"] == [(_POOL, _PAYLOAD)]
    recorded = [n for stage, n in ledger.events if stage.startswith("faker_pool_build")]
    assert recorded == [expected]


def test_a_ceiling_of_exactly_the_reservations_completes_and_one_byte_less_refuses_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The preflight fit band is not under test here; the live ledger is.
    monkeypatch.setattr(_streamed, "_fits", lambda ledger, need: True)
    probe = GenerationBudgetLedger(1 << 40)  # bounded, so payload bounds (and widths) are in play
    _city_run(probe)
    exact = probe.peak_bytes
    assert _city_run(GenerationBudgetLedger(exact)).mode == "resident"

    builds: list[int] = []
    real_build = _faker_pool.build_pool_values

    def counting(*args: Any, **kwargs: Any) -> Any:
        builds.append(1)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(_faker_pool, "build_pool_values", counting)
    with pytest.raises(GenerationBudgetExceeded):
        _city_run(GenerationBudgetLedger(exact - 1))
    assert builds == []
