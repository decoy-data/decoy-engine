"""Every Faker locale a run opens is charged before the first one opens.

Faker builds a locale's provider tables the first time anything opens it: in-run validation,
admission and bounds probes, a pool build, a per-row stream or a Faker-backed provider column.
These tests spy on `Faker.__init__` and hold every open to the run's one reservation.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pyarrow as pa
import pytest
from faker import Faker

from decoy_engine.generation import _streamed, synthesize
from decoy_engine.generation._budget_ledger import (
    GenerationBudgetExceeded,
    GenerationBudgetLedger,
)
from decoy_engine.generation._column_streams import PerRowFakerStream
from decoy_engine.generation.pool import run_faker_footprint
from decoy_engine.internal.faker_setup import effective_locale, locale_entries
from decoy_engine.plan.checks import _generate_columns
from tests.parity import _f0_fixtures as fx
from tests.parity._fr0_support import prepared_config
from tests.unit.generation.stream._support import faker_config

_MIB = 1024 * 1024
_INIT = "faker_provider_init"


class _DrainSink:
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


def _resolved_names(fake: Faker) -> tuple[str, ...]:
    """The locale each factory under ``fake`` really built, read from Faker's own generator.

    `Faker.locales` keeps the submitted alias (`it`); the generator config holds the name Faker
    resolved it to (`it_IT`), which is the locale whose tables the open allocates."""
    names: list[str] = []
    for factory in fake._factory_map.values():
        if isinstance(factory, Faker):
            names.extend(_resolved_names(factory))
        else:
            names.append(factory._Generator__config["locale"])
    return tuple(names)


class _Trace:
    """The order of reservations and Faker opens in one run, and the locales each open read."""

    def __init__(self) -> None:
        self.order: list[str] = []
        self.opened: list[tuple[str, ...]] = []
        self.reserved: frozenset[str] = frozenset()

    def reset(self) -> None:
        """Forget opens made while building the config, and start the run with cold caches."""
        self.order.clear()
        self.opened.clear()
        _generate_columns._builtin.cache_clear()
        synthesize._THREAD_LOCAL.__dict__.clear()


@pytest.fixture
def trace(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Trace]:
    t = _Trace()
    # Cold caches: the validator's per-locale Fakers and this thread's default Faker.
    _generate_columns._builtin.cache_clear()
    monkeypatch.setattr(synthesize, "_THREAD_LOCAL", type(synthesize._THREAD_LOCAL)())
    real_init = Faker.__init__

    def spy_init(self: Faker, *args: Any, **kwargs: Any) -> None:
        real_init(self, *args, **kwargs)
        t.order.append("open")
        t.opened.append(_resolved_names(self))

    real_reserve = GenerationBudgetLedger.reserve

    def spy_reserve(self: GenerationBudgetLedger, stage: str, n: int) -> Any:
        t.order.append(stage)
        return real_reserve(self, stage, n)

    real_footprint = _streamed.run_faker_footprint

    def spy_footprint(*args: Any, **kwargs: Any) -> tuple[frozenset[str], int]:
        locales, instances = real_footprint(*args, **kwargs)
        t.reserved = locales
        return locales, instances

    monkeypatch.setattr(Faker, "__init__", spy_init)
    monkeypatch.setattr(GenerationBudgetLedger, "reserve", spy_reserve)
    monkeypatch.setattr(_streamed, "run_faker_footprint", spy_footprint)
    yield t
    _generate_columns._builtin.cache_clear()


def _provider_config(rows: int) -> dict[str, Any]:
    col = {"name": "p", "type": "provider", "provider": "person_first_name"}
    return fx.config([fx.table("t", rows, [col])])


# (config, instance default locale): one per route that opens a Faker locale.
_PROBES: dict[str, tuple[dict[str, Any], str | None]] = {
    "per_row_run_default": (faker_config("prefix", 1), "it_IT"),
    "per_row_run_default_alias": (faker_config("prefix", 1), "it"),
    "pooled_run_default_alias": (faker_config("prefix", 50_000), "it"),
    "per_row_explicit": (faker_config("prefix", 1, locale="de_AT"), None),
    "pooled": (faker_config("prefix", 50_000, locale="it_IT"), None),
    "provider_column": (_provider_config(4), None),
}


def _probe(name: str) -> tuple[dict[str, Any], str | None]:
    raw, default = _PROBES[name]
    return prepared_config(raw), default


@pytest.mark.serial
@pytest.mark.parametrize("name", sorted(_PROBES))
def test_every_locale_a_run_opens_is_reserved_before_the_first_open(
    name: str, trace: _Trace
) -> None:
    config, default = _probe(name)
    trace.reset()
    _streamed.run_generation(
        config,
        sink=_DrainSink(),
        ledger=GenerationBudgetLedger(None),
        batch_rows=4096,
        instance_default_locale=default,
    )
    assert trace.opened, "the probe opened no Faker, so it proves nothing"
    opened = {locale for locales in trace.opened for locale in locales}
    assert opened <= trace.reserved
    assert _INIT in trace.order
    assert trace.order.index(_INIT) < trace.order.index("open")


@pytest.mark.serial
def test_a_one_row_job_in_a_heavy_default_locale_is_refused_before_faker_opens(
    trace: _Trace,
) -> None:
    """Codex V1-1: a one-row `it_IT` job used 10.7 MB against 331 bytes in the ledger."""
    config = prepared_config(faker_config("prefix", 1))
    trace.reset()
    ledger = GenerationBudgetLedger(6 * _MIB)
    with pytest.raises(GenerationBudgetExceeded):
        _streamed.run_generation(
            config,
            sink=_DrainSink(),
            ledger=ledger,
            batch_rows=128,
            instance_default_locale="it_IT",
        )
    assert trace.opened == []
    assert ledger.remaining_bytes == 6 * _MIB


@pytest.mark.serial
def test_two_heavy_locales_are_refused_under_a_ceiling_their_cold_import_passes(
    trace: _Trace,
) -> None:
    """Codex V1-2: `de_AT` then `it_IT` peaked at 66 MB cold under a 32 MiB ceiling."""
    config = prepared_config(faker_config("prefix", 50_000))
    config["tables"][0]["generate_columns"][0]["locale"] = ["de_AT", "it_IT"]
    trace.reset()
    ledger = GenerationBudgetLedger(32 * _MIB)
    with pytest.raises(GenerationBudgetExceeded):
        _streamed.run_generation(config, sink=_DrainSink(), ledger=ledger, batch_rows=128)
    assert trace.opened == []


@pytest.mark.parametrize(
    ("column_locale", "default"),
    [
        (None, None),
        (None, "it_IT"),
        ("de-AT", None),
        ("de_AT", "it_IT"),
        ("en-GB", "it_IT"),
    ],
)
def test_a_per_row_stream_opens_the_locales_of_the_shared_rule(
    column_locale: Any, default: str | None
) -> None:
    col: dict[str, Any] = {"name": "v", "type": "faker", "faker_type": "prefix"}
    if column_locale is not None:
        col["locale"] = column_locale
    stream = PerRowFakerStream(col, None, 7, default, None)  # type: ignore[arg-type]
    expected = locale_entries(effective_locale(column_locale, default))
    assert tuple(stream._inst.locales) == expected
    assert set(expected) <= run_faker_footprint(prepared_config(_with(col)), default)[0]


def _with(col: dict[str, Any]) -> dict[str, Any]:
    return fx.config([fx.table("t", 1, [col])])


def test_the_locale_rule_normalizes_and_defaults() -> None:
    assert locale_entries(effective_locale(None, None)) == ("en_US",)
    assert locale_entries(effective_locale("", "it-IT")) == ("it_IT",)
    assert locale_entries(["en-US", None, "en_US", "de_AT"]) == ("en_US", "de_AT")
    assert locale_entries([]) == ("en_US",)


def test_locale_entries_read_a_faker_alias_as_the_locale_faker_opens() -> None:
    assert locale_entries("it") == ("it_IT",)
    assert locale_entries(["de-AT", "it"]) == ("de_AT", "it_IT")


def _list_rows(ambient: int) -> list[Any]:
    Faker.seed(ambient)  # the shared RNG an unseeded factory choice would read
    config = prepared_config(faker_config("prefix", 60, locale=["de_AT", "it_IT"]))
    return synthesize._generate_tables_from_config(config)["t"].column("v").to_pylist()


@pytest.mark.serial
def test_a_validated_locale_list_replays_exactly_whatever_the_ambient_state() -> None:
    first = _list_rows(1)
    assert all(_list_rows(ambient) == first for ambient in range(2, 8))
    assert len(set(first)) > 3, "both locales should contribute, or the replay proves nothing"


@pytest.mark.serial
def test_a_locale_list_pool_build_replays_exactly_whatever_the_ambient_state() -> None:
    from decoy_engine.generation._faker_pool import build_pool_values

    def build(ambient: int) -> list[Any]:
        Faker.seed(ambient)
        return build_pool_values("prefix", ["de_AT", "it_IT"], b"\x01" * 8, 40, {})[0]

    first = build(1)
    assert all(build(ambient) == first for ambient in range(2, 8))
    assert len(set(first)) > 3
