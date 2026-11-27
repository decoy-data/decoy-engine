"""A memory error during cleanup is never hidden, and a strict guard keeps no library error.

`shutil.rmtree(..., ignore_errors=True)` swallows a `MemoryError` on Python 3.10 and 3.11 (3.12
propagates it), so a fault inside the real removal ended a scratch-only run as `completed`.
`fileaccess.remove_tree` ignores ordinary filesystem errors and raises a memory error. Each case
faults `os.lstat` inside the real `rmtree` call, on the path the cleanup removes.

The strict guard (`guarded_with_parser_errors`) must not leave the raw library error, which can
carry a cell value, in the frame locals of the error it raises.
"""

from __future__ import annotations

import errno
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from decoy_engine import fileaccess
from decoy_engine.execution import run_pipeline_isolated
from decoy_engine.fileaccess import _errors, _local
from tests.unit.execution.publication._isolated_support import ENGINE_VERSION, sources
from tests.unit.execution.publication.test_isolated_commit_memory import CANARY
from tests.unit.execution.publication.test_isolated_readback_cap import scratch  # noqa: F401
from tests.unit.execution.publication.test_memory_boundary_routes import Route, raises_memory

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX isolated route")

STAGE = "._decoy_publication_pending_"


def removal_fault(mp: pytest.MonkeyPatch, marker: str) -> list[str]:
    """Raise `MemoryError` once from `os.lstat` while a real `shutil.rmtree` runs on a path with
    `marker`. The fault covers the whole call, so it does not depend on the helper's frame name,
    which differs between Python versions."""
    fired: list[str] = []
    inside: list[str] = []
    real_lstat, real_rmtree = os.lstat, shutil.rmtree

    def lstat(path: Any, *args: Any, **kwargs: Any) -> Any:
        if inside and not fired and marker in str(path):
            fired.append(marker)
            raise MemoryError(CANARY)
        return real_lstat(path, *args, **kwargs)

    def rmtree(path: Any, *args: Any, **kwargs: Any) -> Any:
        inside.append(str(path))
        try:
            return real_rmtree(path, *args, **kwargs)
        finally:
            inside.pop()

    mp.setattr(os, "lstat", lstat)
    mp.setattr(shutil, "rmtree", rmtree)
    return fired


def test_remove_tree_ignores_filesystem_errors_and_raises_memory_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fileaccess.remove_tree(tmp_path / "missing")  # an ordinary failure stays best-effort
    (tmp_path / "gone" / "inner").mkdir(parents=True)
    fileaccess.remove_tree(tmp_path / "gone")
    assert not (tmp_path / "gone").exists()
    (tmp_path / "held").mkdir()
    fired = removal_fault(monkeypatch, "held")
    raises_memory(fileaccess.remove_tree, tmp_path / "held")
    assert fired


def test_remove_tree_ignores_only_filesystem_errors() -> None:
    """A NUL in the path raises `ValueError` from `os.lstat` on every Python version, not only
    on 3.12."""
    with pytest.raises(ValueError):
        fileaccess.remove_tree("stage\0name")


def test_a_failed_abort_removal_still_closes_the_held_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = _local.LocalOutputTxn(tmp_path / "out", "dir", "exclusive", "publication")
    assert txn._held.fd >= 0
    fired = removal_fault(monkeypatch, STAGE)
    raises_memory(txn.abort)
    assert fired
    assert txn._held.fd == -1  # closed before the error reached the caller
    txn.abort()  # a second abort returns early and stays quiet


def test_a_fault_in_the_scratch_stage_removal_is_not_a_completed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
) -> None:
    route = Route(tmp_path, monkeypatch, True)
    fired = removal_fault(monkeypatch, "staging_output")
    result = route.go_checked(output=False)
    assert fired
    route.not_published(result)


def test_a_fault_in_the_work_root_removal_after_the_bind_is_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
) -> None:
    route = Route(tmp_path, monkeypatch, True)
    fired = removal_fault(monkeypatch, "decoy-isolated-run-")
    result = route.go_checked()
    assert fired
    route.unknown(result)
    assert (route.out / "t1.parquet").exists()


@pytest.mark.parametrize("isolated", [True, False], ids=["isolated", "resident"])
def test_a_fault_in_the_stage_removal_on_a_matching_replay_is_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
    isolated: bool,
) -> None:
    route = Route(tmp_path, monkeypatch, isolated)
    assert route.go().outcome == "completed"
    fired = removal_fault(monkeypatch, STAGE)
    result = route.go_checked()
    assert fired
    route.unknown(result)
    assert (route.out / f"{route.table}.parquet").exists()


def test_a_caller_staging_output_that_already_exists_is_refused_and_kept(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
) -> None:
    """The parent removes only a scratch stage it made. A `staging_output` folder that was
    already in the caller's `staging_dir` holds someone else's file, so the run refuses it."""
    route = Route(tmp_path, monkeypatch, True)
    root = fileaccess.open_protected_dir(tmp_path / "caller-stage", create=True)
    (root / "staging_output").mkdir()
    keep = root / "staging_output" / "keep.txt"
    keep.write_bytes(b"keep")
    refusal: BaseException | None = None
    try:
        run_pipeline_isolated(
            route.cfg,
            sources(route.cfg),
            engine_version=ENGINE_VERSION,
            isolate=True,
            staging_dir=root,
        )
    except BaseException as exc:
        refusal = exc
    kept = keep.exists()
    assert isinstance(refusal, fileaccess.ProtectedDirUnsafe), type(refusal).__name__
    assert kept and keep.read_bytes() == b"keep"


# -- the strict guard keeps no library error in its frames --------------------------------------


def frame_leaks(exc: BaseException) -> list[str]:
    """The locals of the guard's own frames in `exc`'s traceback that show the canary."""
    found: list[str] = []
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == _errors.__file__:
            found += [
                f"{tb.tb_frame.f_code.co_name}.{name}"
                for name, value in tb.tb_frame.f_locals.items()
                if value is not exc and CANARY in repr(value)
            ]
        tb = tb.tb_next
    return found


def library_failure(kind: str) -> Exception:
    return {
        "read_error": ValueError(f"bad cell {CANARY}"),
        "resource": OSError(errno.ENOSPC, f"no space {CANARY}", CANARY),
        "memory_text": OSError(f"Unknown error: Wrapping {CANARY} failed"),
    }[kind]


@pytest.mark.parametrize("kind", ["read_error", "resource", "memory_text"])
def test_the_strict_guard_keeps_the_library_error_out_of_its_frames(kind: str) -> None:
    original = library_failure(kind)

    def call() -> None:
        raise original

    with pytest.raises(Exception) as info:
        _errors.guarded_with_parser_errors("field", True, (), call)
    assert info.value is not original
    assert frame_leaks(info.value) == []


def test_the_strict_guard_frames_hold_nothing_on_a_parser_pass_through() -> None:
    parser = ValueError(f"parser {CANARY}")

    def call() -> None:
        raise parser

    with pytest.raises(ValueError) as info:
        _errors.guarded_with_parser_errors("field", True, (ValueError,), call)
    assert info.value is parser
    assert frame_leaks(info.value) == []
