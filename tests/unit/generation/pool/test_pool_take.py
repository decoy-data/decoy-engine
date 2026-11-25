"""GEN-STREAM-ALL S1a: `pool_take` is the one pooled pick, and the REUSE sampler goes through it.

A2 take parity (unit half) and the no-other-gather inventory. The byte-level digests are in
`tests/unit/generation/stream/test_take_move.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

import decoy_engine.generation as generation_pkg
from decoy_engine.determinism import seed_bytes_to_int
from decoy_engine.generation._faker_pool import PooledSelector
from decoy_engine.generation.pool import _value_pool
from decoy_engine.generation.pool._cardinality import CardinalityMode
from decoy_engine.generation.pool._sampler import PoolSampler
from decoy_engine.generation.pool._value_pool import ValuePool, _freeze_array, pool_take

_WORDS = [f"w{i:04d}" for i in range(257)] + ["", "naïve", "日本"]


def _pool(*, with_arrow: bool) -> ValuePool:
    values = _freeze_array(np.array(_WORDS, dtype=object))
    return ValuePool(
        values=values,
        provider="gen.faker_pool.first_name",
        locale="en_US",
        config_hash="",
        seed=b"\x01" * 8,
        size=len(values),
        build_time_ms=0.0,
        backend_type="faker",
        backend_version="x",
        distinct_count=len(set(_WORDS)),
        arrow=pa.array(_WORDS) if with_arrow else None,
    )


def test_pool_take_gathers_by_index_and_keeps_nulls() -> None:
    pool = pa.array(["a", None, "c"])
    out = pool_take(pool, np.array([2, 0, 0, 1, 2]))
    assert out.to_pylist() == ["c", "a", "a", None, "c"]
    assert out.type == pool.type


@pytest.mark.parametrize("with_arrow", [True, False])
def test_reuse_sample_equals_the_numpy_object_gather(with_arrow: bool) -> None:
    """The oracle is the pre-S1a draw written out: `integers` then an object-array gather."""
    seed = b"\x07" * 8
    n = 5_000
    pool = _pool(with_arrow=with_arrow)
    rng = np.random.default_rng(seed_bytes_to_int(seed))
    expected = pd.Series(pool.values[rng.integers(0, pool.size, size=n)])
    got = PoolSampler().sample(pool, n, mode=CardinalityMode.REUSE, seed=seed, deterministic=False)
    assert got.dtype == expected.dtype
    assert got.tolist() == expected.tolist()


def test_reuse_sample_calls_pool_take_when_the_pool_has_an_arrow_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    real = _value_pool.pool_take

    def spy(pool: pa.Array, indices: np.ndarray) -> pa.Array:
        calls.append(len(indices))
        return real(pool, indices)

    monkeypatch.setattr(_value_pool, "pool_take", spy)
    PoolSampler().sample(_pool(with_arrow=True), 100, mode=CardinalityMode.REUSE, seed=b"\x01" * 8)
    assert calls == [100]


def test_selector_take_matches_select_and_the_same_draw() -> None:
    values = _freeze_array(np.array(_WORDS, dtype=object))
    seed = b"\x09" * 8
    by_take = PooledSelector(values, seed)
    by_select = PooledSelector(values, seed)
    taken = by_take.take(3_000)
    assert isinstance(taken, pa.Array)
    assert taken.to_pylist() == by_select.select(3_000)
    # The stream is position-based: a second call continues it.
    assert by_take.take(10).to_pylist() == by_select.select(10)


# `pool.values[...]` gathers that remain, by file. Each is a keyed or bundle read that is not a
# REUSE pick: derived indices (`derive_pool_indices`), the MATCH/SCALE source map, and the bundle
# pool's tuples. The one REUSE gather lives in `_value_pool.pool_pick`.
_REMAINING_GATHERS = {
    "pool/_pool_adapter.py": 1,
    "pool/_sampler.py": 3,
    "pool/_value_pool.py": 1,
}


def test_no_other_pool_values_gather_remains() -> None:
    root = Path(generation_pkg.__file__).parent
    found: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        count = len(re.findall(r"\bpool\.values\[", path.read_text(encoding="utf-8")))
        if count:
            found[path.relative_to(root).as_posix()] = count
    assert found == _REMAINING_GATHERS
