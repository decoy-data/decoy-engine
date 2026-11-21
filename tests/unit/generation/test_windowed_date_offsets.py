"""S2 of GEN-WINDOWED-BATCH: windowed_date offsets come from the pool sampler's index kernel.

Each draw is `min_days + derive_index(seed, namespace, int(2 * row + k), span + 1)` over the
global row number `row`. These tests pin the properties the change must keep (window, shape,
partitioning, independence) and the new derivation itself (oracle, domain).
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from decoy_engine import reasons
from decoy_engine.generation._column_streams import WindowedDateStream
from decoy_engine.generation.pool._sampler import (
    compiled_index_kernel,
    reference_index_kernel,
)
from decoy_engine.generators.derivation import with_table
from decoy_engine.transforms.windowed_date import (
    WindowedDateConfig,
    WindowedDateError,
    WindowedDateRowNumberError,
    apply_windowed_date,
)
from tests.unit.generation._windowed_date_corpus import (
    SEED8,
    SEED32,
    build_cases,
    outcome,
    reference_apply_windowed_date,
)

CASES = build_cases()
ISO_ANCHOR = "2000-01-01"


def _frame(anchors: list[Any]) -> pd.DataFrame:
    return pd.DataFrame({"a": pd.Series(anchors, dtype=object)})


def _config(lo: int, hi: int, distribution: str) -> WindowedDateConfig:
    return WindowedDateConfig(anchor="a", min_days=lo, max_days=hi, distribution=distribution)


def _offset_days(anchor: Any, produced: str) -> int:
    return (pd.Timestamp(produced) - pd.Timestamp(anchor).normalize()).days


# --- 1. The window ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.expect_error is False], ids=lambda c: c.name
)
def test_offsets_in_window(case: Any) -> None:
    got = outcome(apply_windowed_date, case)
    assert got[0] == "ok", case.name
    anchors = case.frame()["a"].tolist()
    for anchor, produced in zip(anchors, got[1], strict=True):
        if produced is None:
            assert anchor is None or pd.isna(anchor)
            continue
        assert case.min_days <= _offset_days(anchor, produced) <= case.max_days


# --- 2. The shape of each distribution --------------------------------------------------------

_SHAPE_ROWS = 200_000
_CHI2_CRITICAL_P001_DF120 = 173.617  # upper-tail 0.001 point of chi-square with 120 df


def _shape_offsets(distribution: str) -> np.ndarray[Any, Any]:
    out = apply_windowed_date(
        _config(-30, 90, distribution),
        _frame([ISO_ANCHOR] * _SHAPE_ROWS),
        SEED8,
        "windowed_date/shape",
    )
    return np.array([_offset_days(ISO_ANCHOR, d) for d in out if d is not None])


def test_distribution_shape() -> None:
    uniform = _shape_offsets("uniform")
    counts = np.bincount(uniform + 30, minlength=121)
    assert counts.shape == (121,)
    expected = len(uniform) / 121
    chi2 = float(((counts - expected) ** 2 / expected).sum())
    assert chi2 < _CHI2_CRITICAL_P001_DF120, chi2
    assert counts.min() > 0  # both window edges are drawn
    midpoint = 30  # (-30 + 90) / 2
    assert _shape_offsets("early").mean() < midpoint - 15
    assert _shape_offsets("late").mean() > midpoint + 15


# --- 3. Compiled kernel equals reference kernel -----------------------------------------------


def test_compiled_equals_reference() -> None:
    compiled = compiled_index_kernel()
    if compiled is None:
        pytest.skip("native companion not installed")
    reference = reference_index_kernel()
    rows = [*range(300), 2**31, 2**32 - 1, 2**40 + 7, 2**62 - 1]
    sources = pa.array([2 * r + k for r in rows for k in (0, 1)], type=pa.int64())
    for seed in (SEED8, SEED32):
        for pool_size in (1, 2, 121, 2**40, 2**56):
            kwargs = {"mask_key": seed, "namespace": "windowed_date/k", "pool_size": pool_size}
            got = compiled.derive_index_batch(sources, **kwargs)
            want = reference.derive_index_batch(sources, **kwargs)
            assert got.to_pylist() == want.to_pylist()


# --- 4. Partitioning --------------------------------------------------------------------------


@settings(
    max_examples=120,
    derandomize=True,
    database=None,
    deadline=None,
    suppress_health_check=list(HealthCheck),
)
@given(
    n=st.integers(1, 60),
    start=st.sampled_from([0, 5, 65_536, 2**32, 2**61]),
    cuts=st.lists(st.integers(0, 60), max_size=4),
    dist=st.sampled_from(["uniform", "early", "late"]),
    gate=st.lists(st.booleans(), min_size=60, max_size=60),
    null_every=st.sampled_from([0, 3, 7]),
)
def test_partitionable(
    n: int, start: int, cuts: list[int], dist: str, gate: list[bool], null_every: int
) -> None:
    anchors: list[Any] = [f"20{10 + (i % 15):02d}-0{1 + (i % 9)}-1{i % 9}" for i in range(n)]
    if null_every:
        for i in range(0, n, null_every):
            anchors[i] = None
    cfg = _config(-30, 90, dist)
    ns = "windowed_date/part"

    def run(df_anchors: list[Any], offset: int = 0, positions: list[int] | None = None) -> Any:
        return apply_windowed_date(
            cfg, _frame(df_anchors), SEED8, ns, row_offset=offset, positions=positions
        )

    whole = run(anchors, start)
    bounds = sorted({0, n, *(c for c in cuts if c < n)})
    chunked: list[Any] = []
    for lo, hi in pairwise(bounds):
        chunked.extend(run(anchors[lo:hi], start + lo))
    assert chunked == whole

    picked = [i for i in range(n) if gate[i]]
    if picked:
        gated = run([anchors[i] for i in picked], 0, [start + i for i in picked])
        assert gated == [whole[i] for i in picked]


# --- 5. Namespace independence ----------------------------------------------------------------


def _differing_share(ns_a: str, ns_b: str, dist: str) -> float:
    cfg = _config(-1000, 1000, dist)
    rows = [ISO_ANCHOR] * 10_000
    a = apply_windowed_date(cfg, _frame(rows), SEED8, ns_a)
    b = apply_windowed_date(cfg, _frame(rows), SEED8, ns_b)
    return sum(x != y for x, y in zip(a, b, strict=True)) / len(rows)


@pytest.mark.parametrize("dist", ["uniform", "early", "late"])
def test_namespace_independence(dist: str) -> None:
    assert _differing_share("windowed_date/x", "windowed_date/y", dist) >= 0.99
    # A column named `x/draw2` shares nothing with `x`: the draw index is in the source.
    assert _differing_share("windowed_date/x", "windowed_date/x/draw2", dist) >= 0.99


# --- 6. Mask and generate share one derivation ------------------------------------------------


def test_mask_and_generate_share_the_derivation() -> None:
    anchors: list[Any] = [f"19{60 + (i % 40):02d}-03-{1 + (i % 28):02d}" for i in range(80)]
    anchors[5] = None
    col = {
        "name": "end",
        "anchor": "start",
        "min_days": -4,
        "max_days": 40,
        "distribution": "early",
    }
    stream = WindowedDateStream(with_table(col, "t"), seed=int.from_bytes(SEED8, "big"))
    offset = 1_000
    generated = stream.next_batch_from(offset, len(anchors), {"start": list(anchors)})

    cfg = WindowedDateConfig(anchor="start", min_days=-4, max_days=40, distribution="early")
    frame = pd.DataFrame({"start": pd.Series(anchors, dtype=object)})
    oracle = reference_apply_windowed_date(cfg, frame, SEED8, stream._namespace, row_offset=offset)
    assert generated == oracle
    assert any(v is not None for v in oracle)

    # The mask leg runs through the strategy handler, which keys on `windowed_date/<column>`.
    handler_out = _run_handler(
        anchors,
        {"anchor": "start", "min_days": -4, "max_days": 40, "distribution": "early"},
        row_offset=offset,
    )
    assert handler_out == reference_apply_windowed_date(
        cfg, frame, SEED8, "windowed_date/end", row_offset=offset
    )
    assert handler_out[5] is None and any(v is not None for v in handler_out)


def _run_handler(anchors: list[Any], pc: dict[str, Any], *, row_offset: int = 0) -> list[Any]:
    from decoy_engine.execution._adapter import StrategyContext
    from decoy_engine.execution._strategies._windowed_date import WindowedDateStrategyHandler
    from decoy_engine.generation.pool._cache import PoolCache
    from decoy_engine.plan._types import ColumnSeed
    from decoy_engine.providers_v2 import get_default_registry
    from decoy_engine.relationships._graph import RelationshipGraph
    from decoy_engine.relationships._namespace import NamespaceRegistry

    ctx = StrategyContext(
        registry=get_default_registry(),
        pool_cache=PoolCache(),
        relationship_graph=RelationshipGraph(edges=(), ordering=()),
        namespace_registry=NamespaceRegistry(bindings=()),
        job_seed=SEED8,
        mask_key=SEED8,
        row_offset=row_offset,
    )
    seed = ColumnSeed(
        namespace="ns",
        strategy="windowed_date",
        provider=None,
        backend_type="transform",
        backend_version="v1",
        cardinality_mode="preserve",
        deterministic=False,
        provider_config=tuple(pc.items()),
    )
    df = pd.DataFrame({"start": pd.Series(anchors, dtype=object), "end": [""] * len(anchors)})
    out, _ = WindowedDateStrategyHandler().run(df, "end", seed, ctx)
    result: list[Any] = out["end"].tolist()
    return result


@pytest.mark.parametrize("days", [106_752, -106_752])
@pytest.mark.parametrize("key", ["min_days", "max_days"])
def test_window_beyond_the_date_range_is_refused_at_parse(key: str, days: int) -> None:
    from decoy_engine.plan._errors import PlanCompileError

    cfg = {"anchor": "a", "min_days": -5, "max_days": 5, key: days}
    with pytest.raises(PlanCompileError) as exc:
        WindowedDateConfig.from_dict(cfg)
    assert exc.value.code in {"windowed_date_window_out_of_range", "windowed_date_min_exceeds_max"}
    if days > 0 or key == "min_days":
        assert exc.value.code == "windowed_date_window_out_of_range"
    assert str(abs(days)) not in str(exc.value)
    if exc.value.code == "windowed_date_window_out_of_range":
        assert exc.value.path == f"provider_config.{key}"
    WindowedDateConfig.from_dict({"anchor": "a", "min_days": -106_751, "max_days": 106_751})


def test_bulk_fallback_matches_per_row_and_keeps_first_error() -> None:
    # A mixed date/str column leaves the batched path; the loop must draw the same offsets.
    import datetime as dt

    cfg = _config(-30, 90, "early")
    anchors: list[Any] = [
        dt.date(2000 + i % 20, 1 + i % 12, 1 + i % 28)
        if i % 2
        else f"20{10 + i % 10}-05-0{1 + i % 9}"
        for i in range(300)
    ]
    anchors[7] = None
    frame = _frame(anchors)
    got = apply_windowed_date(cfg, frame, SEED8, "windowed_date/d", row_offset=40)
    assert got == reference_apply_windowed_date(cfg, frame, SEED8, "windowed_date/d", row_offset=40)
    bad = list(anchors)
    bad[3] = "not a date"
    bad[9] = "also bad"
    with pytest.raises(WindowedDateError) as exc:
        apply_windowed_date(cfg, _frame(bad), SEED8, "windowed_date/d", row_offset=40)
    # The message names no row (value-free); the first bad row in row order is an invalid anchor.
    assert exc.value.code == reasons.runtime.WINDOWED_DATE_ANCHOR_INVALID
    assert "43" not in str(exc.value)


@pytest.mark.serial
def test_mixed_column_fallback_is_not_slower_than_per_row_baseline() -> None:
    # Regression guard for the review finding: origin/main drew a mixed date/str column at about
    # 93 us/row and the first S2 head about 258. The bulk draw keeps it well under the baseline;
    # the 200 us/row ceiling leaves wide margin for a loaded CI box.
    import datetime as dt
    import time

    cfg = _config(-30, 90, "early")
    n = 5_000
    anchors: list[Any] = [
        dt.date(2000 + i % 20, 1 + i % 12, 1 + i % 28) if i % 2 else "2015-05-04" for i in range(n)
    ]
    frame = _frame(anchors)
    apply_windowed_date(cfg, frame, SEED8, "windowed_date/d")  # warm imports and caches
    best = min(
        _elapsed(lambda: apply_windowed_date(cfg, frame, SEED8, "windowed_date/d"), time)
        for _ in range(3)
    )
    assert best / n < 200e-6


def _elapsed(fn: Callable[[], object], time: Any) -> float:
    start = time.perf_counter()
    fn()
    return float(time.perf_counter() - start)


# --- 7. Row-number domain ---------------------------------------------------------------------


@pytest.mark.parametrize("row", [-1, 2**62, 2**63 - 1, 2**64 - 1])
def test_row_number_domain(row: int) -> None:
    cfg = _config(-30, 90, "uniform")
    with pytest.raises(WindowedDateRowNumberError) as exc:
        apply_windowed_date(cfg, _frame([ISO_ANCHOR]), SEED8, "windowed_date/d", row_offset=row)
    assert exc.value.code == "windowed_date_row_number_out_of_range"
    assert str(row) not in str(exc.value)
    assert exc.value.__cause__ is None and exc.value.__context__ is None
    # A negative or oversize `positions` entry is refused the same way.
    with pytest.raises(WindowedDateRowNumberError):
        apply_windowed_date(cfg, _frame([ISO_ANCHOR]), SEED8, "windowed_date/d", positions=[row])


def test_row_number_domain_edges_are_admitted() -> None:
    cfg = _config(-30, 90, "late")
    for row in (0, 2**62 - 1):
        out = apply_windowed_date(
            cfg, _frame([ISO_ANCHOR]), SEED8, "windowed_date/d", row_offset=row
        )
        assert out == reference_apply_windowed_date(
            cfg, _frame([ISO_ANCHOR]), SEED8, "windowed_date/d", row_offset=row
        )


def test_row_number_error_waits_for_earlier_row_errors() -> None:
    """A bad anchor at an earlier row raises its own error first, as row order says."""
    cfg = _config(0, 5, "uniform")
    frame = _frame(["2000-01-01", "not a date", ISO_ANCHOR])
    with pytest.raises(WindowedDateError) as exc:
        apply_windowed_date(cfg, frame, SEED8, "windowed_date/d", positions=[1, 2, -1])
    assert not isinstance(exc.value, WindowedDateRowNumberError)


# --- 8. Errors that do not involve row numbers keep their text --------------------------------


def test_non_row_errors_match_the_oracle() -> None:
    checked = 0
    for case in CASES:
        want = outcome(reference_apply_windowed_date, case)
        if want[0] != "err" or "row_offset" in case.name or "positions" in case.name:
            continue
        assert outcome(apply_windowed_date, case) == want, case.name
        checked += 1
    assert checked >= 30


# --- Windows the corpus does not carry --------------------------------------------------------


def _run_one(fn: Callable[..., Any], cfg: WindowedDateConfig, frame: pd.DataFrame) -> Any:
    try:
        return ("ok", fn(cfg, frame, SEED8, "windowed_date/w"))
    except Exception as exc:
        return ("err", type(exc).__name__, str(exc))


@pytest.mark.parametrize(
    ("lo", "hi"),
    [(2**62, 2**62 + 5), (-(2**62) - 5, -(2**62)), (0, 2**56), (0, 2**56 + 1), (5, 5)],
)
def test_extreme_windows_match_the_oracle(lo: int, hi: int) -> None:
    for dist in ("uniform", "early"):
        cfg = _config(lo, hi, dist)
        frame = _frame([ISO_ANCHOR, ISO_ANCHOR])
        assert _run_one(apply_windowed_date, cfg, frame) == _run_one(
            reference_apply_windowed_date, cfg, frame
        )


# --- The kernel's own result is checked before it becomes an offset ----------------------------


class _OutOfBoundsKernel:
    """Returns an index one past the pool, as a malformed compiled kernel could."""

    def derive_index_batch(self, values: Any, *, pool_size: int, **_kw: Any) -> pa.Array:
        return pa.array([pool_size] * len(values), type=pa.uint64())


def test_malformed_kernel_result_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from decoy_engine.generation.pool import GenerationError, _sampler

    monkeypatch.setattr(_sampler, "compiled_index_kernel", lambda: _OutOfBoundsKernel())
    with pytest.raises(GenerationError) as exc:
        apply_windowed_date(
            _config(0, 30, "uniform"), _frame([ISO_ANCHOR]), SEED8, "windowed_date/stub"
        )
    assert exc.value.code == "index_batch_out_of_bounds"
