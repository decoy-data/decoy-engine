"""B3 acceptance: run-scoped out-of-core faker pool lifecycle.

Plan: docs/plans/2026-10-26-substrate-route-coverage.md (B3). This slice adds a
run-scoped context that owns and reuses a bounded provider pool across batches.
It does NOT admit faker on the out-of-core route; that is B4. These tests drive
the new `OocFakerPoolContext` directly.

Each new assertion fails on the base commit (d613c804) because
`decoy_engine.execution.out_of_core._faker_pool` does not exist there.

The contract under test:
- one pool build per identity, reused across many simulated batches;
- identical identities share a pool; a changed locale/provider/namespace/config
  does not;
- a second context has independent state (no cross-run cache leakage);
- an oversized pool plan is refused with a caller-visible code BEFORE the
  provider is allocated (the builder's `build` is never called);
- the pool the context builds is byte-identical to one PoolBuilder builds
  directly for the same identity (the context does not alter construction);
- pool memory is bounded by the run allowance, never by a batch/source row
  count.
"""

from __future__ import annotations

import numpy as np
import pytest

from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution.native._real_type_admission import C1_PROVIDER_ALLOWLIST
from decoy_engine.execution.out_of_core._faker_pool import OocFakerPoolContext
from decoy_engine.generation.pool._builder import PoolBuilder
from decoy_engine.generation.pool._value_pool import (
    BUILD_HELD_BYTES_PER_VALUE,
    ValuePool,
    construction_floor,
    measured_pool_bytes,
)
from decoy_engine.providers_v2 import get_default_registry

_JOB_SEED = b"\x00\x01\x02\x03\x04\x05\x06\x07"
_OTHER_SEED = b"\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f"
_PROVIDER = "person_first_name"
_PROVIDER_2 = "person_last_name"
# Small pools keep the build cheap; the lifecycle, not the pool size, is tested.
_CFG = {"pool_size": 16}


class _CountingPoolBuilder(PoolBuilder):
    """Real PoolBuilder that counts `build` calls so a test can prove a pool is
    built exactly once (and never built at all when a plan is refused)."""

    def __init__(self, registry) -> None:  # type: ignore[no-untyped-def]
        super().__init__(registry)
        self.build_calls = 0

    def build(self, provider, **kwargs):  # type: ignore[no-untyped-def]
        self.build_calls += 1
        return super().build(provider, **kwargs)


class _FixedWidthPoolBuilder(_CountingPoolBuilder):
    """Counts builds but returns `size` distinct strings of one width, so a test controls the
    measured pool size without a provider. `build_calls` still proves a refusal came first."""

    def __init__(self, registry, *, width: int, ints: bool = False) -> None:  # type: ignore[no-untyped-def]
        super().__init__(registry)
        self._width = width
        self._ints = ints

    def build(self, provider, **kwargs):  # type: ignore[no-untyped-def]
        self.build_calls += 1
        size = kwargs["size"]
        # Ints above 256 are real 28-byte objects, not shared small ints.
        values = np.array(
            [1000 + i if self._ints else f"{i:0{self._width}d}" for i in range(size)],
            dtype=object,
        )
        values.setflags(write=False)
        return ValuePool(
            values=values,
            provider=provider,
            locale=kwargs.get("locale") or "default",
            config_hash=f"fixed|{kwargs.get('namespace')}",
            seed=b"\x00" * 8,
            size=size,
            build_time_ms=0.0,
            backend_type="stub",
            backend_version="0",
            distinct_count=size,
        )


@pytest.fixture
def registry():
    reg = get_default_registry()
    if not reg.get_capabilities(_PROVIDER).poolable:
        pytest.skip(f"{_PROVIDER} is not poolable in this environment")
    return reg


def _context(registry, *, max_pool_bytes=64 * 1024 * 1024, builder=None):
    return OocFakerPoolContext(
        registry=registry,
        job_seed=_JOB_SEED,
        max_pool_bytes=max_pool_bytes,
        builder=builder,
    )


def test_one_build_across_many_batches(registry):
    builder = _CountingPoolBuilder(registry)
    ctx = _context(registry, builder=builder)
    prepared = ctx.prepare(provider=_PROVIDER, namespace="ns", cfg=_CFG)

    pools = [ctx.get_pool(prepared) for _ in range(5)]  # five simulated batches

    assert builder.build_calls == 1
    assert ctx.builds == 1
    first = pools[0]
    for pool in pools[1:]:
        assert pool is first  # same cached object, not a rebuild
        np.testing.assert_array_equal(pool.values, first.values)


