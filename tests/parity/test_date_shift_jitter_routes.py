"""`jitter_days: N` is the window [-N, N] on every date_shift route.

One config with `jitter_days: 7` runs on each route. Each cell asserts, from run evidence, the
route it took (a silent fallback to another route fails the cell), that every shift is inside
[-7, 7], and that the bytes equal the same config written as `min_days: -7, max_days: 7`.
out_of_core refuses date_shift, so its cell asserts the registered decline instead of output.
The chunked native lane needs the companion and lives in `tests/native`.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest

from decoy_engine.execution._sequential_native_ops import SEQ_DATE_SHIFT_DISPOSITION_KEY
from decoy_engine.execution.native._operator_params import DateShiftParams, resolve_operator_params
from decoy_engine.relationships._graph import OrphanPolicy
from tests.parity._d1a_hash_data import column_seed
from tests.parity._d2b_shapes import run_full, run_seq, strs
from tests.parity._d2c_date_shift_data import (
    DS_NS,
    ISO,
    ReferenceDateShiftKernel,
    date_payload_shape,
    date_shift_seed,
    hide_date_shift,
    install_date_shift,
)
from tests.parity.test_out_of_core_group_b_parity import (
    _gate_admits,
    _gate_codes,
    _payload_edge_job,
    _seed,
)

JITTER = 7
BASE = dt.date(2019, 1, 1)
CELLS = [None if i % 9 == 4 else (BASE + dt.timedelta(days=37 * i)).isoformat() for i in range(60)]
NATIVE = "rust_companion"
PYTHON = "python_scalar"


def _jitter_seed() -> Any:
    return column_seed(
        "date_shift",
        namespace=DS_NS,
        provider_config=(("date_format", ISO), ("jitter_days", JITTER)),
    )


def _bounds_seed() -> Any:
    return date_shift_seed(-JITTER, JITTER)


def _shape(seed: Any) -> Any:
    return date_payload_shape({"d": (strs(CELLS), seed)})


def _column(result: Any) -> list[Any]:
    return list(result.outputs["P"].column("d").to_pylist())


def _assert_inside_window(out: list[Any], source: list[Any] = CELLS) -> None:
    moved = 0
    for before, after in zip(source, out, strict=True):
        if before is None:
            assert after is None
            continue
        delta = (dt.date.fromisoformat(after) - dt.date.fromisoformat(before)).days
        assert -JITTER <= delta <= JITTER, delta
        moved += delta != 0
    assert moved > 0  # the shift ran; a no-op would pass the window check


def _disposition(result: Any) -> list[dict[str, Any]]:
    return [
        e
        for e in result.quality_metrics.get(SEQ_DATE_SHIFT_DISPOSITION_KEY, [])
        if e["column"] == "d"
    ]


def test_full_frame_pandas_handler() -> None:
    jitter, bounds = run_full(_shape(_jitter_seed())), run_full(_shape(_bounds_seed()))
    # The full-frame adapter never goes through the sequential route.
    assert SEQ_DATE_SHIFT_DISPOSITION_KEY not in jitter.quality_metrics
    assert _column(jitter) == _column(bounds)
    _assert_inside_window(_column(jitter))


def test_sequential_pandas(monkeypatch: pytest.MonkeyPatch) -> None:
    hide_date_shift(monkeypatch)
    jitter, bounds = run_seq(_shape(_jitter_seed())), run_seq(_shape(_bounds_seed()))
    for run in (jitter, bounds):
        [entry] = _disposition(run)
        assert entry["executed_backend"] == PYTHON
    assert _column(jitter) == _column(bounds)
    assert _column(jitter) == _column(run_full(_shape(_jitter_seed())))
    _assert_inside_window(_column(jitter))


def test_sequential_native_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = install_date_shift(monkeypatch, ReferenceDateShiftKernel())
    jitter, bounds = run_seq(_shape(_jitter_seed())), run_seq(_shape(_bounds_seed()))
    for run in (jitter, bounds):
        [entry] = _disposition(run)
        assert entry["executed_backend"] == NATIVE
    assert kernel.calls
    assert {c.pool_size for c in kernel.calls} == {2 * JITTER + 1}
    assert _column(jitter) == _column(bounds)
    assert _column(jitter) == _column(run_full(_shape(_jitter_seed())))
    _assert_inside_window(_column(jitter))


def test_native_parameters_for_the_shadow_binding_and_the_chunked_lane() -> None:
    cfg = {"date_format": ISO, "jitter_days": JITTER}
    params = resolve_operator_params("date_shift", target="d", provider_config=cfg, namespace=DS_NS)
    same = resolve_operator_params(
        "date_shift",
        target="d",
        provider_config={"date_format": ISO, "min_days": -JITTER, "max_days": JITTER},
        namespace=DS_NS,
    )
    assert isinstance(params, DateShiftParams)
    assert (params.min_days, params.max_days) == (-JITTER, JITTER)
    assert params == same


def _nested_seed(strategy_config: dict[str, Any]) -> Any:
    return column_seed(
        "nested",
        namespace=DS_NS,
        provider_config=(
            ("strategy", "date_shift"),
            ("strategy_config", strategy_config),
            ("target", "$.d"),
        ),
    )


def test_nested_date_shift_child() -> None:
    docs = [json.dumps({"d": d}) for d in CELLS if d is not None]
    jitter = run_full(
        date_payload_shape(
            {"d": (strs(docs), _nested_seed({"date_format": ISO, "jitter_days": 7}))}
        )
    )
    bounds = run_full(
        date_payload_shape(
            {
                "d": (
                    strs(docs),
                    _nested_seed({"date_format": ISO, "min_days": -7, "max_days": 7}),
                )
            }
        )
    )
    got = [json.loads(v)["d"] for v in _column(jitter)]
    assert got == [json.loads(v)["d"] for v in _column(bounds)]
    _assert_inside_window(got, [d for d in CELLS if d is not None])


def test_out_of_core_declines_date_shift() -> None:
    seed = _seed(
        "date_shift",
        namespace="dns",
        provider_config=(("date_format", ISO), ("jitter_days", JITTER)),
    )
    plan, _sources, graph = _payload_edge_job(
        seed, ["2024-01-01"] * 3, policy=OrphanPolicy.PRESERVE
    )
    assert not _gate_admits(plan, graph)
    assert "out_of_core_row_error_strategy_unsupported" in _gate_codes(plan, graph)
