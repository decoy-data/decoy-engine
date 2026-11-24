"""PM-1a: a check that fails on one table reports the class name and fixed text only, and the
other tables are still checked.

A cell that cannot be read as text makes the decode error name its bytes, so that text must not
reach a finding, the report or the log. A malformed transform makes only its own table an unknown
writer. Bytes read as text by one rule on every path, so a column Arrow will not take (bytes
mixed with an int) is not read as Python's `b'...'` or `<memory at ...>` form, which no detector
matches. The same holds for every bytes dtype: Arrow binary of any width and a categorical of bytes.
"""

from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.internal.cell_text import UnreadableCellError, column_text, key_text
from decoy_engine.profiling import profile_columns
from decoy_engine.verification.postmask import post_scan_verdict, run_post_mask
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
    findings = check_residual_pii(frames, config, source_frames=frames)
    report = run_post_mask(frames, frames, config=config)
    assert [row[:2] for row in _rows(findings)] == [("u", "email")]
    assert [(r["table"], r["column"], r["severity"]) for r in report["residual_pii"]] == _rows(
        findings
    )


_BYTE_EMAILS = [b"ann@realmail.com", b"bob@realmail.com", b"cat@realmail.com"]
_ONE_TABLE = {"version": 2, "tables": [{"name": "t", "columns": []}]}
_FAIL = "residual_pii check raised UnreadableCellError (see job log for details)"
# Every email is 19 bytes, so the same cells fit a fixed-width binary column too.
_WIDE_EMAILS = [f"user{i}@realmail.com".encode() for i in range(10, 100)]
_ARROW_BINARY = {
    "binary": pa.binary(),
    "large_binary": pa.large_binary(),
    "binary_view": pa.binary_view(),
}


def _blocks_as_email_on_every_path(frames: dict[str, pd.DataFrame]) -> None:
    frame = check_residual_pii(frames, _ONE_TABLE, source_frames=frames)
    report = run_post_mask(frames, frames, config=_ONE_TABLE)
    assert _rows(frame) == [("t", "email", "fail")]
    assert [(r["table"], r["column"], r["severity"]) for r in report["residual_pii"]] == [
        ("t", "email", "fail")
    ]
    assert post_scan_verdict(report).blocking is True


def _is_an_error_on_every_path(frames: dict[str, pd.DataFrame], caplog) -> None:
    caplog.set_level(logging.DEBUG)
    frames = {**frames, "u": pd.DataFrame({"email": _EMAILS})}
    frame = check_residual_pii(frames, _CONFIG, source_frames=frames)
    report = run_post_mask(frames, frames, config=_CONFIG)
    assert [(f.severity, f.message) for f in frame if f.table == "t"] == [("error", _FAIL)]
    assert [(r["severity"], r["message"]) for r in report["residual_pii"] if r["table"] == "t"] == [
        ("error", _FAIL)
    ]
    assert any(r["table"] == "u" and r["column"] == "email" for r in report["residual_pii"])
    assert post_scan_verdict(report).blocking is True
    texts = [json.dumps(report, default=str), caplog.text]
    assert [_leaks(text) for text in texts] == [[], []]


@pytest.mark.parametrize("kind", [bytes, memoryview])
def test_a_byte_encoded_email_mixed_with_an_int_blocks_on_every_path(kind):
    """Arrow will not take bytes with an int, so the runner reads the column as text."""
    _blocks_as_email_on_every_path({"t": pd.DataFrame({"email": [*map(kind, _BYTE_EMAILS), 7]})})


def test_a_column_of_only_memoryview_emails_blocks_on_every_path():
    """Arrow takes these as binary, so the runner reads them on its native route."""
    _blocks_as_email_on_every_path({"t": pd.DataFrame({"email": [*map(memoryview, _BYTE_EMAILS)]})})


