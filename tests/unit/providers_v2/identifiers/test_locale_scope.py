"""An identifier's locale declaration and its gate are one fact.

For each identifier in the live registry and each of `en_US` and `fr_FR`, `generate_random`
returns a value exactly when the locale is declared, and refuses with `UNSUPPORTED_LOCALE`
otherwise. Declared scope: SSN, EIN, NPI and NDC `en_US` only; CUSIP `en_US` and `en_CA`; IBAN,
PAN, ICD-10 and MRN every engine locale.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest
from decoy_engine.providers_v2.identifiers._locale import ENGINE_LOCALES, require_locale
from faker.config import AVAILABLE_LOCALES

from decoy_engine import reasons
from decoy_engine.providers_v2 import ProviderError, get_default_registry

MODULES = {
    "synthetic_ssn": "_ssn",
    "synthetic_ein": "_ein",
    "synthetic_npi": "_npi",
    "synthetic_ndc": "_ndc",
    "synthetic_cusip": "_cusip",
    "synthetic_iban": "_iban",
    "synthetic_pan": "_pan",
    "synthetic_icd10": "_icd10",
    "synthetic_mrn": "_mrn",
}
US_ONLY = ("en_US",)
EXPECTED: dict[str, tuple[str, ...]] = {
    "synthetic_ssn": US_ONLY,
    "synthetic_ein": US_ONLY,
    "synthetic_npi": US_ONLY,
    "synthetic_ndc": US_ONLY,
    "synthetic_cusip": ("en_CA", "en_US"),
    "synthetic_iban": ENGINE_LOCALES,
    "synthetic_pan": ENGINE_LOCALES,
    "synthetic_icd10": ENGINE_LOCALES,
    "synthetic_mrn": ENGINE_LOCALES,
}
LOCALES = ("en_US", "fr_FR")


def _generator(name: str) -> Callable[..., str]:
    module = importlib.import_module(f"decoy_engine.providers_v2.identifiers.{MODULES[name]}")
    fn: Callable[..., str] = module.generate_random
    return fn


def _declared(name: str) -> tuple[str, ...]:
    return get_default_registry().get_capabilities(name).supported_locales


def test_the_table_names_every_decoy_native_identifier() -> None:
    registry = get_default_registry()
    native = {
        p
        for p in registry.known_providers()
        if registry.get_capabilities(p).backend_type == "decoy_native"
    }
    assert native == set(MODULES) == set(EXPECTED)


def test_engine_locales_are_fakers_available_locales_sorted() -> None:
    assert tuple(sorted(AVAILABLE_LOCALES)) == ENGINE_LOCALES
    assert "en_US" in ENGINE_LOCALES and "fr_FR" in ENGINE_LOCALES


@pytest.mark.parametrize("name", sorted(MODULES))
def test_the_declared_scope_is_the_owners_choice(name: str) -> None:
    assert _declared(name) == EXPECTED[name]


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("name", sorted(MODULES))
def test_generate_random_returns_a_value_exactly_when_the_locale_is_declared(
    name: str, locale: str
) -> None:
    generate = _generator(name)
    if locale in _declared(name):
        assert isinstance(generate(np.random.default_rng(7), locale), str)
        return
    with pytest.raises(ProviderError) as info:
        generate(np.random.default_rng(7), locale)
    assert info.value.code == reasons.provider.UNSUPPORTED_LOCALE


@pytest.mark.parametrize("name", sorted(MODULES))
def test_a_declared_locale_has_no_effect_on_the_value(name: str) -> None:
    generate = _generator(name)
    base = generate(np.random.default_rng(7), "en_US")
    for locale in _declared(name):
        assert generate(np.random.default_rng(7), locale) == base


def test_a_locale_outside_the_engine_set_is_refused_by_the_locale_free_identifiers() -> None:
    for name in ("synthetic_iban", "synthetic_pan", "synthetic_icd10", "synthetic_mrn"):
        with pytest.raises(ProviderError) as info:
            _generator(name)(np.random.default_rng(7), "zz_ZZ")
        assert info.value.code == reasons.provider.UNSUPPORTED_LOCALE


def test_require_locale_text_names_the_identifier_not_the_locale() -> None:
    canary: Any = "zz_CANARY"
    with pytest.raises(ProviderError) as info:
        require_locale("NPI", canary, US_ONLY)
    assert info.value.code == reasons.provider.UNSUPPORTED_LOCALE
    assert "NPI" in str(info.value) and "CANARY" not in str(info.value)
    require_locale("NPI", "en_US", US_ONLY)
