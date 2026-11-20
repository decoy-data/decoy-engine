"""AT-EW1-3: the strict file-access policy refuses where it cannot work (Windows plan E11, EW1).

`RootedFileAccess` confines through directory descriptors. Without `dir_fd` support it raises
`FileAccessUnavailable` at construction, before any open, with and without the portable
fallback, whose descriptor walk needs `dir_fd` too.
"""

from __future__ import annotations

import sys

import pytest

from decoy_engine.fileaccess import FileAccessUnavailable, RootedFileAccess, _osflags


@pytest.mark.parametrize("fallback", [False, True])
def test_rooted_policy_refuses_without_dir_fd(
    monkeypatch: pytest.MonkeyPatch, fallback: bool
) -> None:
    monkeypatch.setattr(_osflags, "DIR_FD", False)
    with pytest.raises(FileAccessUnavailable):
        RootedFileAccess([], allow_portable_fallback=fallback)


@pytest.mark.skipif(sys.platform != "win32", reason="the unpatched refusal is the Windows fact")
@pytest.mark.parametrize("fallback", [False, True])
def test_rooted_policy_refuses_on_windows(fallback: bool) -> None:
    with pytest.raises(FileAccessUnavailable):
        RootedFileAccess([], allow_portable_fallback=fallback)


def test_the_policy_still_constructs_with_dir_fd() -> None:
    if not _osflags.DIR_FD:
        pytest.skip("no dir_fd on this platform")
    assert RootedFileAccess([], allow_portable_fallback=True).roots == ()