def test_identical_identity_shares_one_pool(registry):
    builder = _CountingPoolBuilder(registry)
    ctx = _context(registry, builder=builder)
    p1 = ctx.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG))
    p2 = ctx.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG))

    assert p1.identity == p2.identity
    pool1 = ctx.get_pool(p1)
    pool2 = ctx.get_pool(p2)
    assert pool1 is pool2
    assert builder.build_calls == 1


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param({"provider": _PROVIDER_2}, id="provider"),
        pytest.param({"namespace": "other_ns"}, id="namespace"),
        pytest.param({"cfg": {"pool_size": 16, "locale": "en_US"}}, id="locale"),
        pytest.param({"cfg": {"pool_size": 32}}, id="config_pool_size"),
    ],
)
def test_distinct_inputs_give_distinct_identity(registry, mutate):
    # prepare() resolves the identity WITHOUT building, so this proves the keying
    # across every dimension (provider/namespace/locale/config) with no
    # dependence on whether the changed provider or locale can actually be built.
    ctx = _context(registry)
    base_kwargs = {"provider": _PROVIDER, "namespace": "ns", "cfg": dict(_CFG)}
    changed_kwargs = {**base_kwargs, **mutate}
    base = ctx.prepare(**base_kwargs)
    changed = ctx.prepare(**changed_kwargs)
    assert base.identity != changed.identity


def test_distinct_identities_build_separately(registry):
    # A namespace change keeps the same poolable provider and locale, so both
    # pools build safely; two distinct identities must each build and be cached.
    builder = _CountingPoolBuilder(registry)
    ctx = _context(registry, builder=builder)
    a = ctx.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG))
    b = ctx.prepare(provider=_PROVIDER, namespace="other_ns", cfg=dict(_CFG))
    assert a.identity != b.identity
    ctx.get_pool(a)
    ctx.get_pool(b)
    assert builder.build_calls == 2
    assert ctx.pool_count == 2


def test_second_context_has_independent_state(registry):
    builder1 = _CountingPoolBuilder(registry)
    ctx1 = _context(registry, builder=builder1)
    prepared1 = ctx1.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG))
    ctx1.get_pool(prepared1)
    assert builder1.build_calls == 1

    builder2 = _CountingPoolBuilder(registry)
    ctx2 = _context(registry, builder=builder2)
    prepared2 = ctx2.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG))
    ctx2.get_pool(prepared2)
    # A fresh context rebuilds; it does not read ctx1's pools.
    assert builder2.build_calls == 1
    assert ctx2.builds == 1

    ctx1.close()
    assert ctx1.pool_count == 0


def test_reservation_refused_before_provider_allocation(registry):
    builder = _CountingPoolBuilder(registry)
    # A 1-byte allowance cannot hold any pool: the lower-bound check must
    # refuse before the provider is ever allocated.
    ctx = _context(registry, max_pool_bytes=1, builder=builder)
    prepared = ctx.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG))

    with pytest.raises(ExecutionError) as exc:
        ctx.get_pool(prepared)
    assert exc.value.code == "out_of_core_faker_pool_budget_exceeded"
    assert builder.build_calls == 0  # provider never allocated
    assert ctx.builds == 0


def test_w1b_a_huge_pool_size_is_refused_before_any_build(registry):
    builder = _CountingPoolBuilder(registry)
    ctx = _context(registry, builder=builder)
    prepared = ctx.prepare(provider=_PROVIDER, namespace="ns", cfg={"pool_size": 10**9})
    with pytest.raises(ExecutionError) as exc:
        ctx.get_pool(prepared)
    assert exc.value.code == "out_of_core_faker_pool_budget_exceeded"
    assert builder.build_calls == 0
    assert ctx.pool_count == 0
    for fragment in (_PROVIDER, str(10**9), str(64 * 1024 * 1024)):
        assert fragment not in str(exc.value)


