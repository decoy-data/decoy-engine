"""`snapshot_rows` owns the row checks (plan revision 2.7, AT-27j).

A gated reader takes its rows by position from a snapshot of the whole frame. A snapshot that is
not the length of that frame raises the reader's own coded error, whichever positions the gate
selected, and never an `IndexError`.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.execution import _pandas_adapter
from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution._exact_int_sources import gated_context
from decoy_engine.execution._strategies._date_shift import DateShiftStrategyHandler
from decoy_engine.generation.pool._cache import PoolCache
from decoy_engine.relationships._namespace import NamespaceRegistry
from tests.unit.execution.when import _write_support as ws

JOINT_CODE = "joint_mask_key_by_snapshot_misaligned"
DATE_CODE = "date_shift_group_anchor_snapshot_misaligned"
STATUS = ["go", "go", "no", "no"]


def _table(status: list[str]) -> pa.Table:
    return pa.table(
        {
            "k": ["k0", "k1", "k2", "k3"],
            "a_status": status,
            "city": ["c0", "c1", "c2", "c3"],
            "state": ["s0", "s1", "s2", "s3"],
        }
    )


def _joint_plan(ref: str) -> Any:
    return ws.plan(
        [
            ("a_status", ws.seed("redact")),
            ("city", ws.joint(ref, ["city", "state"], when="a_status == 'go'")),
        ]
    )


def _shorten_key_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the last row of the `k` snapshot, as a route that built it from another frame would."""
    real = _pandas_adapter.take_source_snapshots

    def take(*args: Any, **kwargs: Any) -> dict[tuple[str, str], pd.Series]:
        out = real(*args, **kwargs)
        return {key: (s.iloc[:-1] if key[1] == "k" else s) for key, s in out.items()}

    monkeypatch.setattr(_pandas_adapter, "take_source_snapshots", take)


def test_a_valid_gated_joint_mask_selection_passes(tmp_path: Any) -> None:
    ref = ws.reference(tmp_path / "c.parquet", city=["C0", "C1"], state=["S0", "S1"])
    out = ws.run(_joint_plan(ref), _table(["go", "go", "no", "no"]), bound=(("k",),))
    assert out.num_rows == 4


@pytest.mark.parametrize(
    "status", [["go", "go", "no", "no"], ["no", "no", "no", "go"]], ids=["early", "last"]
)
def test_a_short_snapshot_raises_the_joint_mask_code(
    status: list[str], tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = ws.reference(tmp_path / "c.parquet", city=["C0", "C1"], state=["S0", "S1"])
    _shorten_key_snapshot(monkeypatch)
    with pytest.raises(ExecutionError) as err:
        ws.run(_joint_plan(ref), _table(status), bound=(("k",),))
    assert err.value.code == JOINT_CODE


def _date_ctx(snapshot: pd.Series, positions: Any) -> StrategyContext:
    ctx = StrategyContext(
        registry=ws.REG,
        pool_cache=PoolCache(),
        relationship_graph=ws.NO_GRAPH,
        namespace_registry=NamespaceRegistry(bindings=()),
        job_seed=ws.SEED,
        mask_key=b"\x01" * 32,
        group_anchor_snapshots={("t", "g"): snapshot},
        source_snapshot_columns={},
    )
    object.__setattr__(ctx, "current_table", "t")
    return gated_context(ctx, "d", positions, 4)


def _date_run(snapshot: pd.Series, positions: Any) -> None:
    import numpy as np

    cfg = (("max_shift_days", 30), ("group_by", "g"), ("date_format", "%Y-%m-%d"))
    seed = ws.seed("date_shift", provider_config=cfg, namespace="nm", deterministic=True)
    pos = np.array(positions)
    sub = pd.DataFrame({"d": ["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"]}).iloc[pos]
    DateShiftStrategyHandler().run(sub.copy(), "d", seed, _date_ctx(snapshot, pos))


def test_a_valid_gated_date_shift_selection_passes() -> None:
    _date_run(pd.Series(["g0", "g1", "g2", "g3"]), [0, 1])


@pytest.mark.parametrize("positions", [[0, 1], [3]], ids=["early", "last"])
def test_a_short_snapshot_raises_the_date_shift_code(positions: list[int]) -> None:
    with pytest.raises(ExecutionError) as err:
        _date_run(pd.Series(["g0", "g1", "g2"]), positions)
    assert err.value.code == DATE_CODE
