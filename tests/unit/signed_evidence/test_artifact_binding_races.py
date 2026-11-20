"""AT-E4 added cells: the rooted artifact reader and the two verifier routes.

The original ``test_filesystem_binding.py`` comes from the gated PR unchanged. These cells cover what
the move onto the engine file-access layer adds: a changed-during-read check, a rooted re-open,
fail-closed enumeration, a missing or linked ``artifacts/``, root and bundle refusals, and the
path/capability split.
"""

from __future__ import annotations

import inspect
import json
import os
import shutil
import time
from pathlib import Path

import pytest

from decoy_engine import fileaccess
from decoy_engine.fileaccess import FileAccessUnavailable, RootedFileAccess
from decoy_engine.fileaccess._openat2 import openat2_usable
from decoy_engine.signed_evidence import (
    ArtifactStatus,
    ExitClass,
    Purpose,
    SignedEvidenceError,
    open_signed_bundle,
    verify_signed_bundle,
    verify_signed_evidence,
)
from decoy_engine.signed_evidence import _artifacts as art
from tests.unit.signed_evidence import _bundles
from tests.unit.signed_evidence import _factory as f

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX file semantics")

CUSTOMERS = "outputs/customers.csv"


@pytest.fixture
def bundle(tmp_path: Path):
    return _bundles.make_bundle(tmp_path)


def _by_path(root: Path, signed, policy, **over):  # type: ignore[no-untyped-def]
    return verify_signed_evidence(
        statement=signed.statement,
        signature=signed.signature,
        artifact_root=root,
        context=f.context(policy, **over),
    )


def _by_bundle(root: Path, policy, **over):  # type: ignore[no-untyped-def]
    with open_signed_bundle(root) as opened:
        return verify_signed_bundle(opened, context=f.context(policy, **over))


# -- the changed-during-read check --------------------------------------------------------------


def _patch_first_chunk(monkeypatch: pytest.MonkeyPatch, action) -> None:  # type: ignore[no-untyped-def]
    real = art._read_chunk
    seen: list[int] = []

    def seam(fd: int) -> bytes:
        data = real(fd)
        if not seen:
            seen.append(fd)
            time.sleep(0.03)  # past the coarse timestamp tick, so ctime moves
            action()
        return data

    monkeypatch.setattr(art, "_read_chunk", seam)


