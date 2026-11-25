"""GEN-STREAM-ALL S1a: `pool_take` is the one pooled pick, and the REUSE sampler goes through it.

A2 take parity (unit half) and the no-other-gather inventory. The byte-level digests are in
`tests/unit/generation/stream/test_take_move.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

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


def test_select_draws_the_same_indices_as_take_including_null_values() -> None:
    """`select` and `take` share one draw; a None pool value comes back as None in both."""
    words = [*_WORDS[:40], None, "x", None]
    values = _freeze_array(np.array(words, dtype=object))
    seed = b"\x0b" * 8
    by_take = PooledSelector(values, seed)
    by_select = PooledSelector(values, seed)
    for size in (1, 999, 4096, 7):
        taken = by_take.take(size).to_pylist()
        assert taken == by_select.select(size)
    assert None in by_select.select(2_000)


def test_select_gathers_from_the_object_array_without_the_arrow_take(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """the list path is an object gather, so it never pays `take` plus `to_pylist`."""
    from decoy_engine.generation import _faker_pool

    def refuse(*_args: Any) -> pa.Array:
        raise AssertionError("select must not call pool_take")

    monkeypatch.setattr(_faker_pool, "pool_take", refuse)
    values = _freeze_array(np.array(_WORDS, dtype=object))
    seed = b"\x0c" * 8
    rng = np.random.default_rng(seed_bytes_to_int(seed))
    expected = values[rng.integers(0, len(values), size=500)].tolist()
    assert PooledSelector(values, seed).select(500) == expected


def test_a_pool_arrow_cannot_type_builds_and_selects_without_an_arrow_form() -> None:
    """the selector builds its Arrow form through the guarded `_arrow_form`."""
    values = _freeze_array(np.array([1, "a", 2.5], dtype=object))
    selector = PooledSelector(values, b"\x0d" * 8)
    assert selector.has_arrow is False
    assert set(selector.select(50)) <= {1, "a", 2.5}
    with pytest.raises(ValueError, match="no Arrow form"):
        selector.take(3)


# Pool-value gathers that remain, by file and function. A gather is a subscript on a `.values`
# or `._values` attribute, or on a local name bound to one (`pool_values = pool.values`).
# Each one outside `pool_pick` is not a REUSE pick: keyed indices (`derive_pool_indices`), the
# MATCH/SCALE source map, bundle tuples, the selector's object-form `select`, or a numeric
# shape's breakpoints. `pool_pick` keeps a dual Arrow/object gather because pools built without
# an Arrow form (mixed-type values Arrow cannot type) must still sample.
_REMAINING_GATHERS = {
    "_faker_pool.py::PooledSelector.select": 1,
    "pool/_pool_adapter.py::PoolAdapter.generate": 1,
    "pool/_sampler.py::PoolSampler._deterministic": 1,
    "pool/_sampler.py::PoolSampler._match_source_cardinality": 1,
    "pool/_sampler.py::PoolSampler.sample_bundle": 2,
    "pool/_value_pool.py::pool_pick": 1,
    "statistical/_sample.py::_sample_shape": 2,
}
_VALUE_ATTRS = frozenset({"values", "_values"})


def _is_values_attr(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr in _VALUE_ATTRS


def _gathers(source: str) -> dict[str, int]:
    """Count value-array subscripts per enclosing function, following local aliases."""
    found: dict[str, int] = {}

    def visit(node: ast.AST, scope: tuple[str, ...], aliases: frozenset[str]) -> None:
        if isinstance(node, ast.ClassDef):
            scope = (*scope, node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = (*scope, node.name)
            bound = {
                target.id
                for sub in ast.walk(node)
                if isinstance(sub, (ast.Assign, ast.AnnAssign))
                and sub.value is not None
                and _is_values_attr(sub.value)
                for target in (sub.targets if isinstance(sub, ast.Assign) else [sub.target])
                if isinstance(target, ast.Name)
            }
            aliases = aliases | bound
        if isinstance(node, ast.Subscript) and (
            _is_values_attr(node.value)
            or (isinstance(node.value, ast.Name) and node.value.id in aliases)
        ):
            key = ".".join(scope) or "<module>"
            found[key] = found.get(key, 0) + 1
        for child in ast.iter_child_nodes(node):
            visit(child, scope, aliases)

    visit(ast.parse(source), (), frozenset())
    return found


def test_no_other_pool_values_gather_remains() -> None:
    root = Path(generation_pkg.__file__).parent
    found: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        for where, count in _gathers(path.read_text(encoding="utf-8")).items():
            found[f"{rel}::{where}"] = count
    assert found == _REMAINING_GATHERS


@pytest.mark.parametrize(
    "planted",
    [
        "def f(pool, ix):\n    v = pool.values\n    return v[ix]\n",
        "def f(pool, ix):\n    v: object = pool.values\n    return [v[i] for i in ix]\n",
        "class S:\n    def g(self, ix):\n        return self._values[ix]\n",
        "def f(pool, ix):\n    return pool.values[ix]\n",
    ],
)
def test_the_gather_scan_sees_direct_and_aliased_gathers(planted: str) -> None:
    assert sum(_gathers(planted).values()) == 1
