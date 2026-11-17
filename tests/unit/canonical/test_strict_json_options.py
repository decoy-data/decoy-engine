"""AT-E13: the two strict-reader options are opt-in; every default reads as it did."""

from __future__ import annotations

import pytest

from decoy_engine._canonical import StrictJsonError, strict_json_loads


@pytest.mark.parametrize(
    ("data", "expected"),
    [(b"-0", 0), (b"1.5", 1.5), (b'{"a":[-0,2.5e1]}', {"a": [0, 25.0]}), (b"[1,2,3]", [1, 2, 3])],
)
def test_defaults_parse_what_they_always_parsed(data: bytes, expected: object) -> None:
    assert strict_json_loads(data) == expected


def test_forbid_negative_zero_records_the_token() -> None:
    with pytest.raises(StrictJsonError) as caught:
        strict_json_loads(b'{"a":-0}', forbid_negative_zero=True)
    assert caught.value.token == "negative_zero"
    assert caught.value.__context__ is None


def test_forbid_negative_zero_leaves_a_plain_zero_and_a_negative_one() -> None:
    assert strict_json_loads(b"[0,-1]", forbid_negative_zero=True) == [0, -1]


def test_forbid_float_records_the_token() -> None:
    with pytest.raises(StrictJsonError) as caught:
        strict_json_loads(b"[1.5]", forbid_float=True)
    assert caught.value.token == "float"
    assert caught.value.__context__ is None
    with pytest.raises(StrictJsonError) as exponent:
        strict_json_loads(b"[1e2]", forbid_float=True)
    assert exponent.value.token == "float"


def test_an_option_does_not_change_the_other_default() -> None:
    assert strict_json_loads(b"-0", forbid_float=True) == 0
    assert strict_json_loads(b"1.5", forbid_negative_zero=True) == 1.5


def test_the_first_recorded_defect_wins() -> None:
    with pytest.raises(StrictJsonError) as caught:
        strict_json_loads(b'[{"a":1,"a":2},1.5]', forbid_float=True)
    assert caught.value.token == "duplicate_key"
