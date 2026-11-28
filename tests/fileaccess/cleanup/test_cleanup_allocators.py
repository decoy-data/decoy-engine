"""The protected-directory allocators go through the cleanup ledger (plan 4c, cells C2, C9, R6-R8).

Every fault is armed for the target call only and matched on the path, never on a caller frame
name; each cell checks that it fired.
"""

from __future__ import annotations

import errno
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.fileaccess import ScratchArena, _fdtree, protected_scratch_dir
from decoy_engine.fileaccess import _protected_dir as pd
from decoy_engine.fileaccess import _scratch as scratch_mod
from decoy_engine.fileaccess._protected_dir import ScratchRootUnusable, allocate_protected_dir
from decoy_engine.fileaccess.cleanup import CleanupLedger

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX allocator cells")

FAULTS: list[Any] = [
    pytest.param(lambda: OSError(errno.ENOSPC, "x"), id="E"),
    pytest.param(lambda: MemoryError(), id="M"),
    pytest.param(lambda: KeyboardInterrupt(), id="I"),
]


def _names(path: Path) -> list[str]:
    return sorted(os.listdir(path))


def _arm(
    monkeypatch: pytest.MonkeyPatch, owner: object, name: str, make: Any, marker: str
) -> list[str]:
    """Raise `make()` once from `owner.name` when its first argument names `marker`."""
    fired: list[str] = []
    real = getattr(owner, name)

    def faulted(path: Any, *args: Any, **kwargs: Any) -> Any:
        if not fired and marker in str(path):
            fired.append(str(path))
            raise make()
        return real(path, *args, **kwargs)

    monkeypatch.setattr(owner, name, faulted)
    return fired


def test_allocate_registers_the_root_and_unregisters_it_only_after_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    at_unregister: list[bool] = []
    real = pd._unregister
    monkeypatch.setattr(
        pd, "_unregister", lambda p: (at_unregister.append(os.path.lexists(p)), real(p))[1]
    )
    with CleanupLedger() as ledger:
        root = allocate_protected_dir(ledger, parent=tmp_path, prefix="job-")
        assert isinstance(root, Path) and root.parent == tmp_path
        assert stat.S_IMODE(os.lstat(root).st_mode) == 0o700
        assert pd._live_root(_fdtree.path_key(root / "child")) == _fdtree.path_key(root)
    assert at_unregister == [False]  # the directory was gone before its registration was dropped
    assert not root.exists() and pd._live_root(_fdtree.path_key(root)) is None


def test_scratch_dir_removal_is_confirmed_and_retried_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fired = _arm(monkeypatch, _fdtree, "remove_tree", lambda: OSError(errno.ENOSPC, "x"), "job-")
    with protected_scratch_dir(tmp_path, "job-") as root:
        (root / "data").write_text("x")
    assert fired and not root.exists()  # pass two removed what pass one could not
    assert pd._live_root(_fdtree.path_key(root)) is None


def test_scratch_dir_stays_registered_while_its_removal_is_unconfirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = _fdtree.remove_tree
    monkeypatch.setattr(
        _fdtree, "remove_tree", lambda p: (_ for _ in ()).throw(OSError(errno.EIO, "x"))
    )
    with protected_scratch_dir(tmp_path, "job-") as root:
        pass
    assert root.is_dir()  # persistent failure: kept as residue, never claimed gone
    assert pd._live_root(_fdtree.path_key(root)) == _fdtree.path_key(root)
    monkeypatch.setattr(_fdtree, "remove_tree", real)
    pd._unregister(root)
    _fdtree.remove_tree(root)


@pytest.mark.parametrize("make", FAULTS)
@pytest.mark.parametrize("seam", ["mkdir", "chmod", "check"])
def test_c2_a_fault_in_the_create_leaves_no_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seam: str, make: Any
) -> None:
    owner, name = {
        "mkdir": (pd, "_mkdir"),
        "chmod": (pd, "_chmod_private"),
        "check": (pd, "_check"),
    }[seam]
    fired = _arm(monkeypatch, owner, name, make, "job-")
    before = _names(tmp_path)
    ledger = CleanupLedger()
    with pytest.raises((OSError, MemoryError, KeyboardInterrupt)):
        allocate_protected_dir(ledger, parent=tmp_path, prefix="job-")
    assert len(fired) == 1
    ledger.close()
    assert _names(tmp_path) == before
    assert all(pd._live_root(_fdtree.path_key(f)) is None for f in fired)


