"""AT-E13: the two strict-reader options are opt-in; every default reads as it did."""

from __future__ import annotations

import pytest

from decoy_engine._canonical import JsonNumber, StrictJsonError, strict_json_loads, strict_json_read


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


def test_forbid_lone_surrogate_refuses_an_escaped_one_and_defaults_off() -> None:
    text = '{"a": "\\ud800"}'
    assert strict_json_loads(text) == {"a": "\ud800"}
    with pytest.raises(StrictJsonError) as caught:
        strict_json_loads(text, forbid_lone_surrogate=True)
    assert caught.value.token == "invalid_unicode"
    assert strict_json_loads('{"a": "\\ud83d\\ude00"}', forbid_lone_surrogate=True) == {"a": "😀"}


# A literal that overflows to infinity (`1e999`) skips `parse_constant`; the float hook refuses it.
# These pin each mix of that refusal with the profile options, which share the one float hook.


def _token(data: bytes, **kwargs: object) -> str:
    with pytest.raises(StrictJsonError) as caught:
        strict_json_read(data, **kwargs)  # type: ignore[arg-type]
    assert caught.value.__context__ is None
    return caught.value.token


@pytest.mark.parametrize("data", [b"[1e999]", b'{"a":-1E999}'])
def test_overflow_is_refused_by_default_and_with_each_integer_option(data: bytes) -> None:
    assert _token(data) == "non_finite"
    assert _token(data, non_finite="refuse") == "non_finite"
    # forbid_negative_zero turns on the integer hook; the float hook must still refuse overflow.
    assert _token(data, forbid_negative_zero=True) == "non_finite"
    assert _token(data, forbid_lone_surrogate=True) == "non_finite"


def test_overflow_under_forbid_float_names_float_first() -> None:
    assert _token(b"[1e999]", forbid_float=True) == "float"
    assert _token(b"[1e999]", forbid_float=True, non_finite="keep") == "float"
    assert _token(b"[1e999]", forbid_float=True, keep_lexemes=True) == "float"


def test_an_earlier_defect_still_wins_over_overflow() -> None:
    assert _token(b"[-0,1e999]", forbid_negative_zero=True) == "negative_zero"
    assert _token(b'[{"a":1,"a":2},1e999]') == "duplicate_key"


def test_overflow_is_kept_when_non_finite_is_kept() -> None:
    assert strict_json_read(b"[1e999]", non_finite="keep") == [float("inf")]
    assert strict_json_read(b"[1e999]", non_finite="keep", forbid_negative_zero=True) == [
        float("inf")
    ]


def test_a_lexeme_read_keeps_the_overflow_literal() -> None:
    kept = strict_json_read(b"[1e999]", keep_lexemes=True)
    assert kept == [JsonNumber(float("inf"), "1e999")]
    kept = strict_json_read(b"[1e999]", keep_lexemes=True, forbid_negative_zero=True)
    assert kept == [JsonNumber(float("inf"), "1e999")]


def test_a_large_finite_float_passes_every_option_but_forbid_float() -> None:
    for kwargs in ({}, {"forbid_negative_zero": True}, {"forbid_lone_surrogate": True}):
        assert strict_json_read(b"[1e308]", **kwargs) == [1e308]  # type: ignore[arg-type]
