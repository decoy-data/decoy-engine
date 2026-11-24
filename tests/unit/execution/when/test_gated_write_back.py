"""Gated write-back keeps main's behavior for returned columns (plan revision 2.6, L2).

For each resolved output: an output absent from the handler's result is skipped, an existing
column takes the returned values at the selected positions, and a returned column the frame lacks
is created with a missing value on every other row. Expected values on the two routes are main's
output at `8ee461e0f` for the same fixture; the direct cases compare with a frozen copy of main's
`df.loc[mask, col] = sub[col]` stitch.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.execution._when_gate import run_with_when_gate
from tests.unit.execution.when import _write_support as ws

ROUTES = {"single": ws.run, "sequential": ws.run_sequential}
TABLE = pa.table({"flag": ["y", "n", "y", "n"], "g": ["a", "a", "b", "b"]})


def _run(route: str, plan: Any) -> pa.Table:
    return ROUTES[route](plan, TABLE, bound=(("g",),))


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_a_gated_derived_target_absent_from_the_source_matches_main(route: str) -> None:
    out = _run(route, ws.plan([("tgt", ws.derived('concat(g, "!")', when="flag == 'y'"))]))
    assert out.column_names == ["flag", "g", "tgt"]
    assert out.schema.field("tgt").type == pa.string()
    assert out.column("tgt").to_pylist() == ["a!", None, "b!", None]


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_a_gated_group_key_absent_from_the_source_matches_main(route: str) -> None:
    seed = ws.seed("group_key", provider_config=(("group_by", "g"),), when="flag == 'y'")
    out = _run(route, ws.plan([("gk", seed)]))
    assert out.column_names == ["flag", "g", "gk"]
    assert out.schema.field("gk").type == pa.string()
    assert out.column("gk").to_pylist() == ["335fdb386ac7e514", None, "35371bf110f7307c", None]


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_a_zero_match_creator_target_is_an_all_null_column_of_type_null(route: str) -> None:
    """Case 5 and L3. Main left the column absent; S2 allocates a missing creator target before
    dispatch so a bundle can fill it, and the unmatched column is an all-null `null` column on
    both routes. Any change to that type is a reviewed change."""
    out = _run(route, ws.plan([("tgt", ws.derived('concat(g, "!")', when="flag == 'zz'"))]))
    assert out.column_names == ["flag", "g", "tgt"]
    assert out.schema.field("tgt").type == pa.null()
    assert out.column("tgt").to_pylist() == [None] * 4


def _main_stitch(df: pd.DataFrame, mask: pd.Series, sub: pd.DataFrame, outputs: tuple[str, ...]):
    """Frozen copy of main's stitch (`_when_gate.py` at `8ee461e0f`)."""
    for out_col in dict.fromkeys(outputs):
        if out_col not in sub.columns:
            continue
        df.loc[mask, out_col] = sub[out_col]
    return df


class _Returns:
    """A handler that returns the selected rows with its own `new` column and no `declared`."""

    def __init__(self, new: Any) -> None:
        self.new = new

    def run(self, df: pd.DataFrame, column: str, plan: Any, ctx: Any) -> tuple[pd.DataFrame, list]:
        df[column] = ["X"] * len(df)
        df["new"] = self.new[: len(df)]
        return df, []


def _ctx() -> Any:
    return SimpleNamespace(
        row_errors=[],
        current_table="t",
        source_snapshot_columns={},
        group_anchor_snapshots={},
    )


@pytest.mark.parametrize(
    "new",
    [["n0", "n1", "n2", "n3"], [1, 2, 3, 4], [1.5, 2.5, 3.5, 4.5], [True, False, True, True]],
    ids=["strings", "ints", "floats", "bools"],
)
def test_returned_new_column_and_unreturned_declared_output_match_main(new: list[Any]) -> None:
    frame = pd.DataFrame({"flag": ["y", "n", "y", "n"], "col": ["a", "b", "c", "d"]})
    seed = ws.seed("redact", when="flag == 'y'")
    outputs = ("col", "new", "declared")
    got, _ = run_with_when_gate(_Returns(new), frame.copy(), "col", seed, _ctx(), outputs)
    mask = frame["flag"] == "y"
    sub = frame.loc[mask].copy()
    sub["col"] = ["X"] * len(sub)
    sub["new"] = new[: len(sub)]
    want = _main_stitch(frame.copy(), mask, sub, ("col", "new", "declared"))
    pd.testing.assert_frame_equal(got, want)
    assert list(got.columns) == ["flag", "col", "new"]  # `declared` is skipped, never created
    assert np.array_equal(got["col"].to_numpy(), ["X", "b", "X", "d"])
