"""DI-1b: the distribution section of the post-scan report, built by the runner (row 31).

`run_post_mask` and `run_post_mask_tables` take a `DistributionInput`; without one the report has no
section and the column facts tally no output values. All values are made up.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.verification.postmask import runner
from decoy_engine.verification.postmask._column_facts import column_facts, value_facts
from decoy_engine.verification.postmask._stream_input import from_table
from decoy_engine.verification.postmask.distribution import (
    FACTS,
    DistributionFinding,
    DistributionInput,
    warn_only,
)
from decoy_engine.verification.postmask.runner import run_post_mask, run_post_mask_tables

CANARY = "CANARY-di1b-report-77"
ALL = frozenset(FACTS)
LIMIT = "128MB"
CONFIG: dict[str, Any] = {"tables": [{"name": "t", "columns": []}]}


def _source(n: int = 20) -> pa.Table:
    return pa.table(
        {
            "x": pa.array([float(i) for i in range(n)], pa.float64()),
            "s": pa.array([f"{CANARY}-{i}" for i in range(n)], pa.string()),
        }
    )


def _plan(source: pa.Table, **kwargs: Any) -> DistributionInput:
    return DistributionInput(
        tolerance_pct=5.0,
        columns={"t": {"x": ALL, "s": frozenset({"row_count", "null_rate"})}},
        sources={"t": from_table("t", source)},
        quarantined={},
        **kwargs,
    )


def _frames(table: pa.Table) -> dict[str, pd.DataFrame]:
    return {"t": table.to_pandas()}


def test_the_section_is_one_value_free_row_per_checked_fact() -> None:
    src = _source()
    report = run_post_mask(_frames(src), _frames(src), config=CONFIG, distribution=_plan(src))
    rows = report["distribution"]
    assert [(r["column"], r["fact"]) for r in rows] == [
        (None, "row_count"),
        ("x", "null_rate"),
        ("x", "distinct_ratio"),
        ("x", "mean"),
        ("x", "std"),
        ("s", "null_rate"),
    ]
    assert {r["severity"] for r in rows} == {"info"}
    assert all(set(r) == {"table", "column", "fact", "severity", "delta_pct"} for r in rows)
    text = json.dumps(report, allow_nan=False)
    assert CANARY not in text
    assert json.loads(text)["distribution"] == rows


def test_a_moved_fact_is_a_warning_row_and_counts_as_a_warning() -> None:
    src = _source()
    out = src.set_column(0, "x", pa.array([i * 1.5 for i in range(20)], pa.float64()))
    report = run_post_mask(_frames(src), _frames(out), config=CONFIG, distribution=_plan(src))
    by_fact = {(r["column"], r["fact"]): r for r in report["distribution"]}
    assert by_fact[("x", "mean")]["severity"] == "warning"
    assert by_fact[("x", "mean")]["delta_pct"] is not None
    assert by_fact[("x", "std")]["severity"] == "warning"
    assert by_fact[("x", "null_rate")]["severity"] == "info"
    assert report["warning_count"] >= 2
    # The control: the same two frames judged without the check carry no such warning.
    plain = run_post_mask(_frames(src), _frames(out), config=CONFIG)
    assert report["warning_count"] - plain["warning_count"] >= 2


def test_without_a_distribution_input_the_report_has_no_section() -> None:
    src = _source()
    report = run_post_mask(_frames(src), _frames(src), config=CONFIG)
    assert "distribution" not in report


def test_the_staged_runner_builds_the_same_section(tmp_path: Path) -> None:
    src = _source()
    out = src.set_column(0, "x", pa.array([i * 1.5 for i in range(20)], pa.float64()))
    report = run_post_mask_tables(
        {"t": from_table("t", src)},
        {"t": from_table("t", out)},
        config=CONFIG,
        keys=(),
        scratch=tmp_path,
        memory_limit=LIMIT,
        distribution=_plan(src),
    )
    by_fact = {(r["column"], r["fact"]): r["severity"] for r in report["distribution"]}
    assert by_fact[("x", "mean")] == "warning" and by_fact[("x", "null_rate")] == "info"


def test_an_unreadable_source_is_a_warning_row_and_the_other_tables_are_still_checked() -> None:
    src = _source()

    def broken(columns: Any, batch_rows: int) -> Any:
        raise RuntimeError(f"cannot read {CANARY}")

    bad = replace(from_table("bad", src), read=broken)
    plan = DistributionInput(
        tolerance_pct=5.0,
        columns={"bad": {"x": ALL}, "t": {"x": ALL}},
        sources={"bad": bad, "t": from_table("t", src)},
        quarantined={},
    )
    frames = {"bad": src.to_pandas(), "t": src.to_pandas()}
    report = run_post_mask(frames, frames, config=CONFIG, distribution=plan)
    rows = report["distribution"]
    bad_rows = [r for r in rows if r["table"] == "bad"]
    assert [(r["fact"], r["severity"]) for r in bad_rows] == [("row_count", "warning")]
    assert {r["severity"] for r in rows if r["table"] == "t"} == {"info"}
    assert CANARY not in json.dumps(report)


def test_an_error_row_is_written_as_a_warning_while_the_check_only_warns() -> None:
    rows = (
        DistributionFinding("t", "x", "mean", "error", None),
        DistributionFinding("t", "x", "std", "info", 0.0),
    )
    assert [r.severity for r in warn_only(rows)] == ["warning", "info"]


# ----- output values are tallied only for the columns a check reads --------------------------------


def test_an_unconfigured_run_tallies_no_output_values(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []
    real = runner.column_facts

    def spy(*args: Any, **kwargs: Any) -> Any:
        facts = real(*args, **kwargs)
        seen.append(facts)
        return facts

    monkeypatch.setattr(runner, "column_facts", spy)
    src = _source()
    run_post_mask(_frames(src), _frames(src), config=CONFIG)
    assert seen and all(f.output_values is None for facts in seen for f in facts.values())
    seen.clear()
    run_post_mask(_frames(src), _frames(src), config=CONFIG, distribution=_plan(src))
    values = {c: f.output_values for facts in seen for c, f in facts.items()}
    assert values["x"] is not None and values["s"] is not None


def test_only_the_named_columns_are_tallied(tmp_path: Path) -> None:
    table = from_table("t", _source())
    facts = column_facts(
        None, table, ["x", "s"], scratch=tmp_path, memory_limit=LIMIT, value_columns=["x"]
    )
    assert facts["x"].output_values is not None
    assert facts["s"].output_values is None
    every = column_facts(None, table, ["x", "s"], scratch=tmp_path, memory_limit=LIMIT)
    assert every["x"].output_values is not None and every["s"].output_values is not None


# ----- a table that drops rows on read ------------------------------------------------------------


def _short(table: pa.Table, rows: int, *, drops: bool) -> Any:
    base = from_table("t", table)

    def read(columns: Any, batch_rows: int) -> Any:
        return from_table("t", table.slice(0, rows)).read(columns, batch_rows)

    return replace(base, read=read, drops_rows=drops)


def test_a_table_that_drops_rows_may_give_fewer_rows_than_it_declares() -> None:
    got = value_facts(_short(_source(20), 17, drops=True), ["x"])
    assert got["x"].rows == 17


def test_a_plain_table_that_gives_fewer_rows_is_still_refused() -> None:
    with pytest.raises(ValueError, match="declares"):
        value_facts(_short(_source(20), 17, drops=False), ["x"])


def test_a_table_that_drops_rows_may_not_give_more_than_it_declares() -> None:
    base = from_table("t", _source(20))
    longer = from_table("t", pa.concat_tables([_source(20), _source(3)]))
    over = replace(base, read=longer.read, drops_rows=True)
    with pytest.raises(ValueError, match="declares"):
        value_facts(over, ["x"])


def test_a_cast_table_without_a_quarantine_column_keeps_the_exact_length_check() -> None:
    from decoy_engine.verification.postmask._stream_input import with_cast

    table = _short(_source(20), 17, drops=False)
    cast = {
        True: with_cast(table, needs=(), schema=table.schema, cast=lambda t, o: t, drops_rows=True),
        False: with_cast(table, needs=(), schema=table.schema, cast=lambda t, o: t),
    }
    assert value_facts(cast[True], ["x"])["x"].rows == 17
    with pytest.raises(ValueError, match="declares"):
        value_facts(cast[False], ["x"])
