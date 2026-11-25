"""ValuePool frozen-array + identity-tuple tests (S5 spec §2)."""

from __future__ import annotations

import sys
from typing import Any

import numpy as np
import pytest

from decoy_engine.generation.pool._value_pool import (
    ValuePool,
    _freeze_array,
    construction_floor,
    measured_pool_bytes,
)


def _make_pool(values: np.ndarray, **overrides) -> ValuePool:
    defaults = {
        "values": values,
        "provider": "person_email",
        "locale": "en_US",
        "config_hash": "abc",
        "seed": b"\x00" * 8,
        "size": len(values),
        "build_time_ms": 1.0,
        "backend_type": "faker",
        "backend_version": "25.4.0",
        "distinct_count": len(values),
    }
    defaults.update(overrides)
    return ValuePool(**defaults)


class TestFrozenness:
    def test_values_setflags_write_false_after_freeze(self) -> None:
        arr = np.array(["a", "b", "c"], dtype=object)
        _freeze_array(arr)
        with pytest.raises(ValueError):
            arr[0] = "x"

    def test_dataclass_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        pool = _make_pool(np.array(["a", "b"], dtype=object))
        with pytest.raises(FrozenInstanceError):
            pool.provider = "other"  # type: ignore[misc]


class TestIdentityTuple:
    def test_identity_is_five_tuple(self) -> None:
        pool = _make_pool(np.array(["a"], dtype=object))
        assert pool.identity == ("person_email", "en_US", "abc", b"\x00" * 8, 1)

    def test_identity_excludes_backend_version(self) -> None:
        """Per S5 spec §2: identity tuple is 5 fields; backend_version is
        NOT one of them. Faker patch shifts produce different pools
        (different values) but the cache key cannot depend on backend_version
        or every job would rebuild on every Faker patch."""
        pool_a = _make_pool(np.array(["a"], dtype=object), backend_version="25.4.0")
        pool_b = _make_pool(np.array(["a"], dtype=object), backend_version="26.0.0")
        # Same identity (5-tuple) despite different backend_version.
        assert pool_a.identity == pool_b.identity


class TestByteEstimate:
    def test_object_dtype_counts_each_string_object_and_its_slot(self) -> None:
        values = np.array(["hi", "ok", "yo"], dtype=object)
        pool = _make_pool(values)
        assert measured_pool_bytes(pool) == sum(sys.getsizeof(v) + 8 for v in values)

    def test_long_strings_are_not_undercounted(self) -> None:
        # A characters-only estimate charged 4 bytes per char and undercounted
        # short strings; the object size is the same on every length.
        values = np.array(["x" * 6, "y" * 30], dtype=object)
        assert measured_pool_bytes(_make_pool(values)) == (
            sys.getsizeof("x" * 6) + sys.getsizeof("y" * 30) + 16
        )

    def test_numeric_dtype_uses_nbytes(self) -> None:
        arr = np.array([1, 2, 3, 4], dtype=np.int64)
        pool = _make_pool(arr)
        assert measured_pool_bytes(pool) == arr.nbytes


class TestConstructionPeakFloor:
    def test_floor_is_above_the_final_pool_of_empty_strings(self) -> None:
        # The peak holds pointer copies and a set on top of the final pool, so the
        # floor must exceed the measured size of the smallest possible pool.
        n = 100
        pool = _make_pool(np.array([""] * n, dtype=object))
        assert construction_floor(n, strings=True) > measured_pool_bytes(pool)

    def test_floor_is_linear_in_size(self) -> None:
        for strings in (True, False):
            assert construction_floor(0, strings=strings) == 0
            assert construction_floor(10, strings=strings) == 10 * construction_floor(
                1, strings=strings
            )

    def test_the_type_free_floor_is_below_the_string_floor_and_above_an_int_pool(self) -> None:
        n = 100
        ints = _make_pool(np.array([1000 + i for i in range(n)], dtype=object))
        assert construction_floor(n, strings=False) < construction_floor(n, strings=True)
        # Distinct ints are real objects, so the final pool is above the bare slots but the
        # type-free floor never exceeds what the build holds.
        assert (
            construction_floor(n, strings=False) <= measured_pool_bytes(ints) + 3 * 8 * n + 16 * n
        )


class TestNestedArrowRetention:
    def test_a_dictionary_inside_a_struct_counts_its_value_buffers(self) -> None:
        import pyarrow as pa

        big = "x" * 1_000_000
        dictionary = pa.array([big, "y"])
        indices = pa.array([0], type=pa.int8())
        nested = pa.StructArray.from_arrays(
            [pa.DictionaryArray.from_arrays(indices, dictionary)], names=["d"]
        )
        pool = _make_pool(np.array([1], dtype=np.int64), arrow=nested)
        assert measured_pool_bytes(pool) >= 1_000_000

    def test_a_buffer_shared_by_two_nested_arrays_counts_once(self) -> None:
        import pyarrow as pa

        shared = pa.array(["z" * 1000, "w"])
        nested = pa.StructArray.from_arrays([shared, shared], names=["a", "b"])
        pool = _make_pool(np.array([1], dtype=np.int64), arrow=nested)
        assert measured_pool_bytes(pool) < 2 * 1000 + 100


def _nested_dictionary_layouts() -> dict[str, Any]:
    import pyarrow as pa

    class Wrapped(pa.ExtensionType):
        def __init__(self, storage_type: pa.DataType) -> None:
            super().__init__(storage_type, "test.wrapped")

        def __arrow_ext_serialize__(self) -> bytes:
            return b""

        @classmethod
        def __arrow_ext_deserialize__(cls, storage_type: Any, serialized: bytes) -> Any:
            return cls(storage_type)

    big = pa.array(["x" * 1_000_000, "y"])
    d = pa.DictionaryArray.from_arrays(pa.array([0, 1], pa.int8()), big)
    off = pa.array([0], pa.int32())
    size = pa.array([2], pa.int32())
    return {
        "struct": pa.StructArray.from_arrays([d], names=["d"]),
        "list": pa.ListArray.from_arrays(pa.array([0, 2], pa.int32()), d),
        "large_list": pa.LargeListArray.from_arrays(pa.array([0, 2], pa.int64()), d),
        "fixed_size_list": pa.FixedSizeListArray.from_arrays(d, 2),
        "list_view": pa.ListViewArray.from_arrays(off, size, d),
        "large_list_view": pa.LargeListViewArray.from_arrays(
            off.cast(pa.int64()), size.cast(pa.int64()), d
        ),
        "run_end_encoded": pa.RunEndEncodedArray.from_arrays(pa.array([2], pa.int32()), d),
        "extension": pa.ExtensionArray.from_storage(Wrapped(d.type), d),
        "struct_of_list_view": pa.StructArray.from_arrays(
            [pa.ListViewArray.from_arrays(off, size, d)], names=["v"]
        ),
        "map": pa.MapArray.from_arrays(pa.array([0, 2], pa.int32()), d.cast(d.type), d),
    }


@pytest.mark.parametrize("layout", sorted(_nested_dictionary_layouts()))
def test_every_nested_layout_counts_its_dictionary_and_the_cache_refuses_it(layout: str) -> None:
    from decoy_engine.generation.pool import PoolCache, PoolCapacityError

    arrow = _nested_dictionary_layouts()[layout]
    pool = _make_pool(np.array([1], dtype=np.int64), arrow=arrow)
    assert measured_pool_bytes(pool) >= 1_000_000
    with pytest.raises(PoolCapacityError):
        PoolCache(max_bytes=1024).put(pool)
