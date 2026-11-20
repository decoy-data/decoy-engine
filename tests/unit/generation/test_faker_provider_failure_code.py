"""AT-B1: a Faker provider that fails for a locale surfaces uncoded and unwrapped, as before.

`faker_type: bank` in a locale with no bank list raises from inside Faker. Under Faker 40.23.0 the
exception is `AttributeError`; Faker 40.31.0 and later raise `NotImplementedError`. The engine has
no reason code for it today and this dependency repin adds none, so the contract pinned here is:
the failure escapes `generate_tables` as the provider's own builtin exception, carrying no engine
code. Only the outer class may change with the Faker version.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.parity._f0_fixtures import config, run_generate_tables, table

# cs_CZ has no bank list in Faker 40.23.0 (see scripts/faker-determinism/output_lock.json).
_BANK_LESS_LOCALE = "cs_CZ"
_FAKER_OUTER_CLASSES = (AttributeError, NotImplementedError)


def _generate_bank(locale: str) -> Any:
    col = {"name": "c", "type": "faker", "faker_type": "bank", "locale": locale}
    return run_generate_tables(config([table("t", 3, [col])]))


def test_bank_without_a_bank_list_fails_uncoded_and_unwrapped() -> None:
    with pytest.raises(Exception) as info:
        _generate_bank(_BANK_LESS_LOCALE)
    exc = info.value
    assert type(exc) in _FAKER_OUTER_CLASSES, "the failure was wrapped or recoded"
    assert not hasattr(exc, "code"), "an engine reason code appeared; update the plan and this test"
    assert exc.__cause__ is None


def test_bank_with_a_bank_list_still_generates() -> None:
    assert _generate_bank("en_US")["t"].num_rows == 3
