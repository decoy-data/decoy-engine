"""The two named canonical JSON forms: bytes, refusals, and value-free errors."""

from __future__ import annotations

import datetime as dt
import decimal
from typing import Any

import pytest

from decoy_engine import reasons
from decoy_engine._canonical import (
    CanonicalJsonError,
    CanonicalStringError,
    StrictJsonError,
    canonical_json_bytes,
    seed_fingerprint_bytes,
    strict_json_loads,
)
from decoy_engine.errors import DecoyError

FORMS = [canonical_json_bytes, seed_fingerprint_bytes]
SURROGATE = "before\ud800after"


def test_the_digest_form_writes_utf8_and_the_seed_form_escapes_ascii() -> None:
    value = {"b": 1, "a": "é"}
    assert canonical_json_bytes(value) == '{"a":"é","b":1}'.encode()
    assert seed_fingerprint_bytes(value) == b'{"a":"\\u00e9","b":1}'


@pytest.mark.parametrize("form", FORMS)
def test_both_forms_sort_keys_and_drop_whitespace(form: Any) -> None:
    assert form({"z": [1, {"y": None, "x": True}], "a": 1.5}) == (
        b'{"a":1.5,"z":[1,{"x":true,"y":null}]}'
    )


@pytest.mark.parametrize("form", FORMS)
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nan_and_infinity_are_refused(form: Any, bad: float) -> None:
    with pytest.raises(CanonicalJsonError):
        form({"x": bad})


@pytest.mark.parametrize("form", FORMS)
def test_a_set_is_refused_and_only_its_type_is_named(form: Any) -> None:
    with pytest.raises(CanonicalJsonError) as caught:
        form({"x": {"secret-member"}})
    assert "set" in str(caught.value)
    assert "secret-member" not in str(caught.value)


@pytest.mark.parametrize("form", FORMS)
@pytest.mark.parametrize(
    "value", [b"raw", decimal.Decimal("1.5"), object(), frozenset({1}), complex(1, 2)]
)
def test_other_non_json_types_are_refused(form: Any, value: object) -> None:
    with pytest.raises(CanonicalJsonError):
        form({"x": value})


@pytest.mark.parametrize("form", FORMS)
def test_a_circular_value_is_refused(form: Any) -> None:
    loop: list[Any] = []
    loop.append(loop)
    with pytest.raises(CanonicalJsonError):
        form(loop)


@pytest.mark.parametrize("form", FORMS)
def test_keys_of_mixed_types_are_refused(form: Any) -> None:
    with pytest.raises(CanonicalJsonError):
        form({1: "a", "b": "c"})


def test_a_date_and_an_aware_datetime_become_isoformat() -> None:
    aware = dt.datetime(2024, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc)
    assert canonical_json_bytes({"d": dt.date(2024, 1, 2), "t": aware}) == (
        b'{"d":"2024-01-02","t":"2024-01-02T03:04:05+00:00"}'
    )


def test_a_naive_datetime_is_refused_because_it_would_read_as_host_time() -> None:
    with pytest.raises(CanonicalJsonError):
        canonical_json_bytes({"t": dt.datetime(2024, 1, 2, 3, 4, 5)})


@pytest.mark.parametrize("form", FORMS)
def test_an_unpaired_surrogate_in_a_value_is_refused_before_encoding(form: Any) -> None:
    with pytest.raises(CanonicalJsonError) as caught:
        form({"x": SURROGATE})
    assert caught.value.code == reasons.config.CANONICAL_JSON_INVALID_STRING


@pytest.mark.parametrize("form", FORMS)
def test_an_unpaired_surrogate_in_a_key_is_refused(form: Any) -> None:
    with pytest.raises(CanonicalJsonError) as caught:
        form({SURROGATE: 1})
    assert caught.value.code == reasons.config.CANONICAL_JSON_INVALID_STRING


@pytest.mark.parametrize("form", FORMS)
def test_a_surrogate_nested_in_a_list_is_found(form: Any) -> None:
    with pytest.raises(CanonicalJsonError):
        form({"a": [{"b": ("ok", SURROGATE)}]})


@pytest.mark.parametrize("form", FORMS)
def test_a_literal_backslash_u_text_is_not_a_surrogate(form: Any) -> None:
    assert form({"x": "\\ud800"}) == b'{"x":"\\\\ud800"}'


