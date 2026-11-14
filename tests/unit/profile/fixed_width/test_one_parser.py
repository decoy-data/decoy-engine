"""AT-17: the one fixed-width record parser keeps every read rule and stays value-free."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from decoy_engine import fileaccess
from decoy_engine.config._fixed_width import FixedWidthLayout
from decoy_engine.errors import FixedWidthParseError, FixedWidthRecordOverlongError
from decoy_engine.fileaccess import FileRequest, FileRole
from decoy_engine.profile._fixed_width_reader import (
    RecordFailure,
    iter_fixed_width_records,
    read_fixed_width,
)
from decoy_engine.profile._readers import FixedWidthFileSource
from tests.unit.test_v2_fixed_width_source import (
    _SENTINEL,
    _SENTINEL_STEM,
    _assert_sentinel_unreachable,
)

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
    # 3 records of 13 bytes plus 16 blank lines: size // 13 says 4, a count says 3.
    path = _write(tmp_path, b"abcdefghi001\n" + b"\n" * 16 + b"abcdefghi002\nabcdefghi003\n")
    count = FixedWidthFileSource(path, _LAYOUT).row_count()
    assert (count.value, count.exact) == (3, True)


def test_row_count_does_not_cast(tmp_path: Path) -> None:
    path = _write(tmp_path, b"abcdefghiXYZ\nabcdefghi002\n")
    assert FixedWidthFileSource(path, _LAYOUT).row_count().value == 2


def test_row_count_of_an_empty_file(tmp_path: Path) -> None:
    count = FixedWidthFileSource(_write(tmp_path, b""), _LAYOUT).row_count()
    assert (count.value, count.exact) == (0, True)


def test_row_count_fails_closed_on_a_bad_record(tmp_path: Path) -> None:
    path = _write(tmp_path, _GOOD + b"\xff" + _SENTINEL.encode() + b"\n")
    with pytest.raises(FixedWidthParseError) as info:
        FixedWidthFileSource(path, _LAYOUT).row_count()
    _assert_sentinel_unreachable(info.value)


def test_row_count_reports_a_missing_file_before_a_bad_layout(tmp_path: Path) -> None:
    source = FixedWidthFileSource(tmp_path / "nope.dat", {"columns": []})
    with pytest.raises(FileNotFoundError):
        source.row_count()


@pytest.mark.parametrize("make", ["missing", "directory"])
def test_capped_zero_read_still_opens_the_file(tmp_path: Path, make: str) -> None:
    path = tmp_path / "d" if make == "directory" else tmp_path / "nope.dat"
    if make == "directory":
        path.mkdir()
    expected = IsADirectoryError if make == "directory" else FileNotFoundError
    with pytest.raises(expected):
        read_fixed_width(path, _LAYOUT, max_records=0)


# Generator level: a failure yield holds no file content and chains nothing.
_GEN_LAYOUT = FixedWidthLayout.model_validate(
    {
        "columns": [
            {"name": "n", "start": 0, "width": 3, "type": "int"},
            {"name": "s", "start": 3, "width": 9},
        ],
        "exact_record_width": True,
    }
)
_GOOD_LAST_COLUMN = b"123" + _SENTINEL.encode() + b"\n"


_CAST_LAYOUT = FixedWidthLayout.model_validate(
    {
        "columns": [
            {"name": "s", "start": 0, "width": 9},
            {"name": "n", "start": 9, "width": 3, "type": "int"},
        ],
        "exact_record_width": True,
    }
)
_STEM = _SENTINEL_STEM.encode()
# kind -> (layout, good first record, bad second line). The sentinel rides in the good record
# and in the bad line, so a leaked local from either shows up.
_CASES: dict[str, tuple[FixedWidthLayout, bytes, bytes]] = {
    "utf8": (_GEN_LAYOUT, _GOOD_LAST_COLUMN, b"\xff" + _SENTINEL.encode() + b"\n"),
    "short": (_GEN_LAYOUT, _GOOD_LAST_COLUMN, b"123" + _STEM + b"\n"),
    "overlong": (_GEN_LAYOUT, _GOOD_LAST_COLUMN, b"123" + _SENTINEL.encode() + b"EXTRA\n"),
    # the string column comes first, so a failed cast leaves a half-built row holding it
    "cast": (_CAST_LAYOUT, _SENTINEL.encode() + b"123\n", _SENTINEL.encode() + b"abc\n"),
}


def _generator(tmp_path: Path, payload: bytes, layout: FixedWidthLayout) -> Any:
    path = _write(tmp_path, payload)
    handle = fileaccess.current().open_read(FileRequest(FileRole.SOURCE, "read", str(path), "p"))
    return iter_fixed_width_records(handle, layout)


def _failing_generator(tmp_path: Path, kind: str) -> Any:
    layout, good, bad = _CASES[kind]
    gen = _generator(tmp_path, good + bad, layout)
    assert isinstance(next(gen), dict)
    return gen


@pytest.mark.parametrize("kind", sorted(_CASES))
def test_failure_yield_frame_holds_no_sentinel(tmp_path: Path, kind: str) -> None:
    gen = _failing_generator(tmp_path, kind)
    failure = next(gen)
    assert isinstance(failure, RecordFailure)
    assert _SENTINEL_STEM not in failure.message
    assert _SENTINEL_STEM not in repr(gen.gi_frame.f_locals)
    gen.close()


@pytest.mark.parametrize("stage", ["unstarted", "one_record", "exhausted", "after_failure"])
def test_the_file_is_closed_in_every_ending(tmp_path: Path, stage: str) -> None:
    bad = {"after_failure": b"short\n"}.get(stage, b"")
    gen = _generator(tmp_path, _GOOD_LAST_COLUMN + bad, _GEN_LAYOUT)
    fh = gen.gi_frame.f_locals["fh"]
    assert not fh.closed
    if stage == "one_record":
        next(gen)
    elif stage == "exhausted":
        assert len(list(gen)) == 1
    elif stage == "after_failure":
        assert isinstance(list(gen)[-1], RecordFailure)
    gen.close()
    assert fh.closed


def test_throw_at_the_utf8_failure_chains_nothing(tmp_path: Path) -> None:
    gen = _failing_generator(tmp_path, "utf8")
    assert isinstance(next(gen), RecordFailure)
    with pytest.raises(RuntimeError) as info:
        gen.throw(RuntimeError("consumer abort"))
    assert info.value.__context__ is None


def test_framing_mode_skips_casts_but_keeps_framing(tmp_path: Path) -> None:
    path = _write(tmp_path, b"abcdefghiXYZ\nshort\n")
    handle = fileaccess.current().open_read(FileRequest(FileRole.SOURCE, "read", str(path), "p"))
    items = list(iter_fixed_width_records(handle, _GEN_LAYOUT, cast_values=False))
    assert items[0] == {}
    assert isinstance(items[1], RecordFailure) and "shorter" in items[1].message


def test_row_count_of_a_directory_beats_a_bad_layout(tmp_path: Path) -> None:
    with pytest.raises(IsADirectoryError):
        FixedWidthFileSource(tmp_path, {"columns": []}).row_count()
