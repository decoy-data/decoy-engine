"""The one reader of `os.O_*`: every open flag the engine uses, right on this platform.

Pattern: a single compatibility shim (as `six` and `os` itself do per platform) so no other
module spells a POSIX-only flag. On POSIX each value equals `os.O_*` exactly. On Windows the
POSIX-only flags are 0 and `O_BINARY | O_NOINHERIT` joins every open-mode flag: without
`O_BINARY` the C runtime opens in text mode, which turns 0x0A into CRLF and ends a read at
0x1A, and without `O_NOINHERIT` a child process inherits the handle (what `O_CLOEXEC` stops
on POSIX).

`POSIX_NAME` maps each exported name to its `os.O_*` name, so a sentry that looks for
`O_NOFOLLOW` on a private open reads `_osflags.NOFOLLOW` as the same flag. `DIR_FD` is a
capability probe, not a platform test: it is true where the `os` functions take `dir_fd=`
(`os.supports_dir_fd` is empty on Windows). Only the modules listed in `DIR_FD_READERS` of
`tests/sentry/test_platform_checks.py` may read it.
"""

from __future__ import annotations

import os
import sys

WINDOWS = sys.platform == "win32"
DIR_FD = bool(os.supports_dir_fd)


def _posix_only(name: str, *, optional: bool = False) -> int:
    """0 on Windows. On POSIX the flag must exist: a missing security flag fails the import
    instead of becoming a silent 0. `optional` is for `O_PATH`, which only Linux defines."""
    if WINDOWS:
        return 0
    return getattr(os, name, 0) if optional else int(getattr(os, name))


def _windows_only(name: str) -> int:
    return getattr(os, name, 0) if WINDOWS else 0


BINARY = _windows_only("O_BINARY")
NOINHERIT = _windows_only("O_NOINHERIT")
_MODE = BINARY | NOINHERIT

RDONLY = os.O_RDONLY | _MODE
WRONLY = os.O_WRONLY | _MODE
RDWR = os.O_RDWR | _MODE
CREAT = os.O_CREAT
EXCL = os.O_EXCL
TRUNC = os.O_TRUNC

NOFOLLOW = _posix_only("O_NOFOLLOW")
CLOEXEC = _posix_only("O_CLOEXEC")
DIRECTORY = _posix_only("O_DIRECTORY")
NONBLOCK = _posix_only("O_NONBLOCK")
NOCTTY = _posix_only("O_NOCTTY")
PATH = _posix_only("O_PATH", optional=True)

POSIX_NAME: dict[str, str] = {
    name: f"O_{name}"
    for name in (
        "RDONLY",
        "WRONLY",
        "RDWR",
        "CREAT",
        "EXCL",
        "TRUNC",
        "NOFOLLOW",
        "CLOEXEC",
        "DIRECTORY",
        "NONBLOCK",
        "NOCTTY",
        "PATH",
        "BINARY",
        "NOINHERIT",
    )
}