def test_a_same_size_write_after_the_first_chunk_is_refused(bundle, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = bundle
    path = root / "artifacts" / CUSTOMERS

    def flip() -> None:
        data = bytearray(path.read_bytes())
        data[0] ^= 0x01
        with path.open("r+b") as fh:
            fh.write(bytes(data))

    _patch_first_chunk(monkeypatch, flip)
    result = _by_path(root / "artifacts", signed, policy)
    assert result.artifacts is ArtifactStatus.MISMATCH
    assert "ARTIFACT_CHANGED_DURING_READ" in result.reasons
    assert not result.exit_class.is_success


def test_a_same_size_write_that_restores_mtime_is_still_refused(bundle, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = bundle
    path = root / "artifacts" / CUSTOMERS
    before = path.stat()

    def flip_and_restore() -> None:
        data = bytearray(path.read_bytes())
        data[0] ^= 0x01
        with path.open("r+b") as fh:
            fh.write(bytes(data))
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    _patch_first_chunk(monkeypatch, flip_and_restore)
    result = _by_path(root / "artifacts", signed, policy)
    assert "ARTIFACT_CHANGED_DURING_READ" in result.reasons
    assert result.artifacts is ArtifactStatus.MISMATCH


def test_a_rename_over_between_the_second_fstat_and_the_reopen_is_refused(
    bundle, monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = bundle
    path = root / "artifacts" / CUSTOMERS
    twin = path.with_name("customers.twin")
    shutil.copy(path, twin)

    def swap() -> None:
        if twin.exists():  # the seam runs once per artifact; only the first swap is the race
            os.replace(twin, path)

    monkeypatch.setattr(art, "_before_reopen", swap)
    result = _by_path(root / "artifacts", signed, policy)
    assert result.artifacts is ArtifactStatus.MISMATCH
    assert "ARTIFACT_CHANGED_DURING_READ" in result.reasons


def test_an_untouched_tree_still_matches_through_the_seams(bundle) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = bundle
    assert _by_path(root / "artifacts", signed, policy).exit_class is ExitClass.OK


# -- links, FIFOs and a missing or linked artifacts/ ---------------------------------------------


@pytest.mark.parametrize("route", ["path", "bundle"])
def test_a_symlinked_artifact_is_unavailable_not_missing(bundle, tmp_path, route) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = bundle
    outside = tmp_path / "outside.csv"
    shutil.copy(root / "artifacts" / CUSTOMERS, outside)
    (root / "artifacts" / CUSTOMERS).unlink()
    (root / "artifacts" / CUSTOMERS).symlink_to(outside)
    r = (
        _by_path(root / "artifacts", signed, policy)
        if route == "path"
        else _by_bundle(root, policy)
    )
    assert r.artifacts is ArtifactStatus.UNAVAILABLE
    assert "ARTIFACT_PATH_UNSAFE" in r.reasons and r.exit_class is ExitClass.INCOMPLETE


def test_a_fifo_is_unavailable(bundle) -> None:  # type: ignore[no-untyped-def]
    root, _, _, policy = bundle
    p = root / "artifacts" / "outputs" / "quarantine.ndjson"
    p.unlink()
    os.mkfifo(p)
    r = _by_bundle(root, policy)
    assert r.artifacts is ArtifactStatus.UNAVAILABLE and "ARTIFACT_NOT_REGULAR_FILE" in r.reasons


def test_a_missing_artifacts_directory_is_a_result_with_every_artifact_missing(bundle) -> None:  # type: ignore[no-untyped-def]
    root, _, _, policy = bundle
    shutil.rmtree(root / "artifacts")
    r = _by_bundle(root, policy)
    assert r.artifacts is ArtifactStatus.MISSING and "ARTIFACT_MISSING" in r.reasons
    assert {a.status for a in r.artifact_results} == {ArtifactStatus.MISSING}
    assert r.exit_class is ExitClass.INCOMPLETE


def test_a_symlinked_artifacts_directory_is_unavailable(bundle, tmp_path) -> None:  # type: ignore[no-untyped-def]
    root, _, _, policy = bundle
    real = tmp_path / "elsewhere"
    shutil.move(root / "artifacts", real)
    (root / "artifacts").symlink_to(real, target_is_directory=True)
    r = _by_bundle(root, policy)
    assert r.artifacts is ArtifactStatus.UNAVAILABLE and not r.exit_class.is_success
    assert {a.status for a in r.artifact_results} == {ArtifactStatus.UNAVAILABLE}


def test_a_regular_file_in_place_of_artifacts_is_unavailable(bundle) -> None:  # type: ignore[no-untyped-def]
    root, _, _, policy = bundle
    shutil.rmtree(root / "artifacts")
    (root / "artifacts").write_text("not a directory")
    r = _by_bundle(root, policy)
    assert r.artifacts is ArtifactStatus.UNAVAILABLE and not r.exit_class.is_success


# -- the root of each route -----------------------------------------------------------------------


def test_a_missing_path_form_root_is_missing_and_a_file_root_is_unavailable(
    bundle, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = bundle
    missing = _by_path(tmp_path / "nope", signed, policy)
    assert missing.artifacts is ArtifactStatus.MISSING and "ARTIFACT_MISSING" in missing.reasons
    afile = tmp_path / "afile"
    afile.write_text("x")
    wrong = _by_path(afile, signed, policy)
    assert wrong.artifacts is ArtifactStatus.UNAVAILABLE
    assert "ARTIFACT_NOT_REGULAR_FILE" in wrong.reasons


def test_open_signed_bundle_refuses_a_missing_root_and_a_file_root(tmp_path) -> None:
    with pytest.raises(SignedEvidenceError) as missing:
        open_signed_bundle(tmp_path / "nope")
    assert missing.value.code == "BUNDLE_ROOT_MISSING"
    (tmp_path / "afile").write_text("x")
    with pytest.raises(SignedEvidenceError) as wrong:
        open_signed_bundle(tmp_path / "afile")
    assert wrong.value.code == "BUNDLE_ROOT_NOT_DIRECTORY"
    for err in (missing.value, wrong.value):
        assert err.__cause__ is None and err.__context__ is None
        assert str(tmp_path) not in str(err)


def test_a_symlinked_bundle_root_is_followed_because_the_caller_named_it(bundle, tmp_path) -> None:  # type: ignore[no-untyped-def]
    root, _, _, policy = bundle
    link = tmp_path / "link-to-bundle"
    link.symlink_to(root, target_is_directory=True)
    assert _by_bundle(link, policy).exit_class is ExitClass.OK


# -- one trust class per entry --------------------------------------------------------------------


def test_each_entry_takes_only_its_own_kind_of_input(bundle) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = bundle
    ctx = f.context(policy)
    with open_signed_bundle(root) as opened:
        with pytest.raises(SignedEvidenceError):
            verify_signed_evidence(
                statement=signed.statement,
                signature=signed.signature,
                artifact_root=opened,  # type: ignore[arg-type]
                context=ctx,
            )
    with pytest.raises(SignedEvidenceError):
        verify_signed_bundle(root, context=ctx)  # type: ignore[arg-type]
    assert "artifact_root" in inspect.signature(verify_signed_evidence).parameters
    assert "artifact_root" not in inspect.signature(verify_signed_bundle).parameters


def test_the_two_routes_agree_on_one_tree(bundle) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = bundle
    by_path = _by_path(root / "artifacts", signed, policy)
    by_bundle = _by_bundle(root, policy)
    for name in ("exit_class", "artifacts", "signature", "trust", "checks", "identity", "reasons"):
        assert getattr(by_path, name) == getattr(by_bundle, name), name
    assert by_path.artifact_results == by_bundle.artifact_results


@pytest.mark.skipif(not openat2_usable(), reason="strict policy needs Linux openat2")
def test_a_strict_policy_refuses_both_routes_before_any_open(bundle, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = bundle
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        strict = RootedFileAccess(
            [fileaccess.Root("t", fd, frozenset({fileaccess.FileRole.CONFIG}))]
        )
        opened: list[object] = []
        real_open = os.open
        monkeypatch.setattr(os, "open", lambda *a, **k: opened.append(a) or real_open(*a, **k))
        with fileaccess.scope(strict):
            with pytest.raises(FileAccessUnavailable):
                open_signed_bundle(root)
            with pytest.raises(FileAccessUnavailable):
                _by_path(root / "artifacts", signed, policy)
        assert opened == []
    finally:
        os.close(fd)


# -- descriptors ------------------------------------------------------------------------------------


@pytest.mark.parametrize("breakage", ["symlink", "fifo", "missing", "mismatch"])
def test_no_descriptor_leaks_on_any_refusal(bundle, tmp_path, breakage) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = bundle
    p = root / "artifacts" / CUSTOMERS
    if breakage == "symlink":
        outside = tmp_path / "o.csv"
        shutil.copy(p, outside)
        p.unlink()
        p.symlink_to(outside)
    elif breakage == "fifo":
        p.unlink()
        os.mkfifo(p)
    elif breakage == "missing":
        p.unlink()
    else:
        p.write_bytes(b"different")
    _by_bundle(root, policy)  # warm any lazy import before counting
    before = _bundles.open_fd_count()
    for _ in range(3):
        _by_bundle(root, policy)
        _by_path(root / "artifacts", signed, policy)
    assert _bundles.open_fd_count() == before


# -- enumeration: fail closed, bounded --------------------------------------------------------------


@pytest.mark.skipif(
    os.geteuid() == 0, reason="root bypasses file modes; the forked variant covers it"
)
def test_an_unreadable_subdirectory_fails_enumeration_closed(bundle) -> None:  # type: ignore[no-untyped-def]
    root, _, _, policy = bundle
    sub = root / "artifacts" / "outputs" / "hidden"
    sub.mkdir()
    (sub / "extra.bin").write_bytes(b"x")
    sub.chmod(0)
    try:
        r = _by_bundle(root, policy)
    finally:
        sub.chmod(0o755)
    assert "ARTIFACT_ENUMERATION_FAILED" in r.reasons
    assert r.artifacts is not ArtifactStatus.MATCH and not r.exit_class.is_success


@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")
@pytest.mark.skipif(os.geteuid() != 0, reason="drops privileges from root")
def test_an_unreadable_subdirectory_fails_enumeration_closed_as_nobody() -> None:
    import tempfile

    base = Path(tempfile.mkdtemp(prefix="f33-enum-"))
    try:
        base.chmod(0o755)
        root, _, _, policy = _bundles.make_bundle(base)
        for p in [root, *root.rglob("*")]:
            p.chmod(0o755 if p.is_dir() else 0o644)
        sub = root / "artifacts" / "outputs" / "hidden"
        sub.mkdir()
        (sub / "extra.bin").write_bytes(b"x")
        sub.chmod(0)
        _by_bundle(root, policy)  # warm lazy imports while still root
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:  # pragma: no cover - runs in the child
            code = 1
            try:
                os.close(read_fd)
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)
                r = _by_bundle(root, policy)
                os.write(
                    write_fd,
                    json.dumps({"a": r.artifacts.name, "r": list(r.reasons)}).encode(),
                )
                code = 0
            finally:
                os._exit(code)
        os.close(write_fd)
        with os.fdopen(read_fd, "rb") as fh:
            payload = fh.read()
        _, status = os.waitpid(pid, 0)
        assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
        out = json.loads(payload)
        assert "ARTIFACT_ENUMERATION_FAILED" in out["r"] and out["a"] != "MATCH"
    finally:
        for p in [*base.rglob("*"), base]:
            if p.exists() and not p.is_symlink():
                p.chmod(0o755 if p.is_dir() else 0o644)
        shutil.rmtree(base, ignore_errors=True)


def test_the_entry_limit_refuses(bundle, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    root, _, _, policy = bundle
    for i in range(5):
        (root / "artifacts" / f"extra{i}.bin").write_bytes(b"x")
    monkeypatch.setattr(art, "MAX_TREE_ENTRIES", 3)
    r = _by_bundle(root, policy)
    assert "ARTIFACT_TREE_TOO_LARGE" in r.reasons or "ARTIFACT_UNBOUND_FILE" in r.reasons
    assert r.artifacts is not ArtifactStatus.MATCH


def test_the_depth_limit_refuses(bundle, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    root, _, _, policy = bundle
    deep = root / "artifacts" / "d1" / "d2" / "d3" / "d4"
    deep.mkdir(parents=True)
    (deep / "x.bin").write_bytes(b"x")
    monkeypatch.setattr(art, "MAX_TREE_DEPTH", 2)
    r = _by_bundle(root, policy)
    assert "ARTIFACT_TREE_TOO_LARGE" in r.reasons
    assert r.artifacts is not ArtifactStatus.MATCH


def test_the_signed_length_is_checked_before_any_read(bundle, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = bundle
    path = root / "artifacts" / CUSTOMERS
    path.write_bytes(path.read_bytes() + b"more")
    changed_size = path.stat().st_size
    real_read = art._read_chunk

    def guarded(fd: int) -> bytes:
        if os.fstat(fd).st_size == changed_size:
            pytest.fail("read before the length check")
        return real_read(fd)

    monkeypatch.setattr(art, "_read_chunk", guarded)
    r = _by_path(root / "artifacts", signed, policy)
    assert "ARTIFACT_LENGTH_MISMATCH" in r.reasons


def test_the_platform_guard_runs_before_any_open(bundle, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = bundle
    monkeypatch.setattr(art, "_POSIX", False)
    monkeypatch.setattr(
        fileaccess,
        "open_ambient_tree",
        lambda *_a, **_k: pytest.fail("an opener ran on an unsupported platform"),
    )
    with pytest.raises(SignedEvidenceError) as caught:
        open_signed_bundle(root)
    assert caught.value.code == "ARTIFACT_PLATFORM_UNSUPPORTED"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    with pytest.raises(SignedEvidenceError) as path_form:
        _by_path(root / "artifacts", signed, policy)
    assert path_form.value.code == "ARTIFACT_PLATFORM_UNSUPPORTED"
    # A signature-only diagnostic opens nothing, so it is not refused.
    result = verify_signed_evidence(
        statement=signed.statement,
        signature=signed.signature,
        artifact_root=None,
        context=f.context(policy, purpose=Purpose.RELEASE_GATE),
    )
    assert result.artifacts is ArtifactStatus.NOT_EVALUATED


def test_a_str_signature_is_input_invalid_not_a_type_error(bundle) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = bundle
    with pytest.raises(SignedEvidenceError) as caught:
        verify_signed_evidence(
            statement=signed.statement,
            signature="not bytes",  # type: ignore[arg-type]
            artifact_root=root / "artifacts",
            context=f.context(policy),
        )
    assert caught.value.code == "INPUT_INVALID"