def test_w1b_the_floor_is_the_real_cpython_str_cost_not_four_bytes(registry):
    # 500,000 values pass a 4-byte floor (2 MB) in an 8 MiB allowance but cannot fit at the
    # real floor (about 28 MB), so the refusal must come before any build.
    builder = _CountingPoolBuilder(registry)
    ctx = _context(registry, max_pool_bytes=8 * 1024 * 1024, builder=builder)
    prepared = ctx.prepare(provider=_PROVIDER, namespace="ns", cfg={"pool_size": 500_000})
    with pytest.raises(ExecutionError) as exc:
        ctx.get_pool(prepared)
    assert exc.value.code == "out_of_core_faker_pool_budget_exceeded"
    assert builder.build_calls == 0


def test_a_pool_that_measures_over_the_allowance_is_dropped_after_the_build(registry):
    # 100-char strings measure well above the construction-peak floor, so a budget just under
    # the measured size passes the pre-build guard and is refused only after the build.
    builder = _FixedWidthPoolBuilder(registry, width=100)
    probe = _context(registry, builder=builder)
    measured = measured_pool_bytes(
        probe.get_pool(probe.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG)))
    )
    assert construction_floor(_CFG["pool_size"], strings=True) < measured - 1
    builder.build_calls = 0
    ctx = _context(registry, max_pool_bytes=measured - 1, builder=builder)
    with pytest.raises(ExecutionError) as exc:
        ctx.get_pool(ctx.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG)))
    assert exc.value.code == "out_of_core_faker_pool_budget_exceeded"
    assert builder.build_calls == 1
    assert (ctx.builds, ctx.pool_count, ctx.reserved_bytes) == (0, 0, 0)


def test_w1d_the_construction_peak_guard_runs_before_the_build(registry):
    # 6-char strings measure well under the floor floor: the final pool would fit a budget set
    # just under the floor, but building it holds four pointer copies and a set on top, so it
    # must be refused before the builder is called.
    size = _CFG["pool_size"]
    builder = _FixedWidthPoolBuilder(registry, width=6)
    probe = _context(registry, builder=builder)
    measured = measured_pool_bytes(
        probe.get_pool(probe.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG)))
    )
    floor = construction_floor(size, strings=True)
    assert measured < floor
    builder.build_calls = 0

    ctx = _context(registry, max_pool_bytes=floor - 1, builder=builder)
    with pytest.raises(ExecutionError) as exc:
        ctx.get_pool(ctx.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG)))
    assert exc.value.code == "out_of_core_faker_pool_budget_exceeded"
    assert builder.build_calls == 0
    assert (ctx.builds, ctx.pool_count, ctx.reserved_bytes) == (0, 0, 0)

    # At the floor itself the build is allowed.
    ok = _context(registry, max_pool_bytes=floor, builder=builder)
    ok.get_pool(ok.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG)))
    assert builder.build_calls == 1


def test_w1e_a_pool_of_ints_that_fits_is_admitted_and_a_string_pool_over_allowance_is_not(registry):
    # An int costs less than an empty str, so the string floor must not refuse an int pool
    # that fits. The int provider is off the string allowlist, so it gets the type-free floor.
    size = _CFG["pool_size"]
    int_provider = "person_email"
    assert int_provider not in C1_PROVIDER_ALLOWLIST
    string_floor = construction_floor(size, strings=True)
    any_floor = construction_floor(size, strings=False)
    assert any_floor < string_floor
    allowance = (any_floor + string_floor) // 2

    ints = _FixedWidthPoolBuilder(registry, width=0, ints=True)
    ctx = _context(registry, max_pool_bytes=allowance, builder=ints)
    pool = ctx.get_pool(ctx.prepare(provider=int_provider, namespace="ns", cfg=dict(_CFG)))
    assert ints.build_calls == 1
    assert measured_pool_bytes(pool) <= allowance

    strings = _FixedWidthPoolBuilder(registry, width=6)
    sctx = _context(registry, max_pool_bytes=allowance, builder=strings)
    with pytest.raises(ExecutionError) as exc:
        sctx.get_pool(sctx.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG)))
    assert exc.value.code == "out_of_core_faker_pool_allowance_exceeded"
    assert strings.build_calls == 0


def test_the_peak_floor_counts_four_pointer_copies_and_a_set_slot():
    # Pins the documented per-value constants: string object, four 8-byte pointers, one
    # 16-byte set slot.
    import sys

    assert sys.getsizeof("") + 4 * 8 + 16 == BUILD_HELD_BYTES_PER_VALUE


