"""AT-EW1-4: `_osflags` is the one reader of `os.O_*` and its values are the OS's (EW1, D1).

On POSIX every exported flag equals its `os.O_*` value and the Windows-only names are 0. On
Windows the open-mode flags carry `O_BINARY | O_NOINHERIT` and the POSIX-only flags are 0.
"""

from __future__ import annotations

import os
import sys

import pytest

from decoy_engine.fileaccess import _osflags

MODES = ("RDONLY", "WRONLY", "RDWR")
NOT_FLAGS = frozenset({"WINDOWS", "POSIX_NAME", "DIR_FD"})
EXPORTED = sorted(
    n for n in vars(_osflags) if n.isupper() and not n.startswith("_") and n not in NOT_FLAGS
)


def test_posix_name_maps_every_exported_flag() -> None:
    assert sorted(_osflags.POSIX_NAME) == EXPORTED
    assert all(v == f"O_{k}" for k, v in _osflags.POSIX_NAME.items())


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX values")
@pytest.mark.parametrize("name", EXPORTED)
def test_posix_values_equal_os_values(name: str) -> None:
    assert getattr(_osflags, name) == getattr(os, _osflags.POSIX_NAME[name], 0)
    assert _osflags.WINDOWS is False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX values")
@pytest.mark.parametrize("name", ["NOFOLLOW", "CLOEXEC", "DIRECTORY", "NONBLOCK", "NOCTTY"])
def test_posix_security_flags_are_nonzero(name: str) -> None:
    """A security flag that fell back to 0 would drop its protection without a sound."""
    assert getattr(_osflags, name) != 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows values")
@pytest.mark.parametrize("name", MODES)
def test_windows_open_modes_are_binary_and_not_inherited(name: str) -> None:
    value = getattr(_osflags, name)
    assert value & os.O_BINARY and value & os.O_NOINHERIT
    assert value & ~(os.O_BINARY | os.O_NOINHERIT) == getattr(os, f"O_{name}")
    assert _osflags.WINDOWS is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows values")
@pytest.mark.parametrize("name", ["NOFOLLOW", "CLOEXEC", "DIRECTORY", "NONBLOCK", "NOCTTY", "PATH"])
def test_windows_posix_only_flags_are_zero(name: str) -> None:
    assert getattr(_osflags, name) == 0
    assert _osflags.DIR_FD is False