_ROUTES = {
    "object bytes": pd.Series([b"a@x.com", None, 7]),
    "object bytearray": pd.Series([bytearray(b"a@x.com"), None, 7]),
    "object memoryview": pd.Series([memoryview(b"a@x.com"), None, 7]),
    "arrow binary": pd.Series([b"a@x.com", None], dtype=pd.ArrowDtype(pa.binary())),
    "arrow large_binary": pd.Series([b"a@x.com", None], dtype=pd.ArrowDtype(pa.large_binary())),
    "arrow binary_view": pd.Series([b"a@x.com", None], dtype=pd.ArrowDtype(pa.binary_view())),
    "arrow fixed binary": pd.Series([b"a@x.com", None], dtype=pd.ArrowDtype(pa.binary(7))),
    "numpy bytes": pd.Series(np.array([b"a@x.com"], dtype="S7")),
    "categorical bytes": pd.Series([b"a@x.com", None], dtype="category"),
    "arrow string": pd.Series(["a@x.com", None], dtype=pd.ArrowDtype(pa.string())),
    "string": pd.Series(["a@x.com", None], dtype="string"),
}
_ROUTE_TEXT = {
    "object bytes": ["a@x.com", "7"],
    "object bytearray": ["a@x.com", "7"],
    "object memoryview": ["a@x.com", "7"],
}


@pytest.mark.parametrize("route", _ROUTES)
def test_every_bytes_dtype_reads_as_its_utf8_text(route):
    assert column_text(_ROUTES[route]).tolist() == _ROUTE_TEXT.get(route, ["a@x.com"])


def test_numbers_and_dates_keep_their_pandas_text():
    assert column_text(pd.Series([1.5, None])).tolist() == ["1.5"]
    assert column_text(pd.Series(pd.to_datetime(["2020-01-01"]))).tolist() == ["2020-01-01"]
    assert key_text(pd.Series([10001.0, 10001, None, memoryview(b"a@x.com")])) == [
        "10001",
        "10001",
        None,
        "a@x.com",
    ]


@pytest.mark.parametrize("arrow", [*_ARROW_BINARY.values(), pa.binary(19)], ids=str)
def test_an_arrow_binary_email_column_blocks_on_every_path(arrow):
    emails = pd.Series(_WIDE_EMAILS, dtype=pd.ArrowDtype(arrow))
    _blocks_as_email_on_every_path({"t": pd.DataFrame({"email": emails})})


def test_a_categorical_of_byte_emails_blocks_on_every_path():
    emails = pd.Series(_BYTE_EMAILS * 3, dtype="category")
    _blocks_as_email_on_every_path({"t": pd.DataFrame({"email": emails})})


@pytest.mark.parametrize("arrow", [*_ARROW_BINARY.values(), pa.binary(9)], ids=str)
def test_an_undecodable_arrow_binary_cell_is_an_error_on_every_path(arrow, caplog):
    blob = pd.Series([_MARKED, None, _MARKED], dtype=pd.ArrowDtype(arrow))
    _is_an_error_on_every_path({"t": pd.DataFrame({"blob": blob})}, caplog)


def test_an_undecodable_categorical_cell_is_an_error_on_every_path(caplog):
    blob = pd.Series([_MARKED, _MARKED], dtype="category")
    _is_an_error_on_every_path({"t": pd.DataFrame({"blob": blob})}, caplog)


@pytest.mark.parametrize(
    "blob",
    [
        pd.Series([_MARKED] * 5, dtype=pd.ArrowDtype(pa.binary())),
        pd.Series([_MARKED] * 5, dtype=pd.ArrowDtype(pa.large_binary())),
        pd.Series([memoryview(_MARKED)] * 4 + [1]),
        pd.Series([_MARKED] * 5, dtype="category"),
    ],
    ids=["binary", "large_binary", "memoryview", "categorical"],
)
def test_profile_columns_raises_fixed_text_for_an_undecodable_cell(blob):
    with pytest.raises(UnreadableCellError) as raised:
        profile_columns(pd.DataFrame({"blob": blob}), "t")
    assert str(raised.value) == "a cell could not be read as text"
    assert _leaks(repr(raised.value)) == []


@pytest.mark.parametrize("kind", [bytes, memoryview])
def test_an_undecodable_cell_mixed_with_an_int_is_an_error_on_every_path(kind, caplog):
    _is_an_error_on_every_path({"t": pd.DataFrame({"blob": [kind(_MARKED), 7]})}, caplog)
