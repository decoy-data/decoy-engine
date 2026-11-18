"""The shared adapter contract kit, run for every harness (AT-E3-2, AT-E3-9).

``aws-sm`` is here so the kit is not tuned to Vault: it must be green on the #663 code.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from decoy_engine.secret_providers import SecretProviderUnavailable
from decoy_engine.secret_providers._types import _CONTEXT_SCALARS, ResolveContext, context_key_parts
from tests.secret_providers.adapters import _contract as kit

KEYS = ("vault", "aws-sm")

CHECKS = [
    kit.check_sr1_failures_are_value_free,
    kit.check_sr2_debug_logging_shows_no_secret,
    kit.check_sr3_values_are_frozen_at_build,
    kit.check_sr4_never_rendered,
    kit.check_sr5_pinned_version,
]


def test_every_harness_is_listed_here() -> None:
    assert sorted(kit.harness_classes()) == sorted(KEYS)


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
def test_the_contract_holds(key, check, tmp_path, monkeypatch) -> None:
    with kit.make_harness(key, tmp_path, monkeypatch) as harness:
        check(harness)


@pytest.mark.parametrize("key", KEYS)
def test_the_context_keys_with_proxies_set(key, tmp_path, monkeypatch) -> None:
    kit.check_sr3_context_has_flat_values(key, tmp_path, monkeypatch)


# -- AT-E3-9: the context stays flat ------------------------------------------------------------


def test_the_context_scalar_contract_is_unchanged() -> None:
    assert list(_CONTEXT_SCALARS) == [str, bool, int, type(None)]


@dataclasses.dataclass(frozen=True, repr=False)
class _DictContext(ResolveContext):
    proxies: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True, repr=False)
class _DatetimeContext(ResolveContext):
    expiry: datetime = datetime(2030, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("context_class", [_DictContext, _DatetimeContext])
def test_a_dict_or_datetime_field_is_refused(context_class) -> None:
    with pytest.raises(SecretProviderUnavailable):
        context_key_parts(context_class(scheme="vault"), "vault")
