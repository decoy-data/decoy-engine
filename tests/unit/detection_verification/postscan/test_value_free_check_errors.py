"""PM-1a: a check that fails on one table reports the class name and fixed text only, and the
other tables are still checked.

A cell that cannot be read as text makes the decode error name its bytes, so that text must not
reach a finding, the report or the log. A malformed transform makes only its own table an unknown
writer.
"""

from __future__ import annotations

import json
import logging

import pandas as pd

from decoy_engine.plan.column_access import KnownEmpty, Unknown
from decoy_engine.verification.postmask import run_post_mask
from decoy_engine.verification.postmask._column_facts import standalone_writes
from decoy_engine.verification.postmask.residual_pii import check_residual_pii

_EMAILS = [f"user{i}@realmail.com" for i in range(100)]
_MARKED = b"\xffMARK9917"
_CONFIG = {"version": 2, "tables": [{"name": "t", "columns": []}, {"name": "u", "columns": []}]}


def _frames() -> dict[str, pd.DataFrame]:
    return {"t": pd.DataFrame({"blob": [_MARKED] * 3}), "u": pd.DataFrame({"email": _EMAILS})}


def _rows(findings) -> list[tuple[str, str, str]]:
    return [(f.table, f.column, f.severity) for f in findings]


def _leaks(text: str) -> list[str]:
    return [mark for mark in ("MARK9917", "0xff", "\\xff") if mark in text]


def test_an_undecodable_cell_is_reported_by_class_name_only(caplog):
    caplog.set_level(logging.DEBUG)
    frame = check_residual_pii(_frames(), _CONFIG, source_frames=_frames())
    report = run_post_mask(_frames(), _frames(), config=_CONFIG)
    assert ("t", "", "error") in _rows(frame)
    assert any(row[:2] == ("u", "email") for row in _rows(frame))
    assert [f.message for f in frame if f.table == "t"] == [
        "residual_pii check raised UnreadableCellError (see job log for details)"
    ]
    assert [r["message"] for r in report["residual_pii"] if r["table"] == "t"] == [
        "residual_pii check raised UnreadableCellError (see job log for details)"
    ]
    assert any(r["table"] == "u" and r["column"] == "email" for r in report["residual_pii"])
    texts = [json.dumps([f.message for f in frame]), json.dumps(report, default=str), caplog.text]
    assert [_leaks(text) for text in texts] == [[], [], []]


def test_a_malformed_transform_leaves_the_other_tables_checked():
    config = {
        "version": 2,
        "tables": [
            {"name": "t", "columns": [], "transforms": [{"op": []}]},
            {"name": "u", "columns": []},
        ],
    }
    frames = {"t": pd.DataFrame({"x": [1, 2, 3]}), "u": pd.DataFrame({"email": _EMAILS})}
    assert standalone_writes(config, {"t": ["x"], "u": ["email"]}) == {
        "t": Unknown(),
        "u": KnownEmpty(),
    }
    findings = check_residual_pii(frames, config, source_frames=frames)
    assert [row[:2] for row in _rows(findings)] == [("u", "email")]
