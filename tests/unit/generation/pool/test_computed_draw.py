"""GEN-NONFAKER-DRAWS S1: the formatter and spec behind the computed Faker draws.

AT-3 (formatter half): the uuid layout is RFC 9562 version 4 and equals the stdlib's layout for the
same 16 bytes; integers follow `lo + index * step`; choices come from the element list. The
expected uuids come from `uuid.UUID(bytes=..., version=4)`, never from the formatter itself.
"""

from __future__ import annotations

import re
import uuid

import numpy as np
import pyarrow as pa
import pytest

from decoy_engine.generation.pool import (
    ComputedDrawSpec,
    DrawRefusal,
    choice_from_index,
    computed_draw_spec,
    draw_kwargs,
    int_from_index,
    parse_computed_draw,
    uuid_from_bits,
    uuid_from_hex,
)

UUID_V4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")


def _bits(n: int, seed: int = 7) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, size=(n, 16), dtype=np.uint8)


class TestUuidFromBits:
    def test_matches_the_stdlib_layout_for_the_same_bytes(self) -> None:
        bits = _bits(300)
        got = uuid_from_bits(bits).to_pylist()
        want = [str(uuid.UUID(bytes=bytes(row), version=4)) for row in bits]
        assert got == want

    def test_every_value_is_version_4_variant_10(self) -> None:
        for fill in (0x00, 0xFF, 0xA5):
            bits = np.full((3, 16), fill, dtype=np.uint8)
            assert all(UUID_V4.match(v) for v in uuid_from_bits(bits).to_pylist())

    def test_all_zero_bits_pin_the_version_and_variant_nibbles(self) -> None:
        assert uuid_from_bits(np.zeros((1, 16), dtype=np.uint8)).to_pylist() == [
            "00000000-0000-4000-8000-000000000000"
        ]

    def test_does_not_modify_the_caller_array(self) -> None:
        bits = _bits(4)
        before = bits.copy()
        uuid_from_bits(bits)
        assert np.array_equal(bits, before)

    def test_empty_input_gives_an_empty_string_array(self) -> None:
        out = uuid_from_bits(np.zeros((0, 16), dtype=np.uint8))
        assert out.type == pa.string() and len(out) == 0

    def test_a_wrong_shape_is_refused(self) -> None:
        with pytest.raises(ValueError):
            uuid_from_bits(np.zeros((2, 15), dtype=np.uint8))


class TestUuidFromHex:
    def test_decodes_tokens_and_keeps_nulls_in_place(self) -> None:
        raw = _bits(3)
        tokens = [bytes(r).hex() for r in raw]
        out = uuid_from_hex(pa.array([tokens[0], None, tokens[1], tokens[2]], pa.string()))
        want = [str(uuid.UUID(bytes=bytes(r), version=4)) for r in raw]
        assert out.to_pylist() == [want[0], None, want[1], want[2]]

    def test_a_short_token_is_a_kernel_fault(self) -> None:
        with pytest.raises(ValueError):
            uuid_from_hex(pa.array(["ab" * 15], pa.string()))

    def test_lengths_that_cancel_out_are_still_a_kernel_fault(self) -> None:
        # 31 + 33 chars decode to the same bytes as two good tokens; only the per-token check sees it
        with pytest.raises(ValueError):
            uuid_from_hex(pa.array(["a" * 31, "b" * 33], pa.string()))

    def test_a_long_token_is_a_kernel_fault(self) -> None:
        with pytest.raises(ValueError):
            uuid_from_hex(pa.array(["ab" * 17], pa.string()))


class TestIntFromIndex:
    def test_honors_the_step(self) -> None:
        out = int_from_index(np.array([0, 1, 2, 3], dtype=np.uint64), lo=10, step=5)
        assert out.type == pa.int64()
        assert out.to_pylist() == [10, 15, 20, 25]

    def test_negative_lower_bound(self) -> None:
        out = int_from_index(np.array([0, 4], dtype=np.uint64), lo=-8, step=4)
        assert out.to_pylist() == [-8, 8]

    def test_a_product_past_int64_wraps_to_the_exact_value(self) -> None:
        # index * step reaches 2**64 - 256, past int64; the final value still fits.
        out = int_from_index(np.array([0, 2**56 - 1], dtype=np.uint64), lo=-(2**63), step=256)
        assert out.to_pylist() == [-(2**63), 2**63 - 256]


