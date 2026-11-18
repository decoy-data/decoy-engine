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
from faker.config import AVAILABLE_LOCALES

from decoy_engine import reasons
from decoy_engine.providers_v2 import ProviderError, get_default_registry
from decoy_engine.providers_v2.identifiers._locale import ENGINE_LOCALES, require_locale

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


def _probe(name: str) -> str:
    """One locale the identifier does not declare."""
    return "xx_XX" if _declared(name) == ENGINE_LOCALES else "fr_FR"


@pytest.mark.parametrize("name", sorted(MODULES))
def test_every_declared_locale_gives_the_en_us_value_and_the_probe_refuses(name: str) -> None:
    generate = _generator(name)
    base = generate(np.random.default_rng(7), "en_US")
    for locale in _declared(name):
        assert generate(np.random.default_rng(7), locale) == base, locale
    with pytest.raises(ProviderError) as info:
        generate(np.random.default_rng(7), _probe(name))
    assert info.value.code == reasons.provider.UNSUPPORTED_LOCALE


def test_the_probe_is_outside_the_engine_set() -> None:
    assert "xx_XX" not in ENGINE_LOCALES and "fr_FR" in ENGINE_LOCALES


def test_cusip_takes_en_ca_and_refuses_fr_fr() -> None:
    generate = _generator("synthetic_cusip")
    assert "en_CA" in _declared("synthetic_cusip")
    assert generate(np.random.default_rng(7), "en_CA") == generate(
        np.random.default_rng(7), "en_US"
    )
    with pytest.raises(ProviderError):
        generate(np.random.default_rng(7), "fr_FR")


def test_require_locale_text_names_the_identifier_not_the_locale() -> None:
    canary: Any = "zz_CANARY"
    with pytest.raises(ProviderError) as info:
        require_locale("NPI", canary, US_ONLY)
    assert info.value.code == reasons.provider.UNSUPPORTED_LOCALE
    assert "NPI" in str(info.value) and "CANARY" not in str(info.value)
    require_locale("NPI", "en_US", US_ONLY)
