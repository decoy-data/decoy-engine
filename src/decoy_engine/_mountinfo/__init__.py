"""The one parser of `/proc/self/mountinfo` records (proc(5)).

A foundation leaf: standard library only, so the cgroup probe in `execution.pipeline` and the
mount-aware tree removal in `fileaccess` both read it without one importing the other. A
sub-package because the engine root is at its fan-out cap.

A record is one line ended by `\\n` and nothing else: the kernel escapes space, tab, newline and
backslash in a path field as `\\ooo`, so no other character (U+2028 and U+0085 included) ends a
record. `str.splitlines` and `str.split()` treat those as boundaries and would cut a valid path,
so this module splits on `"\\n"` and `" "` only.

Record layout: mount id, parent id, `major:minor`, root, mount point, mount options, zero or
more optional fields, the separator `-`, then file system type, source and super options. The
source may be empty, which is one more reason to split on single spaces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["MountRecord", "parse_record", "records", "unescape"]

_OCTAL = re.compile(r"\\([0-7]{3})")
_SEPARATOR = " - "


@dataclass(frozen=True)
class MountRecord:
    """One parsed record; its path fields are unescaped."""

    root: str
    mountpoint: str
    fstype: str
    super_options: frozenset[str]


def unescape(field: str) -> str:
    """Undo the kernel's `\\ooo` octal escapes in a path field; any other backslash stays."""
    return _OCTAL.sub(lambda found: chr(int(found.group(1), 8)), field)


def records(text: str) -> list[str]:
    """The records of a mountinfo table: split on `"\\n"` only, the final empty piece dropped."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def parse_record(line: str) -> MountRecord | None:
    """One record, or None when it does not have the proc(5) shape. The caller decides what None
    means: the cgroup probe skips the record, tree removal refuses to go on."""
    left, separator, right = line.partition(_SEPARATOR)
    left_fields = left.split(" ")
    right_fields = right.split(" ")
    if not separator or len(left_fields) < 6 or len(right_fields) < 3:
        return None
    return MountRecord(
        root=unescape(left_fields[3]),
        mountpoint=unescape(left_fields[4]),
        fstype=right_fields[0],
        super_options=frozenset(right_fields[2].split(",")),
    )
