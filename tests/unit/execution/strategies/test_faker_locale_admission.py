"""GEN-NONFAKER-DRAWS S2: locale admission is decided by the live adapter, on every route.

A Faker callback registered under a stock provider name replaces that provider's string draw. The
out-of-core route reads its schema from the stock binding, so it may run a column only when the
adapter dispatch will use cannot reach such a callback for the column's locale. That adapter
resolves the locale itself (given, empty or omitted), so the matrix crosses each kind of live
binding with each kind of locale and asserts both routes:

- admitted: the forced out-of-core run draws no callback and the column is Arrow `string`;
- declined: the forced run is refused with the typed reason and an auto run equals the full-frame
  run.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import ConfigError
from decoy_engine.providers_v2 import (
    ProviderRegistry,
    faker_callback_reachable,
    get_default_registry,
    register_faker_provider_v2,
)
from decoy_engine.providers_v2._faker_adapter import (
    FakerAdapter,
    _unregister_faker_provider_v2,
)
from tests.unit.execution.strategies.test_faker_computed_routes import _column
from tests.unit.execution.strategies.test_faker_computed_variant import OOC_POOL, _Routes

# The stock `person_email` binds to Mimesis only where the optional dependency is installed, so the
# cases that need a Mimesis binding skip without it; the Faker-backed cases run everywhere.
needs_mimesis = pytest.mark.skipif(
    importlib.util.find_spec("mimesis") is None, reason="needs the optional mimesis extra"
)

_DEFAULT = get_default_registry()
# Mimesis covers de_DE (and en_US, the stock default); Faker covers pl_PL and nl_NL, Mimesis does not.
IN_SET = "de_DE"
OUT_OF_SET = "pl_PL"
LOCALES: dict[str, str | None] = {
    "given_in_set": IN_SET,
    "given_outside": OUT_OF_SET,
    "empty": "",
    "omitted": None,
}


def _override(provider: str, adapter: Any) -> ProviderRegistry:
    return _DEFAULT.override(provider, adapter, _DEFAULT.get_capabilities(provider))


def _mimesis_nl(provider: str) -> ProviderRegistry:
    """A Mimesis binding whose default locale is outside the Mimesis set, with a Faker fallback."""
    from decoy_engine.providers_v2.mimesis import MimesisAdapter

    return _override(
        provider, MimesisAdapter(locale="nl_NL", fallback=_DEFAULT.get_adapter("lorem_text"))
    )


def _mimesis_nl_pooled_fallback(provider: str) -> ProviderRegistry:
    """As `_mimesis_nl`, but the Faker fallback sits behind a `PoolAdapter`, which forwards batches."""
    from decoy_engine.generation.pool import PoolAdapter, PoolBuilder, PoolCache
    from decoy_engine.providers_v2.mimesis import MimesisAdapter

    pooled = PoolAdapter(
        wrapped=FakerAdapter(), builder=PoolBuilder(_DEFAULT), cache=PoolCache(max_bytes=10_000_000)
    )
    return _override(provider, MimesisAdapter(locale="nl_NL", fallback=pooled))


# case -> (provider, registry factory, locale kinds the live adapter serves without a callback)
CASES: dict[str, tuple[str, Any, set[str]]] = {
    "stock_mimesis": ("person_email", lambda p: None, {"given_in_set", "empty", "omitted"}),
    "mimesis_nl_default_faker_fallback": ("person_email", _mimesis_nl, {"given_in_set"}),
    "mimesis_nl_default_pooled_faker_fallback": (
        "person_email",
        _mimesis_nl_pooled_fallback,
        {"given_in_set"},
    ),
    "faker_backed_override": ("person_email", lambda p: _override(p, FakerAdapter()), set()),
    "stock_faker_backed": ("address_city", lambda p: None, set()),
}
CASE_PARAMS = [
    pytest.param(name, marks=needs_mimesis if "mimesis" in name else ()) for name in CASES
]


class _Calls:
    def __init__(self) -> None:
        self.count = 0


@pytest.fixture
def callback() -> Iterator[tuple[_Calls, list[str]]]:
    """A callback registered under both stock names that returns an integer, not a string."""
    calls = _Calls()
    names = ["person_email", "address_city"]

    def draw(fake: Any) -> int:
        calls.count += 1
        return 7

    for name in names:
        register_faker_provider_v2(name, draw)
    try:
        yield calls, names
    finally:
        for name in names:
            _unregister_faker_provider_v2(name)


def _setup(case: str, kind: str) -> tuple[dict[str, Any], dict[str, Any], bool]:
    provider, make_registry, served = CASES[case]
    config: dict[str, Any] = {"pool_size": 50}
    if LOCALES[kind] is not None:
        config["locale"] = LOCALES[kind]
    registry = make_registry(provider)
    kwargs = {} if registry is None else {"registry": registry}
    return _column(provider, config, deterministic=True), kwargs, kind in served


@pytest.mark.parametrize("kind", LOCALES)
@pytest.mark.parametrize("case", CASE_PARAMS)
class TestLocaleAdmissionMatrix:
    def test_the_forced_out_of_core_run(
        self, case: str, kind: str, callback, tmp_path: Path
    ) -> None:
        calls, _ = callback
        column, kwargs, admitted = _setup(case, kind)
        if not admitted:
            with pytest.raises(ConfigError, match=OOC_POOL):
                _Routes().run(tmp_path, column, execution_mode="out_of_core", **kwargs)
            return
        result = _Routes().run(tmp_path, column, execution_mode="out_of_core", **kwargs)
        assert calls.count == 0
        assert result.outputs["t"].schema.field("f").type == pa.string()

    def test_the_auto_run(self, case: str, kind: str, callback, tmp_path: Path) -> None:
        calls, _ = callback
        column, kwargs, admitted = _setup(case, kind)
        auto = _Routes().run(tmp_path, column, **kwargs)
        if admitted:
            assert calls.count == 0
            assert auto.outputs["t"].schema.field("f").type == pa.string()
            return
        whole = _Routes().run(
            tmp_path, column, execution_mode="full_frame", auto_chunk=False, **kwargs
        )
        assert auto.outputs["t"].equals(whole.outputs["t"])


class TestOneResolverForAdmissionAndDispatch:
    """The reachability answer is the adapter's own locale resolution, so it cannot drift from it."""

    @needs_mimesis
    def test_it_agrees_with_what_dispatch_draws(self, callback) -> None:
        from decoy_engine.providers_v2 import ProviderSpec

        calls, _ = callback
        for case in ("stock_mimesis", "mimesis_nl_default_faker_fallback"):
            provider, make_registry, served = CASES[case]
            registry = make_registry(provider) or _DEFAULT
            adapter = registry.get_adapter(provider)
            for kind, locale in LOCALES.items():
                calls.count = 0
                adapter.generate(
                    provider,
                    spec=ProviderSpec(
                        locale=locale, deterministic=False, namespace=None, seed=None
                    ),
                )
                assert faker_callback_reachable(provider, adapter, locale) is (calls.count > 0)
                assert (calls.count == 0) is (kind in served), (case, kind)

    def test_a_non_string_locale_is_reachable_without_drawing(self, callback) -> None:
        adapter = _DEFAULT.get_adapter("person_email")
        assert faker_callback_reachable("person_email", adapter, 5) is True
        assert faker_callback_reachable("person_email", adapter, ["en_US"]) is True

    def test_no_registered_callback_means_nothing_is_reachable(self) -> None:
        adapter = _DEFAULT.get_adapter("address_city")
        assert faker_callback_reachable("address_city", adapter, None) is False

    @needs_mimesis
    def test_a_mimesis_adapter_with_no_fallback_reaches_no_callback(self, callback) -> None:
        from decoy_engine.providers_v2.mimesis import MimesisAdapter

        adapter = MimesisAdapter(locale="nl_NL")
        assert faker_callback_reachable("person_email", adapter, None) is False

    def test_a_wrapper_that_does_not_say_where_it_draws_is_reachable(self, callback) -> None:
        """Fail closed: an adapter with no `serving_adapter` may forward to Faker, so it declines."""

        class Opaque:
            backend_type = "stub"

        assert faker_callback_reachable("person_email", Opaque(), None) is True  # type: ignore[arg-type]
        assert faker_callback_reachable("person_email", Opaque(), "de_DE") is True  # type: ignore[arg-type]

    def test_a_pool_wrapper_answers_with_the_adapter_it_wraps(self, callback) -> None:
        from decoy_engine.generation.pool import PoolAdapter, PoolBuilder, PoolCache

        class Quiet:
            """Draws its own locales and never reaches Faker."""

            backend_type = "stub"

            def serving_adapter(self, locale: str | None) -> Any:
                return self

        def pooled(inner: Any) -> Any:
            return PoolAdapter(
                wrapped=inner, builder=PoolBuilder(_DEFAULT), cache=PoolCache(max_bytes=1_000_000)
            )

        assert faker_callback_reachable("person_email", pooled(FakerAdapter()), None) is True
        assert faker_callback_reachable("person_email", pooled(Quiet()), None) is False
