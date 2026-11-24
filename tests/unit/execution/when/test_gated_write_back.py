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

from decoy_engine.execution._errors import StrategyError
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


_WIDE = pa.table(
    {
        "flag": ["y", "n", "y", "n"],
        "g": ["a", "a", "b", "b"],
        "n": [1, 2, 3, 4],
        "f": [1.5, 2.5, 3.5, 4.5],
    }
)


def _run_wide(route: str, plan: Any) -> pa.Table:
    return ROUTES[route](plan, _WIDE, bound=(("g",),))


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_a_zero_match_creator_leaves_the_column_absent_as_main_does(route: str) -> None:
    """Case 5 and L3. A creator whose gate selects no row never writes, so the column is absent,
    exactly as on main (`8ee461e0f`)."""
    out = _run_wide(route, ws.plan([("tgt", ws.derived("n + 1", when="flag == 'zz'"))]))
    assert out.column_names == ["flag", "g", "n", "f"]


@pytest.mark.parametrize("route", sorted(ROUTES))
@pytest.mark.parametrize(
    ("expression", "arrow_type", "values"),
    [
        ("n + 1", pa.float64(), [2.0, None, 4.0, None]),
        ("f * 2", pa.float64(), [3.0, None, 7.0, None]),
        ("n > 2", pa.bool_(), [False, None, True, None]),
    ],
    ids=["int", "float", "bool"],
)
def test_a_partial_gated_creator_keeps_mains_dtype_and_values(
    route: str, expression: str, arrow_type: pa.DataType, values: list[Any]
) -> None:
    """Main's output at `8ee461e0f`: ints widen to float64 with NaN for the unmatched rows."""
    out = _run_wide(route, ws.plan([("tgt", ws.derived(expression, when="flag == 'y'"))]))
    assert out.column_names == ["flag", "g", "n", "f", "tgt"]
    assert out.schema.field("tgt").type == arrow_type
    assert out.column("tgt").to_pylist() == values


_CREATORS = {
    "two": (
        [("zz", ws.derived('concat(g, "!")')), ("aa", ws.derived('concat(g, "?")'))],
        ["aa", "zz"],
    ),
    "three": (
        [
            ("zz", ws.derived('concat(g, "!")')),
            ("mm", ws.derived('concat(g, "#")')),
            ("aa", ws.derived('concat(g, "?")')),
        ],
        ["aa", "mm", "zz"],
    ),
    "chain": (
        [("b2", ws.derived('concat(a2, "?")')), ("a2", ws.derived('concat(g, "!")'))],
        ["a2", "b2"],
    ),
}


@pytest.mark.parametrize("route", sorted(ROUTES))
@pytest.mark.parametrize("case", sorted(_CREATORS))
def test_created_columns_come_out_in_mains_order(route: str, case: str) -> None:
    """A creator's column is made when its node runs, so the order is main's, not allocation order."""
    per_column, created = _CREATORS[case]
    out = _run_wide(route, ws.plan(per_column))
    assert out.column_names == ["flag", "g", "n", "f", *created]


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_a_when_naming_a_created_column_is_a_when_expression_error(route: str) -> None:
    """Main refused it with `when_expression_error`; the snapshot code is for a route that forgot
    a snapshot, not for this."""
    plan = ws.plan(
        [("tgt", ws.derived('concat(g, "!")')), ("g", ws.seed("redact", when="tgt == 'a!'"))]
    )
    with pytest.raises(StrategyError) as info:
        _run(route, plan)
    assert info.value.code == "when_expression_error"


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
