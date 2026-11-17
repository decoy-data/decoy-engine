"""The bounded, lexeme-keeping mode of the one strict JSON reader, and its writer (F07 E1)."""

from __future__ import annotations

import json
import random
from typing import Any

import pytest

from decoy_engine._canonical import (
    MASK_CELL_BYTES,
    MASK_MAX_DEPTH,
    JsonNumber,
    StrictJsonError,
    strict_json_loads,
    strict_json_plain,
    strict_json_read,
    strict_json_write,
)
from decoy_engine._canonical._json import STRICT_JSON_TOKENS

_NESTED: dict[str, Any] = {
    "max_bytes": MASK_CELL_BYTES,
    "max_depth": MASK_MAX_DEPTH,
    "non_finite": "keep",
    "keep_lexemes": True,
    "max_int_digits": None,
}


def _token(text: Any, **kwargs: Any) -> str:
    with pytest.raises(StrictJsonError) as caught:
        strict_json_read(text, **kwargs)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    return caught.value.token


def _nest(depth: int) -> str:
    return "[" * depth + "]" * depth


def test_tokens_keep_their_first_four_and_add_the_bounds() -> None:
    assert STRICT_JSON_TOKENS[:4] == ("not_json", "duplicate_key", "non_finite", "out_of_range")
    assert STRICT_JSON_TOKENS[4:] == ("oversized", "too_deep")


def test_lexeme_mode_keeps_every_number_as_read() -> None:
    cell = '{"amt":1.10,"big":12345678901234567890.5,"e":1e400,"n":-0,"i":7}'
    parsed = strict_json_read(cell, **_NESTED)
    assert parsed["amt"] == JsonNumber(1.1, "1.10")
    assert parsed["e"] == JsonNumber(float("inf"), "1e400")
    assert parsed["i"] == 7 and type(parsed["i"]) is int
    assert strict_json_write(parsed) == (
        '{"amt": 1.10, "big": 12345678901234567890.5, "e": 1e400, "n": -0, "i": 7}'
    )
    assert json.loads(strict_json_write(parsed), parse_constant=_refuse)["amt"] == 1.1


def _refuse(_name: str) -> None:
    raise AssertionError("a non-finite token was written")


def test_a_lossless_cell_writes_the_same_bytes_as_json_dumps() -> None:
    rng = random.Random(7)
    for _ in range(200):
        cell = {
            "é": [rng.random(), rng.randint(-5, 5), "\ud800" if rng.random() < 0.5 else "x"],
            "k": {"z": None, "a": True, "ñ": rng.randint(0, 10**6)},
        }
        text = json.dumps(cell)
        assert strict_json_write(strict_json_read(text, **_NESTED)) == json.dumps(json.loads(text))


def test_a_cell_with_only_one_lossy_number_still_keeps_the_lossless_ones_as_dumps_would() -> None:
    parsed = strict_json_read('{"a":1.5,"b":2.50}', **_NESTED)
    assert strict_json_write(parsed) == '{"a": 1.5, "b": 2.50}'


def test_a_duplicate_key_is_refused() -> None:
    assert _token('{"a":1,"a":2}', **_NESTED) == "duplicate_key"


def test_size_is_measured_in_utf8_bytes_and_a_text_at_the_limit_passes() -> None:
    limit = 12
    three_byte = '"' + "€" * 4 + '"'  # 4 characters, 12 + 2 bytes
    assert len(three_byte) <= limit < len(three_byte.encode())
    assert _token(three_byte, max_bytes=limit) == "oversized"
    assert strict_json_read('"' + "€" * 3 + '"', max_bytes=11) == "€" * 3
    assert _token(b'"' + b"x" * 20 + b'"', max_bytes=10) == "oversized"
    assert strict_json_read('"' + "x" * 9 + '"', max_bytes=11) == "x" * 9


def test_a_raw_lone_surrogate_over_the_limit_is_oversized_not_a_crash() -> None:
    text = '"\ud800' + "\u20ac" * 40 + '"'  # 43 characters, 125 bytes counting the surrogate as 3
    assert _token(text, max_bytes=100) == "oversized"
    assert _token(text, max_bytes=124) == "oversized"
    assert _token(text, max_bytes=125) == "not_json"


def test_a_raw_lone_surrogate_under_the_limit_is_not_json() -> None:
    assert _token('"a\ud800b"', **_NESTED) == "not_json"
    assert _token('"a\ud800b"') == "not_json"


def test_an_escaped_surrogate_is_valid_json_and_is_written_back_escaped() -> None:
    parsed = strict_json_read('{"k":"\\ud800","x":1}', **_NESTED)
    assert strict_json_write(parsed) == '{"k": "\\ud800", "x": 1}'


def test_depth_at_the_limit_passes_and_one_more_is_too_deep() -> None:
    assert strict_json_read(_nest(MASK_MAX_DEPTH), **_NESTED) is not None
    assert _token(_nest(MASK_MAX_DEPTH + 1), **_NESTED) == "too_deep"
    assert _token('{"a":' * 5 + "1" + "}" * 5, max_depth=4) == "too_deep"