class TestChoiceFromIndex:
    def test_selects_the_element_at_each_index(self) -> None:
        got = choice_from_index(np.array([2, 0, 1, 2], dtype=np.uint64), ("a", "b", "c"))
        assert got == ["c", "a", "b", "c"]

    def test_keeps_python_scalars(self) -> None:
        got = choice_from_index(np.array([0, 1], dtype=np.uint64), (1, 2))
        assert got == [1, 2] and all(type(v) is int for v in got)


class TestParseComputedDraw:
    def test_uuid_takes_no_arguments(self) -> None:
        spec = computed_draw_spec("mask", "uuid", {})
        assert isinstance(spec, ComputedDrawSpec) and spec.output_type == pa.string()
        assert isinstance(parse_computed_draw("mask", "uuid", {"x": 1}), DrawRefusal)

    def test_int_defaults_come_from_the_contract(self) -> None:
        spec = computed_draw_spec("mask", "random_int_range", {})
        assert spec is not None
        assert (spec.lo, spec.step, spec.count) == (0, 1, 10000)
        assert spec.output_type == pa.int64()

    def test_int_count_and_step(self) -> None:
        spec = computed_draw_spec("mask", "random_int_range", {"min": 10, "max": 50, "step": 5})
        assert spec is not None and spec.count == 9 and spec.step == 5

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"min": True},
            {"max": "5"},
            {"max": 5.0},
            {"min": 5, "max": 4},
            {"step": 0},
            {"step": -1},
            {"min": 0, "max": 2**56, "step": 1},
            {"min": 0, "max": 2**63},
            {"min": -(2**63) - 1, "max": 0},
            {"unknown": 1},
        ],
    )
    def test_int_arguments_outside_the_contract_are_a_range_refusal(self, kwargs: dict) -> None:
        assert parse_computed_draw("mask", "random_int_range", kwargs) == DrawRefusal("range")

    def test_int_count_at_the_limit_is_admitted(self) -> None:
        spec = computed_draw_spec("mask", "random_int_range", {"min": 0, "max": 2**56 - 1})
        assert spec is not None and spec.count == 2**56

    def test_choice_default_elements(self) -> None:
        spec = computed_draw_spec("mask", "random_choice", {})
        assert spec is not None and spec.elements == ("a", "b", "c")

    @pytest.mark.parametrize(
        ("elements", "arrow"),
        [
            (["x", "y"], pa.string()),
            ((1, 2, 3), pa.int64()),
            ([1.5, 2.5], pa.float64()),
            ([True, False], pa.bool_()),
        ],
    )
    def test_mask_choice_pins_the_homogeneous_arrow_type(self, elements, arrow) -> None:
        spec = computed_draw_spec("mask", "random_choice", {"elements": elements})
        assert spec is not None and spec.output_type == arrow

    @pytest.mark.parametrize(
        "elements",
        [[], (), "abc", {"a": 1}, [1, "a"], [1, 2.5], [True, 1], [None, "a"], [[1], [2]], [2**70]],
    )
    def test_mask_choice_refuses_empty_non_list_and_mixed(self, elements) -> None:
        found = parse_computed_draw("mask", "random_choice", {"elements": elements})
        assert found == DrawRefusal("choice")

    def test_provider_caller_keeps_text_for_mixed_scalars(self) -> None:
        spec = computed_draw_spec("provider", "random_choice", {"elements": [1, "a", 2.5]})
        assert spec is not None and spec.output_type == pa.string()

    def test_provider_caller_int_is_text(self) -> None:
        spec = computed_draw_spec("provider", "random_int_range", {})
        assert spec is not None and spec.output_type == pa.string()

    def test_faker_type_caller_takes_the_planned_type(self) -> None:
        spec = computed_draw_spec("faker_type", "random_int", {}, planned_output_type=pa.int32())
        assert spec is not None and spec.output_type == pa.int32()

    def test_a_non_computed_name_is_none(self) -> None:
        assert parse_computed_draw("mask", "person_email", {}) is None
        assert computed_draw_spec("mask", "person_email", {}) is None

    def test_a_refusal_carries_no_argument_value(self) -> None:
        found = parse_computed_draw("mask", "random_choice", {"elements": ["secret-token", 1]})
        assert repr(found) == "DrawRefusal(kind='choice')"


def test_draw_kwargs_drops_only_the_pool_build_knobs() -> None:
    assert draw_kwargs({"pool_size": 5, "locale": "en_US", "min": 1}) == {"min": 1}
    assert draw_kwargs(None) == {}
