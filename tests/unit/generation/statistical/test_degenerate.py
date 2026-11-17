"""G7, G7b, G7c: one degenerate-snapshot rule for the sampler, window admission and compile.

A snapshot that `decoy run` would refuse as degenerate must be refused by `decoy validate`
(the compile check) with the same code, and a negative or non-finite weight or count is refused
everywhere, not only a zero or negative total.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from decoy_engine.generation._window_admission import (
    GenerationAdmissionError,
    classify_window_table,
)
from decoy_engine.generation.statistical import (
    StatisticalSpecError,
    check_degenerate,
    sample_column,
    spec_from_dict,
)
from decoy_engine.plan._checks import check_statistical_columns
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.quality.snapshot import compute_distribution_snapshot

CODE = "statistical_stats_degenerate"
DECODER_CODE = "statistical_snapshot_schema_mismatch"
NAN = float("nan")
INF = float("inf")


def _spec(kind: str, stats: dict[str, Any], **kw: Any) -> Any:
    base: dict[str, Any] = {
        "column": "c",
        "source_column": "c",
        "kind": kind,
        "dtype": "float64",
        "stats": stats,
        "other_mode": "redistribute",
        "condition_on": None,
        "joint": None,
        "parent_first": True,
    }
    return spec_from_dict({**base, **kw})


def _numeric(edges: list[Any], counts: list[Any]) -> Any:
    return _spec("numeric", {"bin_edges": edges, "bin_counts": counts})


def _cat(top: list[tuple[str, Any]], other: Any = 0, **kw: Any) -> Any:
    values = [{"value": v, "count": c} for v, c in top]
    stats = {"top_values": values, "other_count": other}
    return _spec("categorical", stats, dtype="object", **kw)


def _years(bins: list[tuple[int, Any]], lo: str = "2000-01-01", hi: str = "2005-01-01") -> Any:
    stats = {
        "year_bins": [{"year": y, "count": c} for y, c in bins],
        "min": lo,
        "max": hi,
    }
    return _spec("datetime", stats, dtype="datetime64[ns]")


def _free(edges: list[Any], counts: list[Any]) -> Any:
    return _spec(
        "freetext",
        {"length_bin_edges": edges, "length_bin_counts": counts},
        dtype="object",
    )


def _conditional(rows: dict[str, list[tuple[str, Any]]]) -> Any:
    cells = [{"key": [p, c], "count": n} for p, kids in rows.items() for c, n in kids]
    return _spec(
        "categorical",
        {"top_values": [{"value": "x", "count": 5}]},
        dtype="object",
        condition_on="p",
        joint={"columns": ["p", "c"], "cells": cells},
    )


# One entry per rule. The id names the rule, so a mutation that deletes it names the case.
CASES: dict[str, Any] = {
    "numeric-too-few-edges": _numeric([0.0], []),
    "numeric-counts-length": _numeric([0, 1, 2], [1]),
    "numeric-zero-total": _numeric([0, 1, 2], [0, 0]),
    "numeric-negative-count": _numeric([0, 1, 2], [5, -1]),
    "numeric-nan-count": _numeric([0, 1, 2], [5, NAN]),
    "numeric-inf-total": _numeric([0, 1, 2], [1e308, 1e308]),
    "categorical-empty": _cat([]),
    "categorical-zero-total": _cat([("a", 0), ("b", 0)]),
    "categorical-negative-weight": _cat([("a", 10), ("b", -1)]),
    "categorical-nan-weight": _cat([("a", 10), ("b", NAN)]),
    "categorical-inf-total": _cat([("a", 1e308), ("b", 1e308)]),
    "categorical-negative-other": _cat([("a", 10)], -3),
    "categorical-nan-other": _cat([("a", 10)], NAN),
    "categorical-inf-other": _cat([("a", 10)], INF),
    "categorical-negative-other-emit": _cat([("a", 10)], -3, other_mode="emit"),
    "conditional-zero-row": _conditional({"u": [("a", 0)], "v": [("a", 3)]}),
    "conditional-negative-weight": _conditional({"u": [("a", 4), ("b", -1)]}),
    "datetime-empty": _years([]),
    "datetime-zero-total": _years([(2001, 0)]),
    "datetime-negative-count": _years([(2001, 5), (2002, -1)]),
    "datetime-nan-count": _years([(2001, 5), (2002, NAN)]),
    "datetime-inverted-range": _years([(2001, 5)], lo="2005-01-01", hi="2000-01-01"),
    "freetext-negative-edge": _free([-5, 10, 20], [4, 4]),
    "freetext-descending-edge": _free([0, 100, 10], [4, 4]),
    "freetext-too-few-edges": _free([5.0], []),
    "freetext-zero-total": _free([0, 10], [0]),
    "freetext-negative-count": _free([0, 10, 20], [4, -1]),
    "freetext-nan-count": _free([0, 10, 20], [4, NAN]),
}
IDS = list(CASES)


def _admission(spec: Any) -> Any:
    cfg = {
        "tables": [
            {
                "name": "t",
                "row_count": 10,
                "generate_columns": [{"name": "c", "type": "statistical"}],
            }
        ]
    }
    return classify_window_table(cfg, "t", statistical_specs={("t", "c"): spec})


@pytest.mark.parametrize("case", IDS)
def test_predicate_refuses(case: str) -> None:
    with pytest.raises(StatisticalSpecError) as exc:
        check_degenerate(CASES[case])
    assert exc.value.code == CODE


@pytest.mark.parametrize("case", IDS)
def test_sampler_refuses_through_the_predicate(case: str) -> None:
    with pytest.raises(StatisticalSpecError) as exc:
        sample_column(CASES[case], 3, col_seed=1, parent_values=["u", "v", "w"])
    assert exc.value.code == CODE


@pytest.mark.parametrize("case", IDS)
def test_window_admission_refuses_with_the_same_code(case: str) -> None:
    with pytest.raises(GenerationAdmissionError) as exc:
        _admission(CASES[case])
    assert exc.value.code == CODE


def test_a_usable_snapshot_passes_every_caller() -> None:
    good = [
        _numeric([0, 1, 2], [3, 0]),
        _cat([("a", 3), ("b", 0)]),
        _years([(2001, 3), (2002, 0)]),
        _free([0, 10, 20], [3, 0]),
    ]
    for spec in good:
        check_degenerate(spec)
        assert _admission(spec).is_class_a
    check_degenerate(_conditional({"u": [("a", 3), ("b", 0)]}))


def test_empty_kind_is_not_degenerate() -> None:
    spec = _spec("empty", {})
    check_degenerate(spec)
    assert sample_column(spec, 2, col_seed=1) == [None, None]


def test_negative_weight_with_positive_sum_is_refused_not_sampled() -> None:
    """G7b: this sampled at run before, because only `sum(weights) <= 0` was checked."""
    spec = _cat([("a", 10), ("b", -1)])
    assert sum(w["count"] for w in spec.stats["top_values"]) > 0
    with pytest.raises(StatisticalSpecError) as exc:
        sample_column(spec, 5, col_seed=3)
    assert exc.value.code == CODE
    assert "b" not in exc.value.message and "10" not in exc.value.message


def test_nan_weight_is_refused() -> None:
    spec = _cat([("a", 10), ("b", NAN)])
    assert math.isnan(spec.stats["top_values"][1]["count"])
    with pytest.raises(StatisticalSpecError) as exc:
        sample_column(spec, 5, col_seed=3)
    assert exc.value.code == CODE


# ---- compile (what `decoy validate` runs) ----------------------------------------------------


def _snapshot_file(tmp_path: Path, column: str, stats: dict[str, Any]) -> str:
    df = pd.DataFrame(
        {
            "num": [float(i) for i in range(40)],
            "cat": ["a", "b", "c", "d"] * 10,
            "when": pd.date_range("2001-01-01", periods=40, freq="40D"),
            "txt": [("word " * (1 + i % 5)).strip() for i in range(40)],
        }
    )
    snap = compute_distribution_snapshot(df)
    snap["columns"][column]["stats"].update(stats)
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snap), encoding="utf-8")
    return str(path)


def _config(snapshot: str, column: str) -> dict[str, Any]:
    col = {"name": column, "type": "statistical", "snapshot_file": snapshot}
    if column == "cat":
        col["allow_real_categories"] = True
    return {
        "global_settings": {"seed": 1},
        "tables": [{"name": "t", "row_count": 10, "generate_columns": [col]}],
    }


COMPILE_CASES = {
    "empty label set": ("cat", {"top_values": [], "other_count": 0}),
    "zero labels": (
        "cat",
        {"top_values": [{"value": "a", "count": 0}, {"value": "b", "count": 0}]},
    ),
    "negative weight": (
        "cat",
        {"top_values": [{"value": "a", "count": 30}, {"value": "b", "count": -2}]},
    ),
    "numeric negative count": ("num", {"bin_counts": [30, -2]}),
    "datetime empty years": ("when", {"year_bins": []}),
    "datetime inverted range": ("when", {"min": "2005-01-01", "max": "2000-01-01"}),
    "datetime negative count": (
        "when",
        {"year_bins": [{"year": 2001, "count": 30}, {"year": 2002, "count": -2}]},
    ),
}


@pytest.mark.parametrize("name", list(COMPILE_CASES))
def test_compile_refuses_what_run_refuses(tmp_path: Path, name: str) -> None:
    """G7: validate (compile) gives the code the sampler gives, at the column's path."""
    column, stats = COMPILE_CASES[name]
    if column == "num":
        stats = {"bin_edges": [0.0, 20.0, 39.0], **stats}
    path = _snapshot_file(tmp_path, column, stats)
    with pytest.raises(PlanCompileError) as exc:
        check_statistical_columns(_config(path, column))
    # The v2 datetime decoder refuses a negative bucket count while the snapshot loads, with its own
    # code, before the shared rule runs; every other case reaches the shared rule.
    expected = DECODER_CODE if name == "datetime negative count" else CODE
    assert exc.value.code == expected
    assert exc.value.path == f"tables.t.generate_columns.{column}"


def test_compile_accepts_a_real_snapshot(tmp_path: Path) -> None:
    path = _snapshot_file(tmp_path, "cat", {})
    assert len(check_statistical_columns(_config(path, "cat"))) == 1


@pytest.mark.parametrize("case", IDS)
def test_refusal_text_carries_no_snapshot_number(case: str) -> None:
    with pytest.raises(StatisticalSpecError) as exc:
        check_degenerate(CASES[case])
    assert not any(ch.isdigit() for ch in exc.value.message.replace("'c'", ""))


def test_flag_token_that_is_not_canonical_is_a_coded_admission_refusal() -> None:
    """A `flag` carrier token must be "true" or "false"; admission maps the sampler's coded
    error to its own, with the `top_values` property."""
    spec = _spec(
        "categorical",
        {"top_values": [{"value": "True", "count": 5}], "other_count": 0},
        dtype="bool",
        carrier="flag",
    )
    with pytest.raises(GenerationAdmissionError) as exc:
        _admission(spec)
    assert exc.value.code == "statistical_flag_token_invalid"
    assert exc.value.prop == "top_values"
