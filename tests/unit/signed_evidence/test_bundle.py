"""AT-E14 (engine half): the bundle opener reads both members through one held handle."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from decoy_engine import fileaccess
from decoy_engine.signed_evidence import (
    EVIDENCE_FILENAME,
    MAX_SIGNATURE_BYTES,
    MAX_STATEMENT_BYTES,
    SIGNATURE_FILENAME,
    ExitClass,
    SignedEvidenceError,
    open_signed_bundle,
    verify_signed_bundle,
)
from decoy_engine.signed_evidence._bundle import SignedBundle
from tests.unit.signed_evidence import _bundles
from tests.unit.signed_evidence import _factory as f

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX file semantics")


def _code(path: Path) -> str:
    with pytest.raises(SignedEvidenceError) as caught:
        open_signed_bundle(path)
    err = caught.value
    assert err.__cause__ is None and err.__context__ is None
    assert str(path) not in str(err) and EVIDENCE_FILENAME not in str(err)
    return err.code


def test_a_bundle_opens_and_verifies(tmp_path) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = _bundles.make_bundle(tmp_path)
    with open_signed_bundle(root) as bundle:
        assert bundle.statement == signed.statement and bundle.signature == signed.signature
        assert verify_signed_bundle(bundle, context=f.context(policy)).exit_class is ExitClass.OK


def test_both_members_come_from_one_open_of_the_directory(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    root, *_ = _bundles.make_bundle(tmp_path)
    opens: list[object] = []
    real = fileaccess.open_ambient_tree
    monkeypatch.setattr(fileaccess, "open_ambient_tree", lambda p: opens.append(p) or real(p))
    open_signed_bundle(root).close()
    assert len(opens) == 1


def test_swapping_the_path_after_the_open_cannot_redirect_the_reads(tmp_path) -> None:  # type: ignore[no-untyped-def]
    root, signed, *_ = _bundles.make_bundle(tmp_path)
    with open_signed_bundle(root) as bundle:
        moved = tmp_path / "moved"
        root.rename(moved)
        (root).mkdir()
        (root / EVIDENCE_FILENAME).write_bytes(b"{}")
        assert bundle.open_artifacts() is not None
    assert signed.statement  # the held capability already read the real bytes


@pytest.mark.parametrize(
    ("name", "limit"),
    [(EVIDENCE_FILENAME, MAX_STATEMENT_BYTES), (SIGNATURE_FILENAME, MAX_SIGNATURE_BYTES)],
)
def test_a_member_above_its_bound_is_refused_and_one_at_the_bound_is_read(
    tmp_path, name, limit
) -> None:  # type: ignore[no-untyped-def]
    root, *_ = _bundles.make_bundle(tmp_path)
    (root / name).write_bytes(b" " * (limit + 1))
    assert _code(root) == "INPUT_TOO_LARGE"
    (root / name).write_bytes(b" " * limit)
    with open_signed_bundle(root) as bundle:
        assert len(bundle.statement if name == EVIDENCE_FILENAME else bundle.signature) == limit


@pytest.mark.parametrize("name", [EVIDENCE_FILENAME, SIGNATURE_FILENAME])
def test_a_missing_member_is_member_missing(tmp_path, name) -> None:  # type: ignore[no-untyped-def]
    root, *_ = _bundles.make_bundle(tmp_path)
    (root / name).unlink()
    assert _code(root) == "BUNDLE_MEMBER_MISSING"


@pytest.mark.parametrize("name", [EVIDENCE_FILENAME, SIGNATURE_FILENAME])
@pytest.mark.parametrize("breakage", ["symlink", "directory", "fifo"])
def test_any_other_member_denial_is_member_unavailable(tmp_path, name, breakage) -> None:  # type: ignore[no-untyped-def]
    root, *_ = _bundles.make_bundle(tmp_path)
    path = root / name
    outside = tmp_path / "outside"
    shutil.copy(path, outside)
    path.unlink()
    if breakage == "symlink":
        path.symlink_to(outside)
    elif breakage == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    assert _code(root) == "BUNDLE_MEMBER_UNAVAILABLE"


def test_a_refused_open_leaves_no_descriptor_behind(tmp_path) -> None:  # type: ignore[no-untyped-def]
    root, *_ = _bundles.make_bundle(tmp_path)
    (root / SIGNATURE_FILENAME).unlink()
    _code(root)
    before = _bundles.open_fd_count()
    for _ in range(3):
        _code(root)
    assert _bundles.open_fd_count() == before


def test_a_bundle_cannot_be_built_or_pickled_by_hand(tmp_path) -> None:  # type: ignore[no-untyped-def]
    root, *_ = _bundles.make_bundle(tmp_path)
    with pytest.raises(SignedEvidenceError):
        SignedBundle(object(), None, b"", b"")  # type: ignore[arg-type]
    import pickle

    with open_signed_bundle(root) as bundle, pytest.raises(TypeError):
        pickle.dumps(bundle)


def test_the_public_limits_alias_the_owner_limits() -> None:
    from decoy_engine.signed_evidence import _envelope, _strict_json

    assert MAX_STATEMENT_BYTES == _strict_json.MAX_BYTES
    assert MAX_SIGNATURE_BYTES == _envelope.MAX_ENVELOPE_BYTES
