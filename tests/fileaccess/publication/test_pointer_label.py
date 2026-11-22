"""The `pointer` file-access label and `LocalPointerStore` over both policies (DELIV E2a).

AT-52: the label's publish (fsync the stage, rename, fsync the parent; a failed parent fsync is
`CommitUncertain` with the new bytes visible). AT-53: the read-error map for `read` and for the
fresh read in `replace_if`. AT-12 (engine part): a parent fsync failing after the replace makes
`replace_if` answer `uncertain` with the leaf holding the new bytes.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.fileaccess import CommitUncertain
from decoy_engine.fileaccess._errors import deny
from decoy_engine.publication import LocalPointerStore, PointerState, PointerUnreadable
from tests.fileaccess.publication._chain_support import OSMARK, Recorder, anchor_at, key
from tests.fileaccess.publication._dirmode_support import POLICIES, _output_dir

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX durable pointer")

OLD, NEW = b"r1\n", b"r2\n"


def _leaf(policy: str, base: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Path, Path]:
    """The pointer leaf `OutputDir`, its directory and the file it names."""
    folder = base / "out" / "n"
    folder.mkdir(parents=True)
    if policy == "ambient":
        anchor_at(monkeypatch, base)
    out, _root_fd = _output_dir(policy, base, "out/n/LATEST")  # the fd lives for the test
    return out, folder, folder / "LATEST"


def _publish(out: Any, data: bytes) -> None:
    with out.begin("file", "replace", label="pointer") as txn:
        with os.fdopen(txn.create_file("value"), "wb") as fh:
            fh.write(data)
        txn.publish()


def _stages(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.name.startswith("._decoy_pointer_stage_"))


@pytest.mark.parametrize("policy", POLICIES)
def test_publish_orders_file_rename_parent_and_is_private(
    tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, folder, leaf = _leaf(policy, tmp_path, monkeypatch)
    leaf.write_bytes(OLD)
    recorder = Recorder(monkeypatch)
    _publish(out, NEW)
    assert leaf.read_bytes() == NEW
    assert stat.S_IMODE(os.lstat(leaf).st_mode) == 0o600
    assert _stages(folder) == []
    kinds = [kind for kind, _ in recorder.events]
    file_sync = recorder.events.index(("fsync", key(leaf)))
    rename = kinds.index("rename")
    parent_sync = recorder.events.index(("fsync", key(folder)))
    assert file_sync < rename < parent_sync


@pytest.mark.parametrize("policy", POLICIES)
def test_parent_fsync_failing_after_rename_is_commit_uncertain(
    tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, folder, leaf = _leaf(policy, tmp_path, monkeypatch)
    leaf.write_bytes(OLD)
    folder_key = key(folder)
    Recorder(monkeypatch, fail=lambda event: event == ("fsync", folder_key))
    with pytest.raises(CommitUncertain) as caught:
        _publish(out, NEW)
    assert OSMARK not in str(caught.value)
    assert caught.value.errno_name == "EIO"
    assert leaf.read_bytes() == NEW  # visible, not confirmed durable
    assert _stages(folder) == []


@pytest.mark.parametrize("policy", POLICIES)
def test_stage_fsync_failing_leaves_the_old_leaf_and_no_stage(
    tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, folder, leaf = _leaf(policy, tmp_path, monkeypatch)
    leaf.write_bytes(OLD)
    Recorder(monkeypatch, fail=lambda event: event[0] == "fsync")
    with pytest.raises(OSError) as caught:
        _publish(out, NEW)
    assert not isinstance(caught.value, CommitUncertain)
    assert OSMARK not in str(caught.value)
    assert leaf.read_bytes() == OLD
    assert _stages(folder) == []


@pytest.mark.parametrize("policy", POLICIES)
def test_a_link_at_the_leaf_is_replaced_not_written_through(
    tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, folder, leaf = _leaf(policy, tmp_path, monkeypatch)
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"sentinel")
    leaf.symlink_to(sentinel)
    _publish(out, NEW)
    assert not leaf.is_symlink()
    assert leaf.read_bytes() == NEW
    assert sentinel.read_bytes() == b"sentinel"


def _regular(leaf: Path) -> None:
    leaf.write_bytes(b"r" * 39 + b"\n")


def _link(leaf: Path) -> None:
    target = leaf.parent / "target"
    target.write_bytes(OLD)
    leaf.symlink_to(target)


def _directory(leaf: Path) -> None:
    leaf.mkdir()


def _fifo(leaf: Path) -> None:
    os.mkfifo(leaf)


def _big(leaf: Path) -> None:
    leaf.write_bytes(b"x" * 5 * 1024)


UNREADABLE = {"link": _link, "directory": _directory, "fifo": _fifo, "big": _big}


def _expect_unreadable(store: LocalPointerStore) -> None:
    with pytest.raises(PointerUnreadable) as caught:
        store.read()
    text = str(caught.value)
    assert "LATEST" not in text and "xxx" not in text and OSMARK not in text
    assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.parametrize("policy", POLICIES)
def test_read_of_absent_and_regular(
    tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, _folder, leaf = _leaf(policy, tmp_path, monkeypatch)
    store = LocalPointerStore(out)
    assert store.read() == PointerState(None, None)
    _regular(leaf)
    raw = b"r" * 39 + b"\n"
    assert store.read() == PointerState(raw, raw)


@pytest.mark.parametrize("case", sorted(UNREADABLE))
@pytest.mark.parametrize("policy", POLICIES)
def test_read_refuses_every_unreadable_case(
    tmp_path: Path, policy: str, case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, _folder, leaf = _leaf(policy, tmp_path, monkeypatch)
    UNREADABLE[case](leaf)
    _expect_unreadable(LocalPointerStore(out))


@pytest.mark.parametrize("policy", POLICIES)
def test_read_refuses_a_policy_denial(
    tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, _folder, _leaf_path = _leaf(policy, tmp_path, monkeypatch)

    def denied(self: Any, *, limit: int) -> bytes | None:
        raise deny("targets.t.path") from None

    monkeypatch.setattr(type(out), "adopt_file", denied)
    _expect_unreadable(LocalPointerStore(out))


@pytest.mark.parametrize("policy", POLICIES)
def test_read_refuses_an_os_error_on_the_read(
    tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, _folder, leaf = _leaf(policy, tmp_path, monkeypatch)
    _regular(leaf)
    Recorder(monkeypatch, fail=lambda event: event[0] == "fsync")
    _expect_unreadable(LocalPointerStore(out))


@pytest.mark.parametrize("policy", POLICIES)
def test_replace_if_on_absent_and_regular(
    tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, _folder, leaf = _leaf(policy, tmp_path, monkeypatch)
    store = LocalPointerStore(out)
    assert store.replace_if(PointerState(None, None), OLD) == "replaced"
    assert leaf.read_bytes() == OLD
    assert store.replace_if(PointerState(b"other\n", None), NEW) == "stale"
    assert leaf.read_bytes() == OLD
    assert store.replace_if(PointerState(OLD, OLD), NEW) == "replaced"
    assert leaf.read_bytes() == NEW


@pytest.mark.parametrize("case", sorted(UNREADABLE))
@pytest.mark.parametrize("policy", POLICIES)
def test_replace_if_fails_on_every_unreadable_case(
    tmp_path: Path, policy: str, case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, _folder, leaf = _leaf(policy, tmp_path, monkeypatch)
    UNREADABLE[case](leaf)
    before = os.lstat(leaf)
    assert LocalPointerStore(out).replace_if(PointerState(None, None), NEW) == "failed"
    after = os.lstat(leaf)
    assert (before.st_ino, before.st_mode, before.st_size) == (
        after.st_ino,
        after.st_mode,
        after.st_size,
    )


@pytest.mark.parametrize("policy", POLICIES)
def test_replace_if_fails_on_a_denial_and_on_an_os_error(
    tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, _folder, leaf = _leaf(policy, tmp_path, monkeypatch)
    _regular(leaf)
    raw = leaf.read_bytes()
    Recorder(monkeypatch, fail=lambda event: event[0] == "fsync")
    assert LocalPointerStore(out).replace_if(PointerState(raw, raw), NEW) == "failed"
    assert leaf.read_bytes() == raw
    monkeypatch.undo()

    def denied(self: Any, *, limit: int) -> bytes | None:
        raise deny("targets.t.path") from None

    monkeypatch.setattr(type(out), "adopt_file", denied)
    assert LocalPointerStore(out).replace_if(PointerState(raw, raw), NEW) == "failed"
    assert leaf.read_bytes() == raw


@pytest.mark.parametrize("policy", POLICIES)
def test_parent_fsync_failing_after_the_replace_is_uncertain(
    tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AT-12, engine part. The fresh read also fsyncs the parent, so the fault arms only once
    the rename has happened."""
    out, folder, leaf = _leaf(policy, tmp_path, monkeypatch)
    leaf.write_bytes(OLD)
    folder_key = key(folder)

    def after_rename(event: Any) -> bool:
        return event == ("fsync", folder_key) and any(kind == "rename" for kind, _ in rec.events)

    rec = Recorder(monkeypatch, fail=after_rename)
    assert LocalPointerStore(out).replace_if(PointerState(OLD, OLD), NEW) == "uncertain"
    assert leaf.read_bytes() == NEW
    assert _stages(folder) == []


@pytest.mark.parametrize("policy", POLICIES)
def test_a_missing_folder_is_created_for_the_pointer(
    tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if policy == "ambient":
        anchor_at(monkeypatch, tmp_path)
    out, _fd = _output_dir(policy, tmp_path, "out/new/LATEST")
    assert not (tmp_path / "out").exists()
    _publish(out, NEW)
    assert (tmp_path / "out" / "new" / "LATEST").read_bytes() == NEW


@pytest.mark.parametrize("mode", ["exclusive"])
@pytest.mark.parametrize("policy", POLICIES)
def test_the_pointer_label_refuses_any_mode_but_replace(
    tmp_path: Path, policy: str, mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, folder, leaf = _leaf(policy, tmp_path, monkeypatch)
    with pytest.raises(Exception) as caught:
        out.begin("file", mode, label="pointer")
    assert type(caught.value).__name__ in ("FileAccessDenied", "FileAccessUnavailable")
    assert not leaf.exists() and _stages(folder) == []
