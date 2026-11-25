"""Hostile ciphertext and oversized cells under an fpe checksum scheme.

Both fail closed with a value-free `FpeChecksumError`, and an oversized cell costs memory
proportional to the scheme's ceiling, not to the cell's length.
"""

from __future__ import annotations

import tracemalloc

import pytest

from decoy_engine.errors import FpeChecksumError
from decoy_engine.transforms.fpe import fpe_decrypt_value, fpe_encrypt_value

_KEY = bytes(range(32))
_TWEAK = b"t"
_ALNUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _text(exc: BaseException) -> str:
    return f"{exc} {exc!r} {exc.args}"


@pytest.mark.parametrize(
    ("scheme", "ciphertext"),
    [("npi", "Z234567893"), ("isbn13", "ZZZ4567890123"), ("isbn13", "97Z1234567890")],
)
def test_nondigit_prefix_raises_a_value_free_checksum_error(scheme: str, ciphertext: str) -> None:
    with pytest.raises(FpeChecksumError) as info:
        fpe_decrypt_value(ciphertext, _KEY, _ALNUM, _TWEAK, True, False, scheme)
    assert "Z" not in _text(info.value)


@pytest.mark.parametrize("scheme", ["npi", "isbn13", "ean13", "gtin", "vin"])
def test_an_oversized_cell_is_refused_without_a_length_sized_copy(scheme: str) -> None:
    cell = "1" * 300_000
    tracemalloc.start()
    try:
        with pytest.raises(FpeChecksumError):
            fpe_encrypt_value(cell, _KEY, _ALNUM, _TWEAK, True, False, scheme)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 200_000, peak