@pytest.mark.parametrize("form", FORMS)
def test_a_paired_surrogate_character_is_a_scalar_value(form: Any) -> None:
    assert form({"x": "\U0001f600"}).startswith(b'{"x":"')


@pytest.mark.parametrize("form", FORMS)
@pytest.mark.parametrize(
    "bad",
    [
        {"x": {"set-secret-xyz"}},
        {"x": SURROGATE},
        {SURROGATE: 1},
        {"x": float("nan")},
        {"x": dt.datetime(2024, 1, 2)},
        {"secret-key-xyz": object()},
    ],
)
def test_errors_carry_no_context_and_no_input_text(form: Any, bad: Any) -> None:
    with pytest.raises(CanonicalJsonError) as caught:
        form(bad)
    error = caught.value
    assert error.__cause__ is None and error.__context__ is None
    text = f"{error} {error!r}"
    for needle in ("secret", "before", "after", "\\ud800", "ud800", "codec", "2024"):
        assert needle not in text


def test_the_error_is_a_value_error_and_a_decoy_error_with_a_registered_code() -> None:
    error = CanonicalJsonError("x")
    assert isinstance(error, ValueError) and isinstance(error, DecoyError)
    assert error.code == reasons.config.CONFIG_VALUE_NOT_JSON
    assert CanonicalStringError().code == reasons.config.CANONICAL_JSON_INVALID_STRING
    assert isinstance(CanonicalStringError(), CanonicalJsonError)


def test_the_surrogate_message_is_the_fixed_registered_text() -> None:
    with pytest.raises(CanonicalJsonError) as caught:
        canonical_json_bytes(SURROGATE)
    assert str(caught.value) == "Canonical JSON strings must contain only Unicode scalar values."


@pytest.mark.parametrize(
    "error", [CanonicalJsonError("a value of type set", "set"), CanonicalStringError()]
)
def test_the_errors_survive_a_pickle_round_trip(error: CanonicalJsonError) -> None:
    import pickle

    again = pickle.loads(pickle.dumps(error))  # noqa: S301 - bytes this test just produced
    assert type(again) is type(error)
    assert str(again) == str(error) and again.code == error.code


@pytest.mark.parametrize(
    ("text", "token"),
    [
        ('{"a": 1, "a": 2}', "duplicate_key"),
        ('{"a": NaN}', "non_finite"),
        ("[Infinity]", "non_finite"),
        ("[-Infinity]", "non_finite"),
        ("[" + "9" * 21 + "]", "out_of_range"),
        ("[-" + "9" * 21 + "]", "out_of_range"),
        ("{not json", "not_json"),
        ("", "not_json"),
    ],
)
def test_strict_json_loads_refuses_each_defect_with_a_closed_token(text: str, token: str) -> None:
    for data in (text, text.encode()):
        with pytest.raises(StrictJsonError) as caught:
            strict_json_loads(data)
        assert caught.value.token == token
        assert str(caught.value) == token
        assert caught.value.__context__ is None


def test_strict_json_loads_refuses_bad_utf8_without_input_text() -> None:
    with pytest.raises(StrictJsonError) as caught:
        strict_json_loads(b"\xff\xfe")
    assert caught.value.token == "not_json"
    assert caught.value.__context__ is None


def test_strict_json_loads_parses_valid_json_and_honours_the_digit_bound() -> None:
    assert strict_json_loads(b'{"a": [1, -2, 1.5, "x", null, true]}') == {
        "a": [1, -2, 1.5, "x", None, True]
    }
    assert strict_json_loads("[" + "9" * 20 + "]") == [int("9" * 20)]
    with pytest.raises(StrictJsonError):
        strict_json_loads("[123]", max_int_digits=2)


def test_strict_json_loads_without_a_digit_limit_keeps_long_integers() -> None:
    assert strict_json_loads("[" + "9" * 40 + "]", max_int_digits=None) == [int("9" * 40)]


def test_strict_json_loads_turns_deep_nesting_into_not_json() -> None:
    with pytest.raises(StrictJsonError) as caught:
        strict_json_loads("[" * 100_000 + "]" * 100_000)
    assert caught.value.token == "not_json"