def test_the_ledger_and_the_cache_charge_the_same_bytes_for_long_strings(registry):
    # 30-char strings: a characters-only estimate charged 120 B each, above the 87 B measured,
    # so the inner cache refused a pool the ledger said fit. One function now serves both.
    size = _CFG["pool_size"]
    builder = _FixedWidthPoolBuilder(registry, width=30)
    budget = construction_floor(size, strings=True)
    ctx = _context(registry, max_pool_bytes=budget, builder=builder)
    pool = ctx.get_pool(ctx.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG)))
    assert ctx.reserved_bytes == measured_pool_bytes(pool)
    assert ctx._cache.stats().bytes_used == ctx.reserved_bytes
    assert ctx.pool_count == 1


def test_a_second_pool_the_ledger_admits_is_not_evicted_by_the_cache(registry):
    size = _CFG["pool_size"]
    builder = _FixedWidthPoolBuilder(registry, width=30)
    one = measured_pool_bytes(
        _context(registry, builder=builder).get_pool(
            _context(registry, builder=builder).prepare(
                provider=_PROVIDER, namespace="ns", cfg=dict(_CFG)
            )
        )
    )
    # Room for two measured pools and the floor of the second.
    budget = max(2 * one, one + construction_floor(size, strings=True))
    builder.build_calls = 0
    ctx = _context(registry, max_pool_bytes=budget, builder=builder)
    for namespace in ("ns", "ns2"):
        ctx.get_pool(ctx.prepare(provider=_PROVIDER, namespace=namespace, cfg=dict(_CFG)))
    assert builder.build_calls == 2
    assert ctx.pool_count == 2
    assert ctx._cache.stats().evictions == 0


def test_pool_bytes_bounded_by_allowance_not_row_count(registry):
    # Allowance sized for exactly one pool; a second distinct pool is refused. The
    # bound is the allowance, independent of any batch size.
    builder = _FixedWidthPoolBuilder(registry, width=100)
    probe = _context(registry, builder=builder)
    first = probe.get_pool(probe.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG)))
    one_pool = measured_pool_bytes(first)
    ctx = OocFakerPoolContext(
        registry=registry,
        job_seed=_JOB_SEED,
        max_pool_bytes=one_pool,
        builder=builder,
    )
    ctx.get_pool(ctx.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG)))  # fits exactly
    assert ctx.reserved_bytes == one_pool
    other = ctx.prepare(provider=_PROVIDER, namespace="ns2", cfg=dict(_CFG))
    with pytest.raises(ExecutionError) as exc:
        ctx.get_pool(other)
    assert exc.value.code == "out_of_core_faker_pool_budget_exceeded"
    assert ctx.pool_count == 1


def test_invalid_pool_size_rejected(registry):
    ctx = _context(registry)
    with pytest.raises(ExecutionError) as exc:
        ctx.prepare(provider=_PROVIDER, namespace="ns", cfg={"pool_size": 0})
    assert exc.value.code == "out_of_core_faker_pool_size_invalid"


def test_context_pool_matches_direct_builder(registry):
    """The context must not alter pool construction: the pool it builds for an
    identity is byte-identical to one PoolBuilder builds directly."""
    ctx = _context(registry)
    prepared = ctx.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG))
    ctx_pool = ctx.get_pool(prepared)

    direct = PoolBuilder(registry).build(
        _PROVIDER,
        size=prepared.pool_size,
        job_seed=_JOB_SEED,
        locale=prepared.locale,
        config=prepared.build_config,
        namespace=prepared.namespace,
    )
    assert ctx_pool.identity == direct.identity
    np.testing.assert_array_equal(ctx_pool.values, direct.values)


def test_distinct_job_seed_distinct_pool(registry):
    builder = _CountingPoolBuilder(registry)
    ctx1 = _context(registry, builder=builder)
    ctx2 = OocFakerPoolContext(
        registry=registry, job_seed=_OTHER_SEED, max_pool_bytes=64 * 1024 * 1024
    )
    p1 = ctx1.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG))
    p2 = ctx2.prepare(provider=_PROVIDER, namespace="ns", cfg=dict(_CFG))
    # job_seed enters the pool seed, so the identity differs across runs.
    assert p1.identity != p2.identity
