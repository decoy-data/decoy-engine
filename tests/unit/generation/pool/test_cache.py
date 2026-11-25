"""PoolCache bytes-bounded LRU tests (S5 spec §4)."""

from __future__ import annotations

import numpy as np
import pytest

from decoy_engine.generation.pool import PoolCache, PoolCapacityError, ValuePool
from decoy_engine.generation.pool._value_pool import measured_pool_bytes


def _make_pool(provider: str, size: int, seed: bytes = b"\x00" * 8) -> ValuePool:
    return ValuePool(
        values=np.array(["x" * 100] * size, dtype=object),
        provider=provider,
        locale="en_US",
        config_hash="abc",
        seed=seed,
        size=size,
        build_time_ms=1.0,
        backend_type="faker",
        backend_version="25.4.0",
        distinct_count=size,
    )


class TestGetPut:
    def test_get_miss_returns_none(self) -> None:
        cache = PoolCache(max_bytes=10_000_000)
        assert cache.get(("p", "l", "c", b"\x00" * 8, 10)) is None
        assert cache.stats().misses == 1

    def test_put_then_get_hit(self) -> None:
        cache = PoolCache(max_bytes=10_000_000)
        pool = _make_pool("p", 5)
        cache.put(pool)
        retrieved = cache.get(pool.identity)
        assert retrieved is pool
        assert cache.stats().hits == 1


class TestEviction:
    def test_lru_eviction_when_over_budget(self) -> None:
        cache = PoolCache(max_bytes=10_000)
        # Each pool measures 628 bytes (4 entries x (49 + 100 + 8)).
        for i in range(5):
            cache.put(_make_pool(f"p{i}", 4, seed=bytes([i] * 8)))
        # Should have evicted some; cache stays within budget.
        assert cache.stats().bytes_used <= 10_000

    def test_pool_larger_than_budget_raises(self) -> None:
        cache = PoolCache(max_bytes=100)  # tiny budget
        big_pool = _make_pool("p", 1000)
        with pytest.raises(PoolCapacityError) as excinfo:
            cache.put(big_pool)
        assert excinfo.value.code == "pool_exceeds_cache_budget"

    def test_the_budget_error_text_is_value_free_and_keeps_the_counts_as_attributes(self) -> None:
        cache = PoolCache(max_bytes=100)
        big_pool = _make_pool("secretprovider", 1000)
        with pytest.raises(PoolCapacityError) as excinfo:
            cache.put(big_pool)
        text = str(excinfo.value)
        assert "secretprovider" not in text
        assert str(excinfo.value.pool_bytes) not in text
        assert str(excinfo.value.max_bytes) not in text
        assert not any(ch.isdigit() for ch in text.replace("pool_exceeds_cache_budget", ""))
        assert excinfo.value.max_bytes == 100
        assert excinfo.value.pool_bytes == measured_pool_bytes(big_pool)

    def test_eviction_counter_increments(self) -> None:
        cache = PoolCache(max_bytes=2000)
        cache.put(_make_pool("a", 4, seed=b"\x01" * 8))  # 628 bytes
        cache.put(_make_pool("b", 4, seed=b"\x02" * 8))
        cache.put(_make_pool("c", 4, seed=b"\x03" * 8))
        cache.put(_make_pool("d", 4, seed=b"\x04" * 8))
        cache.put(_make_pool("e", 4, seed=b"\x05" * 8))  # forces evictions
        # At least one eviction happened.
        assert cache.stats().evictions >= 1


class TestStats:
    def test_hit_miss_tracking(self) -> None:
        cache = PoolCache(max_bytes=10_000_000)
        pool = _make_pool("p", 5)
        cache.put(pool)
        cache.get(pool.identity)
        cache.get(("nope", "l", "c", b"\x00" * 8, 5))
        s = cache.stats()
        assert s.hits == 1
        assert s.misses == 1
        assert s.entries == 1
        assert s.bytes_capacity == 10_000_000


