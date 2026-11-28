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

FAKER_SCALARS = [p for p in SCALARS if p not in NATIVE_SCALARS]

COMMITTED = {
    "address_city": "f39e66d21afda8070bb7105d64471db1d923c0ec4e8207405848b7eb91322398",
    "address_full": "c6a2f9c4af1a1c198aac13f9c328de08be94e40b70459314c23b96bfcb5c7dfe",
    "address_state": "36c91c19e90e5b78271d672ddff2dca6ed85a4632d87c5966f979e8d474f4870",
    "address_street": "d76567ac5081a8623a580660a3c684176872c96741c37e2719f11aec60a096e8",
    "address_zip": "9a188d9ab2c5fb710251c517d29df6ffba0df7c9e639f42dd6df018f258a18ae",
    "lorem_text": "06b92d3cc90cfae9fa0715a417b243ffe3152c1e51b9a80e87842aebe0ef4318",
    "person_dob": "3ebd3655d5e82023f397d8e449c84056c77a99e05d7d9cdcd0f17c2992757164",
    "person_email": "b8ce659f768470b1a74384541b73e8a58273008d8265d17f40572c234abb6d01",
    "person_first_name": "69d2d4da0cf6ea7533747d3c5c8e27d4d7e3d2d0fbef24e8b550dc3876d5fd08",
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
