"""V2, V3: a session report does not depend on how rows are chunked or which table comes first.

The same rows are fed whole, one row at a time, in chunks of 7 and of 4096, with tables in
generated orders (parent first, child first, interleaved batch by batch). Every validator,
including ``leak_check`` with a source and the three keyed validators, must give one report.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from decoy_engine.validators import FINDING_INDEX_CAP, ValidationReport, ValidationSession, validate
from tests.unit.validators._fold_cases import Case, build_cases

CASES = build_cases()
CHUNKS = (1, 7, 4096, None)  # None: the whole table in one span


def _same(report: ValidationReport) -> ValidationReport:
    return dataclasses.replace(report, elapsed_ms=0.0)


def _spans(table: pa.Table, chunk: int | None) -> list[pa.Table]:
    if chunk is None or table.num_rows <= chunk:
        return [table]
    return [table.slice(i, chunk) for i in range(0, table.num_rows, chunk)]


def feed(case: Case, chunk: int | None, order: list[str], interleave: bool) -> ValidationReport:
    """Feed the case's outputs batch by batch and return the finished report."""
    session = ValidationSession(case.config, sources=case.sources)
    spans = {name: _spans(case.outputs[name], chunk) for name in order}
    if interleave:
        for position in range(max(len(s) for s in spans.values())):
            for name in order:
                if position < len(spans[name]):
                    session.observe_published(name, spans[name][position])
    else:
        for name in order:
            for span in spans[name]:
                session.observe_published(name, span)
    return session.finish()


@settings(derandomize=True, max_examples=120, deadline=None)
@given(
    name=st.sampled_from(sorted(CASES)),
    chunk=st.sampled_from(CHUNKS),
    interleave=st.booleans(),
    data=st.data(),
)
def test_chunk_size_and_table_order_do_not_change_the_report(
    name: str, chunk: int | None, interleave: bool, data: st.DataObject
) -> None:
    case = CASES[name]
    order = data.draw(st.permutations(sorted(case.outputs)))
    whole = validate(case.outputs, case.config, sources=case.sources)
    assert _same(feed(case, chunk, order, interleave)) == _same(whole)


# ---------------------------------------------------------------------------
# parent_window_respected: one date format per column, whatever the chunking
# ---------------------------------------------------------------------------

_DATES = [
    "2020-03-05",
    "2021-03-05",
    "03/05/2020",
    "12/25/2019",
    "2020-03-05T10:00:00",
    "2020-06-01 08:30:00",
    "not a date",
    "",
    "NaT",
    "nan",
    None,
]


def _window_case(child_dates: list[str | None]) -> Case:
    parent = pa.table({"id": [1], "start": ["2020-01-01"], "end": ["2020-12-31"]})
    child = pa.table({"pid": [1] * len(child_dates), "d": pa.array(child_dates, pa.string())})
    entry = {
        "name": "parent_window_respected",
        "params": {
            "child_table": "child",
            "child_column": "d",
            "parent_table": "parent",
            "window_start_column": "start",
            "window_end_column": "end",
        },
    }
    config = {
        "validators": [entry],
        "tables": [],
        "relationships": [
            {
                "parent": {"table": "parent", "columns": ["id"]},
                "children": [{"table": "child", "columns": ["pid"]}],
            }
        ],
    }
    return Case({"parent": parent, "child": child}, config, {})


def _whole_column_verdict(child_dates: list[str | None]) -> tuple[int, ...]:
    """The full-frame verdict: pandas parses the whole column at once, as the old code did."""
    parsed = pd.to_datetime(pd.Series(child_dates), errors="coerce")
    start, end = pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31")
    failing = []
    for i, raw in enumerate(child_dates):
        if raw is None:
            continue
        if pd.isna(parsed.iloc[i]) or not (start <= parsed.iloc[i] <= end):
            failing.append(i)
    return tuple(failing)


@settings(derandomize=True, max_examples=150, deadline=None)
@given(
    dates=st.lists(st.sampled_from(_DATES), min_size=1, max_size=40),
    chunk=st.sampled_from((1, 3, 7, 4096, None)),
    child_first=st.booleans(),
)
@pytest.mark.filterwarnings("ignore")
def test_mixed_date_formats_give_the_full_frame_verdict_at_any_chunk_size(
    dates: list[str | None], chunk: int | None, child_first: bool
) -> None:
    case = _window_case(dates)
    order = ["child", "parent"] if child_first else ["parent", "child"]
    report = feed(case, chunk, order, interleave=False)
    got = tuple(i for f in report.findings for i in f.failing_row_indices)
    assert got == _whole_column_verdict(dates)


