"""G6-1: one function names the engine's scratch root, and an unusable choice stops the run."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from itertools import combinations
from pathlib import Path

import pytest

from decoy_engine import reasons
from decoy_engine.execution.out_of_core._spill_estimate import default_ooc_temp_root
from decoy_engine.fileaccess import ScratchArena, scratch_root
from decoy_engine.fileaccess._protected_dir import ScratchRootUnusable, _parent_base

VARS = ("TMPDIR", "TEMP", "TMP")


@pytest.fixture(autouse=True)
def _clean_temp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(tempfile, "tempdir", None)


def _unusable(kind: str, tmp_path: Path) -> str:
    if kind == "missing":
        return str(tmp_path / "gone")
    if kind == "file":
        path = tmp_path / "plain-file"
        path.write_text("x")
        return str(path)
    raise AssertionError(kind)


def test_scratch_root_is_one_function(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    cached = tmp_path / "cached"
    cached.mkdir()
    monkeypatch.setenv("TMPDIR", str(chosen))
    # The stdlib cache may name another directory by now; the selected variable still wins.
    monkeypatch.setattr(tempfile, "tempdir", str(cached))
    assert scratch_root() == chosen
    assert Path(_parent_base(None)) == chosen
    assert default_ooc_temp_root() == chosen
    if sys.platform != "win32":  # the arena is POSIX-only until S1w
        with ScratchArena.fresh() as arena:
            assert Path(arena.local_path()).parent == chosen


def test_scratch_root_without_variables_is_the_stdlib_default() -> None:
    assert scratch_root() == Path(tempfile.gettempdir())


@pytest.mark.parametrize("kind", ["missing", "file"])
@pytest.mark.parametrize("var", VARS)
def test_scratch_root_refuses_unusable_tmpdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, var: str, kind: str
) -> None:
    bad = _unusable(kind, tmp_path)
    monkeypatch.setenv(var, bad)
    with pytest.raises(ScratchRootUnusable) as seen:
        scratch_root()
    _value_free(seen.value, var, bad)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows makes directories with CreateDirectoryW, not os.mkdir; the Windows lane covers it",
)
def test_scratch_root_refuses_a_denied_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Injected so the case also runs as root and on Windows, where a mode bit proves nothing.
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    real_mkdir = os.mkdir

    def deny(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(os.fsdecode(path)).parent == tmp_path:
            raise PermissionError(13, "denied")
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(os, "mkdir", deny)
    with pytest.raises(ScratchRootUnusable) as seen:
        scratch_root()
    _value_free(seen.value, "TMPDIR", str(tmp_path))


def test_scratch_root_refuses_a_parent_that_denies_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Create works, delete does not: each call would leave one more directory behind.
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: None)
    with pytest.raises(ScratchRootUnusable) as seen:
        scratch_root()
    _value_free(seen.value, "TMPDIR", str(tmp_path))


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs a mode bit")
def test_scratch_root_refuses_a_read_only_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    try:
        try:
            (locked / "probe").touch()
        except PermissionError:
            pass
        else:
            pytest.skip("the filesystem does not deny the create")
        monkeypatch.setenv("TMPDIR", str(locked))
        with pytest.raises(ScratchRootUnusable):
            scratch_root()
    finally:
        locked.chmod(0o700)


@pytest.mark.parametrize(("high", "low"), list(combinations(VARS, 2)))
def test_scratch_root_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, high: str, low: str
) -> None:
    good, stale = tmp_path / "good", str(tmp_path / "stale")
    good.mkdir()
    # A valid higher choice wins over a stale lower one.
    monkeypatch.setenv(high, str(good))
    monkeypatch.setenv(low, stale)
    assert scratch_root() == good
    # A stale higher choice stops the run, even with a valid lower one.
    monkeypatch.setenv(high, stale)
    monkeypatch.setenv(low, str(good))
    with pytest.raises(ScratchRootUnusable) as seen:
        scratch_root()
    _value_free(seen.value, high, stale, other=low)


def test_empty_variable_is_not_a_choice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    good = tmp_path / "good"
    good.mkdir()
    monkeypatch.setenv("TMPDIR", "")
    monkeypatch.setenv("TEMP", str(good))
    assert scratch_root() == good


def _value_free(exc: BaseException, var: str, value: str, other: str | None = None) -> None:
    assert exc.code == reasons.runtime.SCRATCH_ROOT_UNUSABLE  # type: ignore[attr-defined]
    text = str(exc)
    assert var in text
    assert value not in text and os.path.basename(value) not in text
    if other is not None:
        assert other not in text.replace(var, "")  # TMP is a prefix of TMPDIR
    assert exc.__cause__ is None and exc.__context__ is None
