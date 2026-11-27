"""Write a file so a reader sees the old content or the new content, never a partial one.

One choke point for the impact map, the selection record and the hand-back files. The temp file
sits in the destination directory, so `os.replace` stays on one filesystem and is atomic on POSIX
and Windows alike (a rename across filesystems is not)."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def atomic_write_bytes(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, dest)
    except BaseException:
        # A failed write must not leave a stray temp file next to the real one.
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def atomic_write_text(dest: Path, text: str) -> None:
    atomic_write_bytes(dest, text.encode("utf-8"))
