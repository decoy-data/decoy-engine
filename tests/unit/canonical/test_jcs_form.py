"""AT-E2: ``jcs_bytes`` is RFC 8785, and the strict profile refuses with the frozen wire tokens."""

from __future__ import annotations

import json
import pickle

import pytest

from decoy_engine import reasons
from decoy_engine._canonical import ALL_STRICT_JSON_TOKENS, CanonicalJsonError, JcsError, jcs_bytes
from decoy_engine.errors import DecoyError
from decoy_engine.signed_evidence import _strict_json as sj
from decoy_engine.signed_evidence._errors import SignedEvidenceError


def test_the_rfc_8785_sorting_example() -> None:
    # RFC 8785 section 3.2.3: keys sort by UTF-16 code units, strings are written as UTF-8.
    value = json.loads(
        '{"\\u20ac":"Euro Sign","\\r":"Carriage Return","\\ufb33":"Hebrew Letter Dalet With Dagesh",'
        '"1":"One","\\ud83d\\ude00":"Emoji: Grinning Face","\\u0080":"Control",'
        '"\\u00f6":"Latin Small Letter O With Diaeresis"}'
    )
    assert (
        jcs_bytes(value)
        == (
            '{"\\r":"Carriage Return","1":"One","\u0080":"Control",'
            '"ö":"Latin Small Letter O With Diaeresis","€":"Euro Sign",'
            '"\U0001f600":"Emoji: Grinning Face","דּ":"Hebrew Letter Dalet With Dagesh"}'
        ).encode()
    )


def test_the_rfc_8785_structured_example() -> None:
    # RFC 8785 section 3.2.1 (numbers, a string with every escape, and the literals).
    text = (
        '{"numbers":[333333333.33333329,1E30,4.50,2e-3,0.000000000000000000000000001],'
        '"string":"\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022\\u005c\\\\\\"\\/",'
        '"literals":[null,true,false]}'
    )
    assert jcs_bytes(json.loads(text)) == (
        b'{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
        b'"string":"\xe2\x82\xac$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}'
    )


def test_a_lone_surrogate_raises_a_value_free_canonical_error() -> None:
    with pytest.raises(JcsError) as caught:
        jcs_bytes({"k": "a\ud800b"})
    err = caught.value
    assert isinstance(err, CanonicalJsonError) and isinstance(err, DecoyError)
    assert err.__cause__ is None and err.__context__ is None
    assert "ud800" not in str(err) and str(err) != "k"
    assert pickle.loads(pickle.dumps(err)).args == err.args  # noqa: S301 -- own round trip


def test_an_unsupported_type_raises_the_same_error() -> None:
    with pytest.raises(JcsError):
        jcs_bytes({"k": object()})


def _wire(data: bytes) -> str:
    with pytest.raises(SignedEvidenceError) as caught:
        sj.parse_strict(data)
    return caught.value.code


@pytest.mark.parametrize(
    ("data", "token"),
    [
        (b'{"a":{"b":{"c":1,"c":2}}}', "DUPLICATE_MEMBER"),
        (b'{"a":-0}', "INTEGER_OUT_OF_DOMAIN"),
        (b'{"a":[-0]}', "INTEGER_OUT_OF_DOMAIN"),
        (b'{"a":1.5}', "FLOAT_NOT_ALLOWED"),
        (b'{"a":1e2}', "FLOAT_NOT_ALLOWED"),
        (b'{"a":9007199254740992}', "INTEGER_OUT_OF_DOMAIN"),
        (b'{"a":10000000000000000}', "INTEGER_OUT_OF_DOMAIN"),
        (b'{"a":-10000000000000001}', "INTEGER_OUT_OF_DOMAIN"),
        (b'{"a":' + b"9" * 5000 + b"}", "INTEGER_OUT_OF_DOMAIN"),
        (b'{"a":NaN}', "NON_FINITE_NUMBER"),
        (b'{"a":1}x', "NOT_JSON"),
        (b"\xef\xbb\xbf{}", "BOM"),
        (b"[" * 33 + b"]" * 33, "TOO_DEEP"),
        (b" " * (sj.MAX_BYTES + 1), "TOO_LARGE"),
        (b'{"a":"\\ud800"}', "INVALID_UNICODE"),
    ],
)
def test_the_strict_profile_refuses_with_the_frozen_token(data: bytes, token: str) -> None:
    assert _wire(data) == token


def test_the_profile_accepts_the_largest_safe_integers() -> None:
    assert sj.parse_strict(b'{"a":9007199254740991,"b":-9007199254740991,"c":0}') == {
        "a": 9007199254740991,
        "b": -9007199254740991,
        "c": 0,
    }


def test_the_token_map_covers_every_token_the_owner_can_raise() -> None:
    assert set(sj.OWNER_TOKEN_MAP) == set(ALL_STRICT_JSON_TOKENS)
    assert {str(v) for v in sj.OWNER_TOKEN_MAP.values()} <= {
        "duplicate_member",
        "non_finite_number",
        "integer_out_of_domain",
        "float_not_allowed",
        "not_json",
        "too_large",
        "too_deep",
        "invalid_unicode",
    }


def test_the_jcs_error_uses_a_registered_config_summary() -> None:
    assert JcsError.code == reasons.config.CONFIG_VALUE_NOT_JSON
