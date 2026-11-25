"""The shared mountinfo record parser: records end at `\\n` only and path fields are unescaped."""

from __future__ import annotations

import pytest

from decoy_engine._mountinfo import MountRecord, parse_record, records, unescape
from decoy_engine.execution.pipeline import parse_mountinfo


def _escape(path: str) -> str:
    """The kernel's `show_path` escaping: backslash first, then space, tab and newline."""
    for raw, code in (("\\", "\\134"), (" ", "\\040"), ("\t", "\\011"), ("\n", "\\012")):
        path = path.replace(raw, code)
    return path


def _line(
    mountpoint: str, *, root: str = "/", optional: str = "shared:1", source: str = "/dev/sda1"
) -> str:
    tail = f" {optional}" if optional else ""
    return f"36 35 98:0 {_escape(root)} {_escape(mountpoint)} rw,noatime{tail} - ext4 {source} rw,errors=continue"


@pytest.mark.parametrize(
    "path",
    [
        "/mnt/a b",
        "/mnt/tab\there",
        "/mnt/new\nline",
        "/mnt/back\\slash",
        "/mnt/line\u2028sep",
        "/mnt/next\u0085line",
        "/mnt/no\xa0break",
        "/mnt/form\x0cfeed",
        "/mnt/\\040literal",
    ],
)
def test_a_path_field_round_trips_through_the_kernel_escaping(path: str) -> None:
    table = f"{_line('/')}\n{_line(path)}\n{_line('/proc')}\n"
    parsed = [parse_record(line) for line in records(table)]
    assert [p.mountpoint for p in parsed if p] == ["/", path, "/proc"]
    assert parse_mountinfo(table)[1].mountpoint.as_posix() == path


def test_records_split_on_newline_only() -> None:
    assert records("a\u2028b\x0bc\x1cd\nnext\n") == ["a\u2028b\x0bc\x1cd", "next"]
    assert records("") == []
    assert records("no newline at end") == ["no newline at end"]


def test_an_empty_source_and_no_optional_fields_still_parse() -> None:
    record = parse_record(_line("/srv", root="/sub", optional="", source=""))
    assert record == MountRecord(
        root="/sub",
        mountpoint="/srv",
        fstype="ext4",
        super_options=frozenset({"rw", "errors=continue"}),
    )


def test_several_optional_fields_still_parse() -> None:
    record = parse_record(_line("/srv", optional="shared:2 master:1 propagate_from:3"))
    assert record is not None and record.mountpoint == "/srv"


@pytest.mark.parametrize(
    "line",
    [
        "",
        "garbage",
        "36 35 98:0 / /mnt rw",  # no separator
        "36 35 98:0 / - ext4 /dev/sda1 rw",  # too few fields before the separator
        "36 35 98:0 / /mnt rw - ext4",  # too few after it
    ],
)
def test_a_malformed_record_is_none(line: str) -> None:
    assert parse_record(line) is None


def test_unescape_leaves_a_backslash_that_is_no_octal_escape() -> None:
    assert unescape("\\x41\\9\\04") == "\\x41\\9\\04"
    assert unescape("a\\040b\\134c") == "a b\\c"


def test_the_cgroup_probe_skips_a_malformed_record() -> None:
    table = f"garbage\n{_line('/sys/fs/cgroup')}\n"
    mounts = parse_mountinfo(table)
    assert [m.mountpoint.as_posix() for m in mounts] == ["/sys/fs/cgroup"]