@pytest.mark.parametrize(
    "make", [pytest.param(MemoryError, id="M"), pytest.param(KeyboardInterrupt, id="I")]
)
def test_c2e_a_fault_in_register_leaves_nothing_registered_or_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make: Any
) -> None:
    fired = _arm(monkeypatch, pd, "_register", make, "job-")
    ledger = CleanupLedger()
    with pytest.raises((MemoryError, KeyboardInterrupt)):
        allocate_protected_dir(ledger, parent=tmp_path, prefix="job-")
    assert len(fired) == 1
    ledger.close()
    assert _names(tmp_path) == []
    assert pd._live_root(_fdtree.path_key(fired[0])) is None


def test_r8_a_memory_error_in_unregister_is_retried_in_the_next_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fired = _arm(monkeypatch, pd, "_unregister", MemoryError, "job-")
    ledger = CleanupLedger()
    root = allocate_protected_dir(ledger, parent=tmp_path, prefix="job-")
    with pytest.raises(MemoryError):
        ledger.close()
    assert len(fired) == 1
    assert not root.exists() and pd._live_root(_fdtree.path_key(root)) is None
    ledger.close()  # a second close is safe


def test_r7_scratch_dir_exit_removes_the_root_for_an_out_of_core_user(tmp_path: Path) -> None:
    with protected_scratch_dir(tmp_path, "decoy-ooc-run-") as root:
        (root / "spill" / "deep").mkdir(parents=True)
        (root / "spill" / "deep" / "f").write_bytes(b"x")
    assert _names(tmp_path) == []


# -- the scratch-root probe: C9 and R6 ---------------------------------------------------------


def _probe_residue(base: Path) -> list[str]:
    return [n for n in _names(base) if n.startswith(".decoy-probe-")]


@pytest.mark.parametrize("seam", ["_mkdir", "_chmod_private"])
def test_c9_enospc_at_the_probe_create_is_unusable_and_leaves_no_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seam: str
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    fired = _arm(monkeypatch, pd, seam, lambda: OSError(errno.ENOSPC, "x"), ".decoy-probe-")
    with pytest.raises(ScratchRootUnusable):
        pd.scratch_root()
    assert len(fired) == 1 and _probe_residue(tmp_path) == []
    assert pd.scratch_root() == tmp_path  # disarmed retry
    assert _probe_residue(tmp_path) == []


@pytest.mark.parametrize(
    "make", [pytest.param(MemoryError, id="M"), pytest.param(KeyboardInterrupt, id="I")]
)
def test_c9_a_memory_error_or_interrupt_after_the_probe_mkdir_removes_the_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make: Any
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    fired = _arm(monkeypatch, pd, "_chmod_private", make, ".decoy-probe-")
    with pytest.raises((MemoryError, KeyboardInterrupt)):
        pd.scratch_root()
    assert len(fired) == 1 and _probe_residue(tmp_path) == []
    assert pd.scratch_root() == tmp_path


def test_r6_enospc_at_the_probe_removal_is_unusable_but_the_ledger_still_removes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    fired = _arm(
        monkeypatch, _fdtree, "remove_tree", lambda: OSError(errno.ENOSPC, "x"), ".decoy-probe-"
    )
    with pytest.raises(ScratchRootUnusable):
        pd.scratch_root()
    assert len(fired) == 1 and _probe_residue(tmp_path) == []
    assert pd.scratch_root() == tmp_path


@pytest.mark.parametrize(
    "make", [pytest.param(MemoryError, id="M"), pytest.param(KeyboardInterrupt, id="I")]
)
def test_r6_a_memory_error_or_interrupt_at_probe_removal_escapes_after_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make: Any
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    fired = _arm(monkeypatch, _fdtree, "remove_tree", make, ".decoy-probe-")
    with pytest.raises((MemoryError, KeyboardInterrupt)):
        pd.scratch_root()
    assert len(fired) == 1 and _probe_residue(tmp_path) == []
    assert pd.scratch_root() == tmp_path


# -- the arena (L16) ---------------------------------------------------------------------------


def test_l16_a_fault_after_the_allocation_removes_the_pending_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "base"
    base.mkdir()
    before = _names(base)
    fired = _arm(monkeypatch, scratch_mod, "_open_dir", MemoryError, "decoy-arena-pending-")
    with pytest.raises(MemoryError):
        ScratchArena.fresh(under=base)
    assert len(fired) == 1
    assert _names(base) == before


def test_l16_on_success_the_renamed_pending_entry_is_released_without_a_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    removals: list[str] = []
    real = _fdtree.remove_confirmed
    monkeypatch.setattr(
        _fdtree, "remove_confirmed", lambda p, **kw: (removals.append(p), real(p, **kw))[1]
    )
    with ScratchArena.fresh(under=tmp_path) as arena:
        assert Path(arena.local_path()).parent == tmp_path
    assert removals == []  # the pending name was renamed away; the ledger found it absent
    assert _names(tmp_path) == []