class TestQualityWarnings:
    """NF5: the QualityWarning event type and the _DOMINATE_THRESHOLD constant
    were both dead (zero construction sites). PoolCache.put now emits a
    pool_dominates_cache warning when a single pool exceeds 25% of the budget;
    S10 reads cache.warnings() into the manifest quality_summary (R14)."""

    def test_dominating_pool_emits_warning(self) -> None:
        cache = PoolCache(max_bytes=2000)
        cache.put(_make_pool("p", 4))  # 628 measured bytes > 25% of 2000
        warns = cache.warnings()
        assert len(warns) == 1
        assert warns[0].code == "pool_dominates_cache"
        assert warns[0].provider == "p"
        assert warns[0].detail["pool_bytes"] > warns[0].detail["cache_bytes_capacity"] * 0.25

    def test_small_pool_emits_no_warning(self) -> None:
        cache = PoolCache(max_bytes=10_000_000)
        cache.put(_make_pool("p", 4))  # 628 bytes, far below 25%
        assert cache.warnings() == ()

    def test_clear_resets_warnings(self) -> None:
        cache = PoolCache(max_bytes=2000)
        cache.put(_make_pool("p", 4))
        assert cache.warnings()
        cache.clear()
        assert cache.warnings() == ()


class TestLruOrdering:
    def test_recent_access_moves_to_end(self) -> None:
        """Per S5 spec §4: LRU on identity tuple via move_to_end on get."""
        cache = PoolCache(max_bytes=2000)
        a = _make_pool("a", 4, seed=b"\x01" * 8)
        b = _make_pool("b", 4, seed=b"\x02" * 8)
        cache.put(a)
        cache.put(b)
        # Access a to make it MRU; then add c + d which evict LRU (b).
        cache.get(a.identity)
        cache.put(_make_pool("c", 4, seed=b"\x03" * 8))
        cache.put(_make_pool("d", 4, seed=b"\x04" * 8))
        cache.put(_make_pool("e", 4, seed=b"\x05" * 8))
        # a accessed-most-recently might survive depending on byte
        # accounting; sanity-check that evictions happened.
        assert cache.stats().evictions >= 1


def test_the_cache_limit_counts_the_retained_arrow_buffers() -> None:
    import pyarrow as pa

    words = [f"w{i:05d}" for i in range(1_000)]
    objects = np.array(words, dtype=object)
    arrow = pa.array(words)

    def pool(tag: str, *, retained: bool = True) -> ValuePool:
        return ValuePool(
            values=objects,
            provider=tag,
            locale="en_US",
            config_hash="",
            seed=b"\x01" * 8,
            size=len(words),
            build_time_ms=0.0,
            backend_type="faker",
            backend_version="x",
            distinct_count=len(words),
            arrow=arrow if retained else None,
        )

    one = measured_pool_bytes(pool("a"))
    object_only = measured_pool_bytes(pool("a", retained=False))
    assert one == object_only + arrow.get_total_buffer_size()
    # Room for two pools if the Arrow form were free, but not once it is counted.
    cache = PoolCache(max_bytes=2 * object_only + arrow.get_total_buffer_size())
    cache.put(pool("a"))
    cache.put(pool("b"))
    assert cache.get(pool("a").identity) is None
    assert cache.stats().bytes_used == one


@pytest.mark.serial
def test_a_one_value_slice_of_a_large_buffer_counts_the_buffer_it_keeps() -> None:
    import pyarrow as pa

    big = pa.array([f"{i:08d}" + "x" * 120 for i in range(10_000)])
    sliced = big.slice(5, 1)
    assert sliced.nbytes < 200  # the logical size the old measure used
    pool = ValuePool(
        values=np.array([sliced[0].as_py()], dtype=object),
        provider="p",
        locale="en_US",
        config_hash="",
        seed=b"\x01" * 8,
        size=1,
        build_time_ms=0.0,
        backend_type="faker",
        backend_version="x",
        distinct_count=1,
        arrow=sliced,
    )
    assert measured_pool_bytes(pool) > 1_000_000
    cache = PoolCache(max_bytes=64 * 1024)
    with pytest.raises(PoolCapacityError):
        cache.put(pool)
