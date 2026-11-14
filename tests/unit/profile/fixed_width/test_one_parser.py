"""AT-17: the one fixed-width record parser keeps every read rule and stays value-free."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from decoy_engine.errors import FixedWidthParseError, FixedWidthRecordOverlongError
from decoy_engine.profile._fixed_width_reader import read_fixed_width
from decoy_engine.profile._readers import FixedWidthFileSource
from tests.unit.test_v2_fixed_width_source import _SENTINEL, _assert_sentinel_unreachable

_LAYOUT: dict[str, Any] = {
    "columns": [
        {"name": "s", "start": 0, "width": 9},
        {"name": "n", "start": 9, "width": 3, "type": "int"},
    ]
}
_GOOD = _SENTINEL.encode() + b"123\n"


def _write(tmp_path: Path, payload: bytes) -> Path:
    path = tmp_path / "f.dat"
    path.write_bytes(payload)
    return path


def test_blank_lines_and_missing_final_newline(tmp_path: Path) -> None:
    path = _write(tmp_path, b"abcdefghi001\n\n\r\nabcdefghi002")
    df = read_fixed_width(path, _LAYOUT)
    assert df["n"].tolist() == [1, 2]
    assert df["s"].tolist() == ["abcdefghi"] * 2


@pytest.mark.parametrize(
    ("tail", "error"),
    [
        (b"short\n", FixedWidthParseError),  # short record
        (_SENTINEL.encode() + b"abc\n", FixedWidthParseError),  # bad cast
        (b"\xff" + _SENTINEL.encode() + b"\n", FixedWidthParseError),  # bad UTF-8
    ],
)
def test_failure_after_a_good_record_leaks_nothing(
    tmp_path: Path, tail: bytes, error: type
) -> None:
    path = _write(tmp_path, _GOOD + tail)
    with pytest.raises(error) as info:
        read_fixed_width(path, _LAYOUT)
    _assert_sentinel_unreachable(info.value)
    assert "line 2" in str(info.value)


def test_overlong_record_raises_the_overlong_error(tmp_path: Path) -> None:
    layout = {**_LAYOUT, "exact_record_width": True}
    path = _write(tmp_path, _GOOD + _SENTINEL.encode() + b"123456\n")
    with pytest.raises(FixedWidthRecordOverlongError) as info:
        read_fixed_width(path, layout)
    _assert_sentinel_unreachable(info.value)


def test_capped_read_stops_before_a_later_bad_line(tmp_path: Path) -> None:
    path = _write(tmp_path, _GOOD * 2 + b"bad\n")
    assert len(read_fixed_width(path, _LAYOUT, max_records=2)) == 2
    assert len(read_fixed_width(path, _LAYOUT, max_records=0)) == 0


def test_row_count_counts_records_not_bytes(tmp_path: Path) -> None:
    path = _write(tmp_path, b"abcdefghi001\n\n\nabcdefghi002\nabcdefghi003")
    count = FixedWidthFileSource(path, _LAYOUT).row_count()
    assert (count.value, count.exact) == (3, True)


def test_row_count_of_an_empty_file(tmp_path: Path) -> None:
    count = FixedWidthFileSource(_write(tmp_path, b""), _LAYOUT).row_count()
    assert (count.value, count.exact) == (0, True)


def test_row_count_fails_closed_on_a_bad_record(tmp_path: Path) -> None:
    path = _write(tmp_path, _GOOD + b"\xff" + _SENTINEL.encode() + b"\n")
    with pytest.raises(FixedWidthParseError) as info:
        FixedWidthFileSource(path, _LAYOUT).row_count()
    _assert_sentinel_unreachable(info.value)
