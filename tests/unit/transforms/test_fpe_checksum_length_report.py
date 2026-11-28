"""An over-length fixed-width value reports "more than <max>", never a collected-length count.

`fpe_encrypt_value` stops collecting in-charset digits one past the scheme's ceiling so a huge
cell is refused in O(limit). The count it hands the length check is therefore a floor, and the
message must not present it as the value's real length.
"""

from __future__ import annotations

import pytest

from decoy_engine.errors import FpeChecksumError
from decoy_engine.transforms.fpe import fpe_encrypt_value

_KEY = b"k" * 32
_TWEAK = b"t"


def _encrypt(value: str, scheme: str) -> None:
    fpe_encrypt_value(value, _KEY, "0123456789", _TWEAK, True, False, scheme)


@pytest.mark.parametrize("extra", [1, 2, 10])
def test_over_length_npi_reports_more_than_the_ceiling(extra: int) -> None:
    digits = "1" * (10 + extra)
    value = "-".join(digits[i : i + 4] for i in range(0, len(digits), 4))
    with pytest.raises(FpeChecksumError) as info:
        _encrypt(value, "npi")
    text = str(info.value)
    assert "more than 10" in text
    for n in range(11, 12 + extra):
        assert f"got {n}" not in text


def test_under_length_npi_still_reports_the_exact_count() -> None:
    with pytest.raises(FpeChecksumError) as info:
        _encrypt("123456789", "npi")
    assert "got 9" in str(info.value)


def test_over_length_gtin_reports_more_than_its_largest_legal_length() -> None:
    with pytest.raises(FpeChecksumError) as info:
        _encrypt("1" * 20, "gtin")
    assert "more than 14" in str(info.value)