def test_a_mixed_format_column_split_at_the_first_chunk_keeps_the_first_values_format() -> None:
    # The first non-null value is ISO, so a later "03/05/2020" does not parse, on every chunking.
    dates: list[str | None] = [None, "2020-03-05"] + ["03/05/2020"] * 6
    case = _window_case(dates)
    whole = validate(case.outputs, case.config)
    chunked = feed(case, 7, ["parent", "child"], interleave=False)
    assert _same(chunked) == _same(whole)
    assert whole.findings[0].failing_row_indices == tuple(range(2, 8))


# ---------------------------------------------------------------------------
# parent_window_respected: a child that arrives before its parent keeps every observation
# ---------------------------------------------------------------------------


def _duplicate_key_case(reverse_parents: bool = False) -> Case:
    """Five children of parent 1 and three of parent 2, with null and malformed dates."""
    ids, starts, ends = [1, 2], ["2020-01-01", "2020-02-01"], ["2020-06-30", "2020-02-28"]
    if reverse_parents:
        ids, starts, ends = ids[::-1], starts[::-1], ends[::-1]
    parent = pa.table({"id": ids, "start": starts, "end": ends})
    child = pa.table(
        {
            "pid": [1, 1, 1, 1, 1, 2, 2, 2],
            "d": pa.array(
                [
                    "2021-01-01",  # outside parent 1's window
                    "2020-03-01",  # inside
                    "2020-06-30",  # the upper bound, inside
                    None,  # null: skipped
                    "garbage",  # non-null, unparseable: fails
                    "2020-03-01",  # outside parent 2's window
                    "2020-02-10",  # inside
                    "2019-12-31",  # outside
                ],
                pa.string(),
            ),
        }
    )
    base = _window_case([])
    return Case({"parent": parent, "child": child}, base.config, {})


@pytest.mark.parametrize("reverse_parents", [False, True])
@pytest.mark.parametrize("order", [["parent", "child"], ["child", "parent"]])
@pytest.mark.parametrize("chunk", [1, 3, None])
def test_children_that_share_one_parent_key_each_keep_their_verdict(
    reverse_parents: bool, order: list[str], chunk: int | None
) -> None:
    case = _duplicate_key_case(reverse_parents)
    report = feed(case, chunk, order, interleave=False)
    (finding,) = report.findings
    # A null child date is skipped, a malformed one fails, and no earlier child is lost.
    assert finding.failing_row_count == 4
    assert finding.failing_row_indices == (0, 4, 5, 7)
    assert _same(report) == _same(validate(case.outputs, case.config))


# ---------------------------------------------------------------------------
# V3: an exact count beside a capped list
# ---------------------------------------------------------------------------


def _bad_rows_case(quarantine: bool) -> Case:
    values = ["bad" if i % 6 else "ok1" for i in range(30_000)]
    config: dict[str, Any] = {
        "validators": [
            {"name": "regex_match", "columns": {"t": ["c"]}, "params": {"pattern": "ok."}}
        ]
    }
    if quarantine:
        config["quarantine"] = {
            "enabled": True,
            "output_path": "q.jsonl",
            "triggers": ["validation_fail"],
        }
    return Case({"t": pa.table({"c": values})}, config, {})


def test_the_count_is_exact_and_the_index_list_stops_at_the_cap() -> None:
    case = _bad_rows_case(quarantine=False)
    failing = [i for i in range(30_000) if i % 6]
    assert len(failing) == 25_000 and FINDING_INDEX_CAP == 10_000
    for report in (validate(case.outputs, case.config), feed(case, 4096, ["t"], False)):
        (finding,) = report.findings
        assert finding.failing_row_count == 25_000
        assert finding.failing_row_indices == tuple(failing[:FINDING_INDEX_CAP])
        assert "25000 row(s)" in finding.detail
        assert report.results[0].failing_row_count == 25_000


def test_quarantine_validation_fail_lists_every_failing_row() -> None:
    case = _bad_rows_case(quarantine=True)
    failing = tuple(i for i in range(30_000) if i % 6)
    for report in (validate(case.outputs, case.config), feed(case, 4096, ["t"], False)):
        (finding,) = report.findings
        assert finding.failing_row_count == 25_000
        assert finding.failing_row_indices == failing