def test_the_depth_walk_accepts_exactly_the_limit_when_the_bracket_count_calls_for_it() -> None:
    # Brackets over the limit force the walk; the deepest chain is exactly at the limit.
    at_limit = "[" + _nest(MASK_MAX_DEPTH - 1) + ",[],[]]"
    assert at_limit.count("[") > MASK_MAX_DEPTH
    assert strict_json_read(at_limit, **_NESTED) is not None
    over = "[" + _nest(MASK_MAX_DEPTH) + ",[],[]]"
    assert _token(over, **_NESTED) == "too_deep"


def test_a_very_deep_cell_is_too_deep_in_bounded_mode_and_not_json_without_a_bound() -> None:
    assert _token(_nest(5000), **_NESTED) == "too_deep"
    assert _token(_nest(100_000)) == "not_json"
    with pytest.raises(StrictJsonError) as caught:
        strict_json_loads(_nest(100_000))
    assert caught.value.token == "not_json"


def test_trailing_whitespace_is_valid_and_trailing_text_is_not_json() -> None:
    assert strict_json_read('{"a":1}  \n', **_NESTED)["a"] == 1
    assert _token('{"a":1}x', **_NESTED) == "not_json"
    assert _token('{"a":1}\nx', **_NESTED) == "not_json"


def test_a_very_long_integer_keeps_its_lexeme_and_has_no_plain_value() -> None:
    digits = "9" * 4301
    parsed = strict_json_read(f'{{"n":{digits}}}', **_NESTED)
    assert parsed["n"] == JsonNumber(None, digits)
    assert strict_json_write(parsed) == f'{{"n": {digits}}}'
    with pytest.raises(StrictJsonError) as caught:
        strict_json_plain(parsed["n"])
    assert caught.value.token == "out_of_range"


def test_non_finite_literals_are_kept_or_refused_by_mode() -> None:
    parsed = strict_json_read("[NaN, Infinity, -Infinity]", non_finite="keep")
    assert strict_json_write(parsed) == "[NaN, Infinity, -Infinity]"
    assert _token("[NaN]") == "non_finite"


def test_plain_conversion_is_deep_and_leaves_no_json_number() -> None:
    parsed = strict_json_read('{"a":[1,{"b":2.5}],"c":"s"}', **_NESTED)
    plain = strict_json_plain(parsed)
    assert plain == {"a": [1, {"b": 2.5}], "c": "s"}
    assert type(plain["a"][0]) is int
    assert type(plain["a"][1]["b"]) is float


def test_loads_defaults_are_unchanged() -> None:
    assert strict_json_loads("[" + "9" * 20 + "]") == [int("9" * 20)]
    with pytest.raises(StrictJsonError) as caught:
        strict_json_loads("[" + "9" * 21 + "]")
    assert caught.value.token == "out_of_range"
    assert strict_json_loads('{"a":1.10}') == {"a": 1.1}


def test_a_number_that_prints_as_read_is_plain_and_only_a_lossy_one_is_a_json_number() -> None:
    parsed = strict_json_read(
        "[1, -5, 0, 1.5, 2.0, 1.10, 1e2, -0, 1E400, 12345678901234567890.5]", **_NESTED
    )
    plain, lossy = parsed[:5], parsed[5:]
    assert [type(v) for v in plain] == [int, int, int, float, float]
    assert all(isinstance(v, JsonNumber) for v in lossy)
    assert [v.lexeme for v in lossy] == ["1.10", "1e2", "-0", "1E400", "12345678901234567890.5"]
    assert strict_json_write(parsed) == (
        "[1, -5, 0, 1.5, 2.0, 1.10, 1e2, -0, 1E400, 12345678901234567890.5]"
    )


def test_a_tree_with_no_json_number_writes_as_json_dumps() -> None:
    tree = {"b": [1, 2.5, None, True], "a": {"k": "é"}}
    assert strict_json_write(tree) == json.dumps(tree)


def test_the_lexeme_writer_names_keys_as_json_dumps_does() -> None:
    tree = {1: JsonNumber(1.1, "1.10"), None: 2, False: 3, 2.5: 4, "é": 5}
    assert strict_json_write(tree) == ('{"1": 1.10, "null": 2, "false": 3, "2.5": 4, "\\u00e9": 5}')


def test_a_shallow_text_skips_the_depth_walk_and_a_deep_one_does_not() -> None:
    assert _token("[" * 5 + "]" * 5, max_depth=4) == "too_deep"
    assert strict_json_read("[" * 4 + "]" * 4, max_depth=4) == [[[[]]]]
    # Few brackets cannot nest past the bound, but a text over the bracket count is still walked.
    assert _token("[[[[[1]]]]]", max_depth=4) == "too_deep"


def test_json_number_repr_does_not_show_the_source_text() -> None:
    assert "1.10" not in repr(JsonNumber(1.1, "1.10"))
