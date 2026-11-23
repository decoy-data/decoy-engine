"""Committed digests of the Faker and Mimesis backed `type: provider` columns.

These values are Faker output, so a Faker bump moves them. They live in the Faker output lock
lane (marker `faker_output_lock`, the `faker-output-lock` CI job) and not in the default loop,
next to `scripts/faker-determinism/output_lock.json`. After a reviewed Faker bump, run the marked
cell with `-s` and `PRINT_FAKER_PROVIDER_DIGESTS=1`: it prints the new table to paste over
`COMMITTED`. The keyed identifier digests stay in `tests/unit/generation/kinds/test_provider.py`.
"""

from __future__ import annotations

import json
import os

import pytest

from tests.unit.generation.kinds.test_provider import (
    NATIVE_SCALARS,
    ROWS,
    SCALARS,
    _digests,
    all_scalars,
    generate,
)
from tests.unit.generation.kinds.test_provider_group import (
    FAKER_FREE,
    composite_config,
)
from tests.unit.generation.kinds.test_provider_group import digests as composite_digests

FAKER_SCALARS = [p for p in SCALARS if p not in NATIVE_SCALARS]

COMMITTED = {
    "address_city": "f39e66d21afda8070bb7105d64471db1d923c0ec4e8207405848b7eb91322398",
    "address_full": "c6a2f9c4af1a1c198aac13f9c328de08be94e40b70459314c23b96bfcb5c7dfe",
    "address_state": "36c91c19e90e5b78271d672ddff2dca6ed85a4632d87c5966f979e8d474f4870",
    "address_street": "d76567ac5081a8623a580660a3c684176872c96741c37e2719f11aec60a096e8",
    "address_zip": "9a188d9ab2c5fb710251c517d29df6ffba0df7c9e639f42dd6df018f258a18ae",
    "lorem_text": "ae983916580f66280be6f0b45cc68c164fba80fdeed74c4ab5eb0dfb15c034af",
    "person_dob": "3ebd3655d5e82023f397d8e449c84056c77a99e05d7d9cdcd0f17c2992757164",
    "person_email": "b8ce659f768470b1a74384541b73e8a58273008d8265d17f40572c234abb6d01",
    "person_first_name": "69d2d4da0cf6ea7533747d3c5c8e27d4d7e3d2d0fbef24e8b550dc3876d5fd08",
    "person_first_name_female": "0366c47f15b7c0df3f2d67b03e89397b86cee7106a2aa499c7dbcd379c46e1bd",
    "person_first_name_male": "c38a668a147e8ce17a69d669ec1908d1e40efc8a15994d6de6b4b7b80f881e24",
    "person_full_name": "f89289c8f88a8583300e5f248d24aaa0112b1be9473a63046aad3c43843a71fc",
    "person_last_name": "74787ccf8bd8f72f4c8b958674ec60233ad90739e48507b7ce6bda9ab55a08dc",
    "person_name": "cf96f66a478a733f56446b0b77af403d93b61fbbed87b06be869b8974eac2b65",
    "person_phone": "79eca1d04fc3b020de0272770802149146d259c1d8fdc669de5c767526ddb243",
    "random_choice": "2cc0b64bf5c360c10157d001c53b907d26c3ea0de064c6c706448fe0fdb30e33",
    "random_int_range": "7421e7798e9f75f60e5d3a97c973f00e5c62c18a39d46e6d719d1eee76d80437",
    "synthetic_account_number": "12433074b42e5629d2b5e7e9111958a55f89d157495faac63e57aee64c12c586",
    "synthetic_member_id": "8e80eb51c4b206e86da0086646de7cca3c6e6ae5cbf99fcee9710d803ae9c46d",
    "synthetic_plan_id": "a07bd635a9e83da2a756af3509c5dfe844e9a2bf85ea9cce8896c27a32f947e5",
    "uuid": "784be5f5d30fb6f1f2e7edced54629d4d63b17ee16b4675963801d690552f823",
}


def test_the_table_names_exactly_the_faker_backed_providers() -> None:
    """Structural only (no Faker output), so the default loop still collects this module."""
    assert sorted(COMMITTED) == FAKER_SCALARS


@pytest.mark.faker_output_lock
def test_every_faker_backed_provider_matches_its_committed_digest() -> None:
    got = _digests(generate(all_scalars(ROWS))["t"])
    got = {p: got[p] for p in FAKER_SCALARS}
    if os.environ.get("PRINT_FAKER_PROVIDER_DIGESTS") == "1":
        print(json.dumps(got, indent=4, sort_keys=True))
    assert got == COMMITTED


# The composite outputs that draw names and dates from Faker (GEN-PROVIDERS E2; E3 adds the optional-slot group `composite_person+`), as one table.
COMPOSITE_COMMITTED = {
    "composite_address.street_address": "ba7b9e29fd9e7224fc49f6eb1c5ae6a4ff8e172000918124a31e01993306b907",
    "composite_name_email.email": "827a6736531cf7dac01fa51db52f15b271a05d098d9fdf13370079e145505816",
    "composite_name_email.first_name": "89cbe8d7b15fe95b3b1d6ec0223a5cf2a11120332414b948eb3ae8d9813685b6",
    "composite_name_email.last_name": "0bd90db873ac06413dedfbcf8ece0f9decda00c65a04a888f02c03b08b27f98d",
    "composite_person+.age": "d84eb8b4e5837573dda3a5c32e56c3b0084b2c5cdc4ffef0f050e00850734039",
    "composite_person+.dob": "a2fbeea037f807abdb95b796402b680a80abf077ed35ae40630058fe316df981",
    "composite_person+.first_name": "aeafe5b0b6343704c498ccdc2de3865e56a3ee51561923c18e9ec5e1fcb38676",
    "composite_person+.sex": "5798cd28c7064ec6d240cbbfb0a597a24ae5e504d8173a772642f21dcb3408eb",
    "composite_person.dob": "3aae31c6f08a0c9efe65fc35f734f4af5a29cdfab7823025f0ee91361026dcdf",
    "composite_person.email": "eff07ec2196477eba9443eacee46e532c5308e7d2bdc05acc1dab6cb9e6fa149",
    "composite_person.first_name": "624d37a958fdec8f84f5c8629634d2a63f7d0ee5a5232266945c44981d46538d",
    "composite_person.last_name": "88272b838916e9991cfed8373be4575ed2c2856860c1e046931a0c0d7ec41c66",
    "composite_provider.provider_name": "39eda716e1758c2bd2158f353a59acc80d2bd3c6d3ea54a11157496ede4574b1",
}


def test_the_composite_table_names_exactly_the_faker_backed_outputs() -> None:
    """Structural only: every composite output is pinned here or in the default loop."""
    full = composite_digests(generate(composite_config(5))["t"])
    assert sorted(COMPOSITE_COMMITTED) == sorted(set(full) - FAKER_FREE)


@pytest.mark.faker_output_lock
def test_every_faker_backed_composite_output_matches_its_committed_digest() -> None:
    got = composite_digests(generate(composite_config())["t"])
    got = {k: v for k, v in got.items() if k not in FAKER_FREE}
    if os.environ.get("PRINT_FAKER_PROVIDER_DIGESTS") == "1":
        print(json.dumps(got, indent=4, sort_keys=True))
    assert got == COMPOSITE_COMMITTED
