"""F22 5.5 and 5.1 (slice b1): `OutputDir.adopt_file`, `VaultWriter.publish`, `VaultCommit`,
`BytesHandle` and `same_rows`.

Plan `docs/plans/2026-10-30-f22-publication-replan.md` 7.2 rows `test_vault_adopt_or_conflict`
and `test_vault_ancestor_chain_durable`, and the vault half of
`test_unreadable_ancestor_fail_closed`. A vault leaf is adopted only after its bytes and its
whole chain were fsynced; anything else is refused with a fixed code and no text of the vault.
"""

from __future__ import annotations

import errno
import hashlib
import os
import signal
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from decoy_engine import fileaccess, reasons
from decoy_engine.publication import _vault_order
from decoy_engine.vault import VaultCommit, VaultError, load_vault
from tests.fileaccess.publication._chain_support import (
    Recorder,
    anchor_at,
    deny_reads,
    key,
    restat,
)
from tests.fileaccess.publication._dirmode_support import POLICIES, run_child
from tests.fileaccess.publication._vault_support import (
    CHILD_MARKER,
    KEY,
    LEAF,
    OTHER_KEY,
    OTHER_ROWS,
    IssueProbe,
    fingerprint,
    kill_child,
    vault_out,
    writer,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX durable vault")
REL = f"vaults/{LEAF}"
COMMIT_FAILED = reasons.runtime.VAULT_COMMIT_FAILED
CONFLICT = reasons.decoy.PUBLICATION_VAULT_CONFLICT


@pytest.fixture
def base(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "vaults").mkdir(parents=True)
    return root


def _setup(
    policy: str, base: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, int, Recorder, IssueProbe]:
    if policy == "ambient":
        anchor_at(monkeypatch, base)
    out, root_fd = vault_out(policy, base, REL)
    rec = Recorder(monkeypatch)
    return out, root_fd, rec, IssueProbe(monkeypatch, rec.synced)


def _chain(base: Path) -> list[Any]:
    leaf = base / REL
    return [key(leaf), key(base / "vaults"), key(base)]


def _text_is_value_free(exc: VaultError, base: Path) -> None:
    text = str(exc)
    for secret in (str(base), LEAF, "<vault>", KEY.decode(), "s1", "m1", "injected"):
        assert secret not in text
    assert exc.__cause__ is None and exc.__context__ is None


@pytest.mark.parametrize("policy", POLICIES)
def test_publish_issues_commit_after_the_chain(
    base: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, root_fd, rec, probe = _setup(policy, base, monkeypatch)
    try:
        commit = writer().publish(out)
        assert isinstance(commit, VaultCommit) and commit.adopted is False
        assert commit.entry_count == 2
        data = (base / REL).read_bytes()
        assert commit.size == len(data)
        assert commit.sha256 == hashlib.sha256(data).hexdigest()
        assert probe.issued == [commit]  # non-vacuity: the probe saw the one issue
        assert probe.synced_at_issue[0][-3:] == _chain(base)
        assert load_vault(None, KEY, vault=_vault_order.BytesHandle(data))[0][("ns", "m1")] == "s1"
    finally:
        if root_fd >= 0:
            os.close(root_fd)


def test_commit_is_issued_only_by_the_vault_module() -> None:
    with pytest.raises(fileaccess.FileAccessUnavailable):
        VaultCommit("0" * 64, 1, 1, False)  # type: ignore[call-arg]
    with pytest.raises(fileaccess.FileAccessUnavailable):
        VaultCommit("0" * 64, 1, 1, False, object())  # type: ignore[call-arg, arg-type]


def test_bytes_handle_is_a_constant_display_read_only_handle() -> None:
    handle = _vault_order.BytesHandle(b"not a vault")
    assert handle.display == "<vault>" and isinstance(handle, fileaccess.FileHandle)
    assert handle.read_all() == b"not a vault" and handle.read_all(3) == b"not"
    with handle.open_binary() as fh:
        assert fh.read() == b"not a vault"
        fh.write(b"XX")  # a copy: the handle's bytes cannot change
    assert handle.read_all() == b"not a vault"
    with pytest.raises(VaultError) as caught:  # the one text that names the handle
        load_vault(None, KEY, vault=handle)
    assert "<vault>" in str(caught.value)
    for method in (handle.fileno, handle.library_path, handle.stat):
        with pytest.raises(fileaccess.FileAccessUnavailable):
            method()


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("via", ["publish", "adopt"])
def test_vault_ancestor_chain_durable(
    base: Path, policy: str, via: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leaf, `vaults` and each ancestor to the anchor are fsynced before the commit exists; EIO
    on each of them is `vault_commit_failed` with the leaf kept; after the fault clears, a
    retry gets an adopted commit."""
    out, root_fd, rec, probe = _setup(policy, base, monkeypatch)
    try:
        if via == "adopt":
            writer().publish(out)
            probe.issued.clear(), probe.synced_at_issue.clear()
            before = len(rec.events)
            commit = _vault_order.adopt_vault(out, writer())
            assert commit.adopted is True and probe.issued == [commit]
            assert [k for kind, k in rec.events[before:] if kind == "fsync"] == _chain(base)
            return
        commit = writer().publish(out)
        assert probe.synced_at_issue[0][-3:] == _chain(base) and commit.adopted is False
    finally:
        if root_fd >= 0:
            os.close(root_fd)


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("step", [0, 1, 2])
@pytest.mark.parametrize("via", ["publish", "adopt"])
def test_vault_chain_fsync_eio_keeps_the_leaf(
    base: Path, policy: str, step: int, via: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if policy == "ambient":
        anchor_at(monkeypatch, base)
    out, root_fd = vault_out(policy, base, REL)
    leaf = base / REL
    state = {"armed": False}
    try:
        if via == "adopt":
            writer().publish(out)
            state["armed"] = True
        else:
            real_link = os.link

            def link(*args: Any, **kwargs: Any) -> None:
                real_link(*args, **kwargs)
                state["armed"] = True

            monkeypatch.setattr(os, "link", link)
        chain = [leaf, base / "vaults", base]
        calls: list[Any] = []
        rec = Recorder(
            monkeypatch,
            fail=lambda e: bool(
                state["armed"] and e == ("fsync", key(chain[step])) and not calls.append(1)
            ),
        )
        probe = IssueProbe(monkeypatch, rec.synced)
        with pytest.raises(VaultError) as caught:
            if via == "publish":
                writer().publish(out)
            else:
                _vault_order.adopt_vault(out, writer())
        assert caught.value.code == COMMIT_FAILED and calls  # non-vacuity: the fault fired
        _text_is_value_free(caught.value, base)
        assert probe.issued == [] and leaf.exists()
        monkeypatch.undo()
        retry = _recorder_after_clear(policy, base, monkeypatch)
        out2, fd2 = vault_out(policy, base, REL)
        try:
            adopted = _vault_order.adopt_vault(out2, writer())
            assert adopted.adopted is True
            assert [k for kind, k in retry.events if kind == "fsync"][-3:] == _chain(base)
        finally:
            if fd2 >= 0:
                os.close(fd2)
    finally:
        if root_fd >= 0:
            os.close(root_fd)


def _recorder_after_clear(policy: str, base: Path, mp: pytest.MonkeyPatch) -> Recorder:
    if policy == "ambient":
        anchor_at(mp, base)
    return Recorder(mp)


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("kill_at", [1, 2, 3])
def test_sigkill_between_link_and_each_chain_fsync(
    base: Path, policy: str, kill_at: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = {"base": str(base), "policy": policy, "rel": REL, "kill_at": kill_at}
    code, _ = run_child(kill_child, spec, base.parent)
    assert code == -signal.SIGKILL and (base.parent / CHILD_MARKER).exists()  # non-vacuity
    assert (base / REL).exists()  # the link happened
    out, root_fd, rec, probe = _setup(policy, base, monkeypatch)
    try:
        commit = _vault_order.adopt_vault(out, writer())
        assert commit.adopted is True
        assert probe.synced_at_issue[0][-3:] == _chain(base)
    finally:
        if root_fd >= 0:
            os.close(root_fd)


@pytest.mark.parametrize("policy", POLICIES)
def test_vault_adopt_or_conflict(base: Path, policy: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Equal rows are adopted (a 0400 leaf too) only after the leaf and then the chain were
    fsynced; a different vault, an oversize one or one under another key is a conflict."""
    leaf = base / REL
    out, root_fd = vault_out(policy, base, REL)
    try:
        writer().publish(out)
        os.chmod(leaf, 0o400)  # MEDIUM-4: a read-only vault still opens
        before = fingerprint(leaf)
        if policy == "ambient":
            anchor_at(monkeypatch, base)
        rec = Recorder(monkeypatch)
        probe = IssueProbe(monkeypatch, rec.synced)
        flags: list[int] = []
        real_open = os.open

        def spy_open(path: Any, fl: int, *args: Any, **kw: Any) -> int:
            if os.fsdecode(path).endswith(LEAF):
                flags.append(fl)
            return real_open(path, fl, *args, **kw)

        monkeypatch.setattr(os, "open", spy_open)
        commit = _vault_order.adopt_vault(out, writer())
        monkeypatch.undo()
        data = leaf.read_bytes()
        assert commit.adopted is True and commit.size == len(data) and commit.entry_count == 2
        assert flags and all(f & os.O_ACCMODE == os.O_RDONLY for f in flags)
        assert probe.synced_at_issue[0][-3:] == _chain(base)  # leaf, then the chain
        assert fingerprint(leaf) == before

        refusals: list[tuple[Any, str]] = [
            (writer(OTHER_ROWS), CONFLICT),  # different rows
            (writer(key=OTHER_KEY), CONFLICT),  # another key opens nothing
        ]
        for other, code in refusals:
            with pytest.raises(VaultError) as caught:
                _vault_order.adopt_vault(out, other)
            assert caught.value.code == code
            _text_is_value_free(caught.value, base)
            assert fingerprint(leaf) == before
        big = base / "vaults" / "big.dcyvault"
        big.write_bytes(os.urandom(200_000))
        bigout, bigfd = vault_out(policy, base, "vaults/big.dcyvault")
        try:
            decrypted: list[int] = []
            real_reads = type(writer()).reads_as_own

            def counting(self: Any, handle: Any) -> bool:
                decrypted.append(1)
                return real_reads(self, handle)

            monkeypatch.setattr(type(writer()), "reads_as_own", counting)
            with pytest.raises(VaultError) as caught:  # over the cap: no decrypt attempted
                _vault_order.adopt_vault(bigout, writer())
            assert caught.value.code == CONFLICT and decrypted == []
            monkeypatch.undo()
        finally:
            if bigfd >= 0:
                os.close(bigfd)
    finally:
        if root_fd >= 0:
            os.close(root_fd)


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("fault", ["leaf_fsync", "leaf_open"])
def test_adopt_io_failure_is_commit_failed(
    base: Path, policy: str, fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, root_fd = vault_out(policy, base, REL)
    try:
        writer().publish(out)
        before = fingerprint(base / REL)
        probe_rec = Recorder(
            monkeypatch, fail=lambda e: fault == "leaf_fsync" and e[1] == key(base / REL)
        )
        probe = IssueProbe(monkeypatch, probe_rec.synced)
        if fault == "leaf_open":
            real_open = os.open

            def refuse(path: Any, fl: int, *args: Any, **kw: Any) -> int:
                if os.fsdecode(path).endswith(LEAF):
                    raise PermissionError(errno.EACCES, "injected")
                return real_open(path, fl, *args, **kw)

            monkeypatch.setattr(os, "open", refuse)
        with pytest.raises(VaultError) as caught:
            _vault_order.adopt_vault(out, writer())
        assert caught.value.code == COMMIT_FAILED and probe.issued == []
        _text_is_value_free(caught.value, base)
        monkeypatch.undo()
        assert fingerprint(base / REL) == before
    finally:
        if root_fd >= 0:
            os.close(root_fd)


@pytest.mark.parametrize("policy", POLICIES)
def test_adopt_file_reads_one_fd_and_refuses_the_wrong_kinds(base: Path, policy: str) -> None:
    out, root_fd = vault_out(policy, base, REL)
    leaf = base / REL
    try:
        assert out.adopt_file(limit=100) is None  # absent leaf
        leaf.write_bytes(b"abcdef")
        assert out.adopt_file(limit=6) == b"abcdef"
        with pytest.raises(fileaccess.LeafTooLarge):
            out.adopt_file(limit=5)
        leaf.unlink()
        leaf.mkdir()  # a directory is not a vault
        with pytest.raises(OSError) as caught:
            out.adopt_file(limit=100)
        assert str(base) not in str(caught.value)
        leaf.rmdir()
        (base / "elsewhere").write_bytes(b"x")
        leaf.symlink_to(base / "elsewhere")  # never followed
        with pytest.raises(OSError):
            out.adopt_file(limit=100)
        leaf.unlink()
        os.mkfifo(leaf)  # a FIFO cannot block the open
        with pytest.raises(OSError):
            out.adopt_file(limit=100)
        out_gone, gone_fd = vault_out(policy, base, "nope/" + LEAF)
        try:
            assert out_gone.adopt_file(limit=10) is None  # absent parent
        finally:
            if gone_fd >= 0:
                os.close(gone_fd)
    finally:
        if root_fd >= 0:
            os.close(root_fd)


@pytest.mark.parametrize("policy", POLICIES)
def test_unreadable_ancestor_fail_closed_vault(
    base: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(i) `p/vaults` with `p` a same-uid directory Decoy cannot read: neither a publish nor an
    adopt ever yields a commit."""
    (base / "p" / "vaults").mkdir(parents=True)
    out, root_fd = vault_out(policy, base, f"p/vaults/{LEAF}")
    leaf = base / "p" / "vaults" / LEAF
    try:
        if policy == "ambient":
            anchor_at(monkeypatch, base)
            fresh = writer().publish(out)  # made before `p` becomes unreadable
            assert fresh.adopted is False
        else:
            leaf.write_bytes(b"x")  # strict cannot reach `p`; the leaf is only there to adopt
            leaf.unlink()
        os.chmod(base / "p", 0o300)
        seen: list[str] = []
        deny_reads(monkeypatch, base / "p", seen)
        rec = Recorder(monkeypatch)
        probe = IssueProbe(monkeypatch, rec.synced)
        with pytest.raises((VaultError, fileaccess.FileAccessDenied)):
            writer().publish(out)
        if policy == "ambient":
            with pytest.raises(VaultError) as caught:
                _vault_order.adopt_vault(out, writer())
            assert caught.value.code == COMMIT_FAILED
        assert seen and probe.issued == []  # non-vacuity: the read open of `p` was refused
    finally:
        os.chmod(base / "p", 0o700)
        if root_fd >= 0:
            os.close(root_fd)


def test_unreadable_ancestor_foreign_owner_stops_the_vault_walk(
    base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(iii) ambient: an unreadable directory above the vault directory, owned by another uid,
    ends the walk and the vault is issued, so a path through a 0711 home still works."""
    from decoy_engine.fileaccess import _local

    h = base / "h"
    (h / "vaults").mkdir(parents=True)
    seen: list[str] = []
    real = _local._probe_dir  # type: ignore[attr-defined]
    top = os.path.realpath(h)

    def probe_dir(path: Any) -> os.stat_result:
        st = real(path)
        return restat(st, uid=os.geteuid() + 1) if os.path.realpath(path) == top else st

    monkeypatch.setattr(_local, "_probe_dir", probe_dir)
    out, _ = vault_out("ambient", base, f"h/vaults/{LEAF}")
    deny_reads(monkeypatch, h, seen)
    rec = Recorder(monkeypatch)
    probe = IssueProbe(monkeypatch, rec.synced)
    commit = writer().publish(out)
    assert seen and probe.issued == [commit]  # non-vacuity: the walk met the unreadable `h`
    assert stat.S_ISREG(os.lstat(h / "vaults" / LEAF).st_mode)
