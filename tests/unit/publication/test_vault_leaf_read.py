"""One shared vault-leaf reader for adoption and the republish check (F22 5.5 step 2, M1).

`read_vault_leaf` classifies what `adopt_file` returns or raises, and the two callers only map
the result to their own codes. The structural errnos (`ELOOP`, `EINVAL`, `ENOTDIR`, `EISDIR`)
are a leaf that cannot be adopted, not an fsync failure: a republish refuses with
`publication_vault_mismatch` and an adopt with `publication_vault_conflict`, never
`commit_uncertain` or `vault_commit_failed`. Other errnos keep the fsync-failure mapping.
"""

from __future__ import annotations

import errno
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from decoy_engine import reasons
from decoy_engine.fileaccess import LeafTooLarge
from decoy_engine.publication import _vault_order
from decoy_engine.vault import VaultError
from tests.fileaccess.publication._chain_support import anchor_at
from tests.fileaccess.publication._dirmode_support import POLICIES
from tests.fileaccess.publication._vault_support import ROWS, vault_out, writer
from tests.unit.publication._vault_publish_support import (
    OUT_REL,
    VAULT_REL,
    close_all,
    prepare,
    publish,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX durable vault")

STRUCTURAL = ("ELOOP", "EINVAL", "ENOTDIR", "EISDIR")
FSYNC = ("EIO", "ENOSPC", "EDQUOT")


class _Stub:
    def __init__(self, result: Any) -> None:
        self._result = result

    def adopt_file(self, *, limit: int) -> bytes | None:
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


@pytest.mark.parametrize(
    ("result", "kind", "arg"),
    [
        (b"abc", "bytes", None),
        (None, "Absent", None),
        (LeafTooLarge(errno.EFBIG), "TooLarge", None),
        *[(OSError(getattr(errno, n), n), "Unadoptable", None) for n in STRUCTURAL],
        *[(OSError(getattr(errno, n), n), "FsyncFailed", n) for n in FSYNC],
        (OSError(), "FsyncFailed", "EIO"),
    ],
)
def test_read_vault_leaf_classifies(result: Any, kind: str, arg: str | None) -> None:
    got = _vault_order.read_vault_leaf(_Stub(result), 10)  # type: ignore[arg-type]
    if kind == "bytes":
        assert got == b"abc"
    elif arg is None:
        assert got == getattr(_vault_order, kind)()
    else:
        assert got == getattr(_vault_order, kind)(arg)


def _raiser(name: str) -> Any:
    def adopt_file(self: Any, *, limit: int) -> bytes | None:
        raise OSError(getattr(errno, name), os.strerror(getattr(errno, name)))

    return adopt_file


def _root(tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "root"
    prepare(base)
    if policy == "ambient":
        anchor_at(monkeypatch, base)
    return base


@pytest.mark.parametrize("name", STRUCTURAL + FSYNC)
@pytest.mark.parametrize("policy", POLICIES)
def test_republish_maps_leaf_read_result(
    tmp_path: Path, policy: str, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _root(tmp_path, policy, monkeypatch)
    first, fds = publish(policy, base, "one", "op-1")
    close_all(fds)
    assert first.outcome == "published"
    vout, vfd = vault_out(policy, base, VAULT_REL)
    monkeypatch.setattr(type(vout), "adopt_file", _raiser(name))
    close_all([vfd])
    receipt, fds = publish(policy, base, "one", "op-1")
    close_all(fds)
    assert receipt.result_id == first.result_id  # non-vacuity: D3 decided
    if name in STRUCTURAL:
        assert (receipt.outcome, receipt.reason_code) == ("refused", "publication_vault_mismatch")
    else:
        assert (receipt.outcome, receipt.reason_code, receipt.os_error) == (
            "commit_uncertain",
            "publication_commit_uncertain",
            name,
        )


@pytest.mark.parametrize("name", STRUCTURAL + FSYNC)
@pytest.mark.parametrize("policy", POLICIES)
def test_adopt_maps_leaf_read_result(
    tmp_path: Path, policy: str, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _root(tmp_path, policy, monkeypatch)
    vout, vfd = vault_out(policy, base, VAULT_REL)
    writer(ROWS).publish(vout)  # a vault already at the leaf: `vault_exists` reaches adopt
    close_all([vfd])
    monkeypatch.setattr(type(vout), "adopt_file", _raiser(name))
    if name in STRUCTURAL:
        receipt, fds = publish(policy, base, "one", "op-1")
        close_all(fds)
        assert (receipt.outcome, receipt.reason_code) == ("refused", "publication_vault_conflict")
        assert not (base / OUT_REL).exists()
    else:
        with pytest.raises(VaultError) as caught:
            _, fds = publish(policy, base, "one", "op-1")
        assert caught.value.code == reasons.runtime.VAULT_COMMIT_FAILED
        assert not (base / OUT_REL).exists()
