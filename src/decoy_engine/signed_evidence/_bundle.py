"""The signed evidence bundle: one held directory, two bounded member reads, one capability.

Pattern: rooted no-follow reads under a held directory descriptor (cap-std and Go os.Root; Linux
openat2 RESOLVE_BENEATH; CERT FIO45-C).

A bundle is a directory holding ``evidence.json`` (the statement), ``evidence.sig.json`` (the
detached signature) and an ``artifacts`` directory. ``open_signed_bundle`` opens that directory
once under the ambient policy and reads both members through the held handle, so a later swap of
the path cannot redirect either read. It does not open ``artifacts``: the verifier does, through
``SignedBundle.open_artifacts``, confined beneath the same handle.

``SignedBundle`` is the capability ``verify_signed_bundle`` accepts. Only this module builds one (a
construction token, as the signing carrier does), so a caller cannot hand the verifier a path
dressed as a bundle, and the path form and the capability form stay separate routes.

Every refusal records only a closed identity inside its ``except`` and raises after the block, so no
member name, path, lower exception text, ``__cause__`` or ``__context__`` reaches the error.
"""

from __future__ import annotations

import os
from typing import Any

from decoy_engine import fileaccess
from decoy_engine.fileaccess import DirHandle, FileAccessDenied
from decoy_engine.reasons import ReasonCode
from decoy_engine.reasons import evidence as ev

from ._artifacts import require_supported_platform
from ._envelope import MAX_ENVELOPE_BYTES
from ._errors import SignedEvidenceError
from ._strict_json import MAX_BYTES

EVIDENCE_FILENAME = "evidence.json"
SIGNATURE_FILENAME = "evidence.sig.json"
ARTIFACTS_DIRNAME = "artifacts"

MAX_STATEMENT_BYTES = MAX_BYTES
MAX_SIGNATURE_BYTES = MAX_ENVELOPE_BYTES

_TOKEN = object()


class SignedBundle:
    """A held bundle directory plus the statement and signature bytes read from it."""

    __slots__ = ("_root", "signature", "statement")

    def __init__(self, token: object, root: DirHandle, statement: bytes, signature: bytes) -> None:
        if token is not _TOKEN:
            raise SignedEvidenceError(ev.BUNDLE_CONSTRUCTION_FORBIDDEN)
        self._root = root
        self.statement = statement
        self.signature = signature

    def open_artifacts(self) -> DirHandle:
        """The ``artifacts`` directory, opened confined beneath the held bundle handle."""
        return self._root.open_dir(ARTIFACTS_DIRNAME)

    def close(self) -> None:
        self._root.close()

    def __enter__(self) -> SignedBundle:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __reduce__(self) -> Any:
        raise TypeError("a signed bundle holds an open directory and is not serialisable")


def _read_member(root: DirHandle, name: str, limit: int) -> bytes:
    """One member through the held handle, bounded, with only a closed identity on refusal."""
    refusal: ReasonCode | None = None
    data = b""
    try:
        with root.open_file(name) as member:
            data = member.read_all(limit + 1)
    except FileAccessDenied as denial:
        refusal = (
            ev.BUNDLE_MEMBER_MISSING if denial.kind == "absent" else ev.BUNDLE_MEMBER_UNAVAILABLE
        )
    except OSError:
        refusal = ev.BUNDLE_MEMBER_UNAVAILABLE
    if refusal is not None:
        raise SignedEvidenceError(refusal)
    if len(data) > limit:
        raise SignedEvidenceError(ev.INPUT_TOO_LARGE)
    return data


def open_signed_bundle(path: str | os.PathLike[str]) -> SignedBundle:
    """Open the bundle directory ``path`` once and read its statement and signature."""
    require_supported_platform()
    root: DirHandle | None = None
    refusal: ReasonCode | None = None
    try:
        root = fileaccess.open_ambient_tree(path)
    except FileAccessDenied as denial:
        refusal = {
            "absent": ev.BUNDLE_ROOT_MISSING,
            "not_regular": ev.BUNDLE_ROOT_NOT_DIRECTORY,
        }.get(denial.kind or "", ev.INPUT_UNAVAILABLE)
    if root is None:
        raise SignedEvidenceError(refusal or ev.INPUT_UNAVAILABLE)
    failed: ReasonCode | None = None
    statement = signature = b""
    try:
        statement = _read_member(root, EVIDENCE_FILENAME, MAX_STATEMENT_BYTES)
        signature = _read_member(root, SIGNATURE_FILENAME, MAX_SIGNATURE_BYTES)
    except SignedEvidenceError as error:
        failed = error.identity
    if failed is not None:
        root.close()
        raise SignedEvidenceError(failed)
    return SignedBundle(_TOKEN, root, statement, signature)
