"""GEN-STREAM-ALL A14: the pool reservation is never under the measured resident peak.

The live ledger and the preflight both call `faker_pool_resident_bytes`. Each part of the model
(`faker_pool_resident_parts`) is held against a measure: the Python side by `tracemalloc`, the
Arrow side by a proxy memory pool's high-water mark. Payloads are UTF-8 bytes, so the content
that costs most per byte (one astral char in ASCII text widens every char to 4 bytes) is used.
"""

from __future__ import annotations

import gc
import os
import tracemalloc
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

import decoy_engine
from decoy_engine.generation import _bounds, _column_streams, _faker_pool, _streamed
from decoy_engine.generation._budget_ledger import (
    GenerationBudgetExceeded,
    GenerationBudgetLedger,
)
from decoy_engine.generation.pool._resident import (
    faker_pool_resident_bytes,
    faker_pool_resident_parts,
)
from tests.parity._fr0_support import prepared_config
from tests.unit.generation.stream._support import faker_config

_ROWS = 120_000
_POOL = 10_000
_PAYLOAD = 256  # the `city` cap in FAKER_VALUE_CAPS
_ASTRAL = "\U0001f600"
# Arrays built under a proxy pool must not outlive it.
_KEEP: list[Any] = []


def _values(kind: str, payload: int, n: int) -> list[str]:
    """`n` distinct values of exactly `payload` UTF-8 bytes."""
    out = []
    for i in range(n):
        tag = str(i)
        if kind == "mixed":
            out.append(_ASTRAL + "a" * (payload - 4 - len(tag)) + tag)
        elif kind == "astral":
            out.append(
                _ASTRAL * ((payload - len(tag)) // 4) + "a" * ((payload - len(tag)) % 4) + tag
            )
        else:
            out.append("a" * (payload - len(tag)) + tag)
    return out


@contextmanager
def _measured() -> Iterator[dict[str, int]]:
    """Python peak (tracemalloc) and Arrow peak (proxy pool high-water) of the block."""
    proxy = pa.proxy_memory_pool(pa.default_memory_pool())
    previous = pa.default_memory_pool()
    peaks: dict[str, int] = {}
    gc.collect()
    pa.set_memory_pool(proxy)
    tracemalloc.start()
    try:
        yield peaks
        peaks["python"] = tracemalloc.get_traced_memory()[1]
        peaks["arrow"] = proxy.max_memory()
    finally:
        tracemalloc.stop()
        pa.set_memory_pool(previous)
        _KEEP.append(proxy)


def _open(kind: str, payload: int, n: int, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    monkeypatch.setattr(
        _faker_pool, "build_pool_values", lambda *a, **k: (_values(kind, payload, n), True, False)
    )
    monkeypatch.setattr(_faker_pool, "_pool_seeds", lambda ctx: (b"\x01" * 8, b"\x02" * 8))
    with _measured() as peaks:
        selector = _faker_pool.open_pooled_selector(
            faker_type="city",
            faker_kwargs={},
            gen_ctx=None,  # type: ignore[arg-type]
            effective_locale="en_US",
            pool_size=n,
        )
    assert selector is not None and selector.has_arrow
    _KEEP.append(selector)
    return peaks


@pytest.mark.serial
@pytest.mark.parametrize("n", [_POOL, 8_193])
@pytest.mark.parametrize("payload", [8, 32, 128, _PAYLOAD])
@pytest.mark.parametrize("kind", ["ascii", "astral", "mixed"])
def test_each_part_covers_its_measured_peak(
    kind: str, payload: int, n: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    peaks = _open(kind, payload, n, monkeypatch)
    parts = faker_pool_resident_parts(n, payload)
    assert parts.arrow_peak >= peaks["arrow"]
    assert parts.object_form + parts.lists >= peaks["python"]


@pytest.mark.serial
@pytest.mark.parametrize("payload", [0, 1, 8, 32, 128, _PAYLOAD])
def test_the_charge_sums_every_part(payload: int) -> None:
    """Leaving any part out of the sum is red at every payload size."""
    parts = faker_pool_resident_parts(_POOL, payload)
    assert parts.arrow_peak > 0 and parts.object_form > 0 and parts.lists > 0
    assert faker_pool_resident_bytes(_POOL, payload) >= (
        parts.object_form + parts.arrow_peak + parts.lists
    )


def test_the_helper_grows_with_pool_size_and_payload() -> None:
    small = faker_pool_resident_bytes(9, _PAYLOAD)
    assert small < faker_pool_resident_bytes(_POOL, _PAYLOAD)
    assert faker_pool_resident_bytes(_POOL, 8) < faker_pool_resident_bytes(_POOL, _PAYLOAD)


def _city_run(ledger: GenerationBudgetLedger, **kwargs: Any) -> Any:
    config = prepared_config(faker_config("city", _ROWS))
    return _streamed.run_generation(config, ledger=ledger, batch_rows=4096, **kwargs)


@pytest.mark.serial
@pytest.mark.parametrize(("kind", "cap"), [("mixed", _PAYLOAD), ("astral", _PAYLOAD), ("mixed", 8)])
def test_the_live_reservation_covers_the_measured_build_peak(
    kind: str, cap: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-ASCII pool at the cap: the recorded reservation is at least the measured peak."""
    monkeypatch.setitem(_bounds.FAKER_VALUE_CAPS, "city", cap)
    monkeypatch.setattr(
        _faker_pool, "build_pool_values", lambda *a, **k: (_values(kind, cap, _POOL), True, False)
    )
    real_open = _faker_pool.open_pooled_selector
    peaks: dict[str, int] = {}

    def measured_open(**kwargs: Any) -> Any:
        with _measured() as got:
            selector = real_open(**kwargs)
        peaks.update(got)
        _KEEP.append(selector)
        return selector

    monkeypatch.setattr(_faker_pool, "open_pooled_selector", measured_open)
    ledger = GenerationBudgetLedger(1 << 40)
    _city_run(ledger)
    recorded = [n for stage, n in ledger.events if stage.startswith("faker_pool_build")]
    assert recorded == [faker_pool_resident_bytes(_POOL, cap)]
    assert recorded[0] >= peaks["python"] + peaks["arrow"]


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
    assert seen["preflight"] == [(_POOL, _PAYLOAD)]
    assert seen["live"] == [(_POOL, _PAYLOAD)]
    recorded = [n for stage, n in ledger.events if stage.startswith("faker_pool_build")]
    assert recorded == [real(_POOL, _PAYLOAD)]


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


# Review R1b V1-1: Faker builds its locale providers when the pool opens, and that cost was not
# charged. These run the real build in a fresh worker (no stubbed build, no warm provider cache).
_FRESH_WORKER = """
import os, sys, tracemalloc
import pyarrow as pa
from decoy_engine.generation import _faker_pool
locale, faker_type, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
proxy = pa.proxy_memory_pool(pa.default_memory_pool())
pa.set_memory_pool(proxy)
tracemalloc.start()
selector = _faker_pool.open_pooled_selector(
    faker_type=faker_type, faker_kwargs={}, gen_ctx=None,
    effective_locale=locale, pool_size=n,
)
python_peak = tracemalloc.get_traced_memory()[1]
assert selector is not None
print(python_peak + proxy.max_memory(), flush=True)
# Arrays built under the proxy pool must not outlive it: skip interpreter teardown.
os._exit(0)
"""


def _fresh_worker_peak(locale: str, faker_type: str, n: int) -> int:
    import subprocess
    import sys

    # Seeds come from the gen context, so the worker stubs only that, not the build.
    script = _FRESH_WORKER.replace(
        "selector = _faker_pool",
        "_faker_pool._pool_seeds = lambda ctx: (b'\\x01' * 8, b'\\x02' * 8)\nselector = _faker_pool",
        1,
    )
    out = subprocess.run(  # noqa: S603 -- fixed argv, test-only
        [sys.executable, "-c", script, locale, faker_type, str(n)],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(decoy_engine.__file__).parents[1])},
    )
    assert out.returncode == 0, out.stderr[-2000:]
    return int(out.stdout.strip().splitlines()[-1])


@pytest.mark.serial
@pytest.mark.parametrize("locale", ["it_IT", "de_AT", "el_GR", "en_US"])
def test_the_reservation_covers_a_fresh_worker_build_with_the_real_provider(locale: str) -> None:
    peak = _fresh_worker_peak(locale, "prefix", _POOL)
    payload = _bounds.FAKER_VALUE_CAPS["prefix"]
    assert faker_pool_resident_bytes(_POOL, payload) >= peak


class _DrainSink:
    """A bounded sink that reads every batch and keeps nothing, so the run streams."""

    bounded_write_batches = True

    def write(self, table: str, data: pa.Table) -> None:
        del table, data

    def write_batches(self, table: str, batches: Any, *, schema: pa.Schema) -> None:
        del table, schema
        for _ in batches:
            pass

    def commit(self) -> None:
        return None

    def abort(self) -> None:
        return None


@pytest.mark.serial
def test_a_six_mib_ceiling_refuses_the_it_it_prefix_job_before_it_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reviewer's repro: the pool charged 3.6 MB but the build peaked at 10.7 MB."""
    builds: list[int] = []
    real_open = _faker_pool.open_pooled_selector

    def counting(**kwargs: Any) -> Any:
        builds.append(1)
        return real_open(**kwargs)

    monkeypatch.setattr(_faker_pool, "open_pooled_selector", counting)
    config = prepared_config(faker_config("prefix", _ROWS, locale="it_IT"))
    with pytest.raises(GenerationBudgetExceeded):
        _streamed.run_generation(
            config,
            sink=_DrainSink(),
            ledger=GenerationBudgetLedger(6 * 1024 * 1024),
            batch_rows=128,
        )
    assert builds == []
