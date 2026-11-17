"""The pinned expectations document: what the verifier is told to expect, never what the bundle says.

Pattern: a digest-pinned trust root (TUF, Sigstore): the operator pins the document's SHA-256 out of
band, and ``parse_expectations`` checks it before any parse, with the same helper the trust policy
loader uses. The document is then read through the engine's one strict reader and declared once as a
``_strict_spec`` shape, so a missing member, an unknown member, a ``bool`` where an integer goes or
a trailing newline in an id is refused with a closed token and no input text.

``Expectations.context`` is the one builder of a ``VerificationContext`` from this document. Nothing
else supplies a context value, so a flag or a bundle member can never loosen what is checked.

This is ``expectations`` version 1, frozen with the platform writer contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from decoy_engine._canonical import (
    CountSpec,
    JcsError,
    ListSpec,
    NullableSpec,
    ObjectSpec,
    ShapedSpec,
    SpecRefusedError,
    VersionSpec,
    attempt,
    jcs_bytes,
)
from decoy_engine.reasons import ReasonCode
from decoy_engine.reasons import evidence as ev

from . import _strict_json as sj
from ._catalog import RequiredCatalog
from ._context import ExpectedArtifact, Purpose, VerificationContext
from ._errors import SignedEvidenceError
from ._trust import TrustPolicy, _pin_verdict

MAX_EXPECTATIONS_BYTES = sj.MAX_BYTES

_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"
_SHA_PATTERN = r"[0-9a-f]{64}"
_MEDIA_PATTERN = r"[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}"
_ID = re.compile(_ID_PATTERN)
_SHA = re.compile(_SHA_PATTERN)
_MEDIA = re.compile(_MEDIA_PATTERN)


@dataclass(frozen=True, slots=True)
class _ArtifactDoc:
    id: str
    sha256: str
    media_type: str


@dataclass(frozen=True, slots=True)
class _Doc:
    v: int
    tenant: str
    job_id: str
    attempt_id: str
    bundle_id: str
    snapshot_id: str | None
    artifacts: tuple[_ArtifactDoc, ...]
    unbound_outputs: int
    catalog: RequiredCatalog


@dataclass(frozen=True)
class _CatalogSpec:
    """The nested ``catalog`` member: read through the one required-catalog loader."""

    def load(self, raw: Any) -> RequiredCatalog:
        loaded: RequiredCatalog | None = None
        try:
            loaded = RequiredCatalog.from_bytes(jcs_bytes(raw))
        except (SignedEvidenceError, JcsError):
            loaded = None
        if loaded is None:
            raise SpecRefusedError("bad_token")
        return loaded

    def dump(self, value: Any) -> Any:
        return value

    def describe(self) -> str:
        return "required_catalog"


# One literal row per strict-reader code, so every raise names a registered identity.
_WIRE: dict[ReasonCode, ReasonCode] = {
    ev.BOM: ev.EXPECTATIONS_BOM,
    ev.DUPLICATE_MEMBER: ev.EXPECTATIONS_DUPLICATE_MEMBER,
    ev.FLOAT_NOT_ALLOWED: ev.EXPECTATIONS_FLOAT_NOT_ALLOWED,
    ev.INTEGER_OUT_OF_DOMAIN: ev.EXPECTATIONS_INTEGER_OUT_OF_DOMAIN,
    ev.INVALID_UNICODE: ev.EXPECTATIONS_INVALID_UNICODE,
    ev.NON_FINITE_NUMBER: ev.EXPECTATIONS_NON_FINITE_NUMBER,
    ev.NOT_JSON: ev.EXPECTATIONS_NOT_JSON,
    ev.NOT_UTF8: ev.EXPECTATIONS_NOT_UTF8,
    ev.TOO_DEEP: ev.EXPECTATIONS_TOO_DEEP,
    ev.TOO_LARGE: ev.EXPECTATIONS_TOO_LARGE,
    ev.TOO_MANY_NODES: ev.EXPECTATIONS_TOO_MANY_NODES,
}

#: One registered identity per closed spec check (``SpecCheck``), so a refusal names no input.
_SPEC_REFUSALS: dict[str, ReasonCode] = {
    "schema_unknown": ev.EXPECTATIONS_SCHEMA_UNKNOWN,
    "missing_field": ev.EXPECTATIONS_MISSING_FIELD,
    "unknown_field": ev.EXPECTATIONS_UNKNOWN_FIELD,
    "wrong_type": ev.EXPECTATIONS_WRONG_TYPE,
    "out_of_range": ev.EXPECTATIONS_OUT_OF_RANGE,
    "bad_token": ev.EXPECTATIONS_BAD_TOKEN,
    "bad_path": ev.EXPECTATIONS_BAD_PATH,
}

_SPEC = ObjectSpec(
    _Doc,
    (
        ("v", VersionSpec(1)),
        ("tenant", ShapedSpec(_ID_PATTERN, lambda s: bool(_ID.fullmatch(s)))),
        ("job_id", ShapedSpec(_ID_PATTERN, lambda s: bool(_ID.fullmatch(s)))),
        ("attempt_id", ShapedSpec(_ID_PATTERN, lambda s: bool(_ID.fullmatch(s)))),
        ("bundle_id", ShapedSpec(_ID_PATTERN, lambda s: bool(_ID.fullmatch(s)))),
        (
            "snapshot_id",
            NullableSpec(ShapedSpec(_ID_PATTERN, lambda s: bool(_ID.fullmatch(s)))),
        ),
        (
            "artifacts",
            ListSpec(
                ObjectSpec(
                    _ArtifactDoc,
                    (
                        ("id", ShapedSpec(_ID_PATTERN, lambda s: bool(_ID.fullmatch(s)))),
                        ("sha256", ShapedSpec(_SHA_PATTERN, lambda s: bool(_SHA.fullmatch(s)))),
                        (
                            "media_type",
                            ShapedSpec(_MEDIA_PATTERN, lambda s: bool(_MEDIA.fullmatch(s))),
                        ),
                    ),
                )
            ),
        ),
        ("unbound_outputs", CountSpec(sj.MAX_SAFE_INT)),
        ("catalog", _CatalogSpec()),
    ),
)


@dataclass(frozen=True, slots=True)
class Expectations:
    """The parsed, pinned expectations. Build a context with ``context``, never by hand."""

    tenant: str
    job_id: str
    attempt_id: str
    bundle_id: str
    snapshot_id: str | None
    artifacts: tuple[ExpectedArtifact, ...]
    unbound_outputs: int
    catalog: RequiredCatalog

    def context(self, trust_policy: TrustPolicy, purpose: Purpose) -> VerificationContext:
        return VerificationContext(
            purpose=purpose,
            trust_policy=trust_policy,
            required_catalog=self.catalog,
            expected_tenant=self.tenant,
            expected_bundle_id=self.bundle_id,
            expected_job_id=self.job_id,
            expected_attempt_id=self.attempt_id,
            expected_snapshot_id=self.snapshot_id,
            expected_artifacts=self.artifacts,
            expected_unbound_outputs=self.unbound_outputs,
        )


def parse_expectations(raw: bytes, *, pinned_sha256: str) -> Expectations:
    """Load the expectations only if their digest equals the pin, then read them strictly."""
    verdict, _ = _pin_verdict(raw, pinned_sha256)
    if verdict == "invalid":
        raise SignedEvidenceError(ev.EXPECTATIONS_PIN_INVALID)
    if verdict == "mismatch":
        raise SignedEvidenceError(ev.EXPECTATIONS_DIGEST_MISMATCH)
    inner: ReasonCode | None = None
    doc: Any = None
    try:
        doc = sj.parse_strict(raw, max_bytes=MAX_EXPECTATIONS_BYTES)
    except SignedEvidenceError as exc:
        inner = exc.identity
    if inner is not None:
        raise SignedEvidenceError(_WIRE[inner])
    loaded, check = attempt(_SPEC.load, doc)
    if check is not None:
        raise SignedEvidenceError(_SPEC_REFUSALS[check])
    ids = [a.id for a in loaded.artifacts]
    if not ids:
        raise SignedEvidenceError(ev.EXPECTATIONS_ARTIFACTS_EMPTY)
    if len(set(ids)) != len(ids):
        raise SignedEvidenceError(ev.EXPECTATIONS_ARTIFACT_ID_DUPLICATE)
    return Expectations(
        tenant=loaded.tenant,
        job_id=loaded.job_id,
        attempt_id=loaded.attempt_id,
        bundle_id=loaded.bundle_id,
        snapshot_id=loaded.snapshot_id,
        artifacts=tuple(
            ExpectedArtifact(id=a.id, sha256="sha256:" + a.sha256, media_type=a.media_type)
            for a in loaded.artifacts
        ),
        unbound_outputs=loaded.unbound_outputs,
        catalog=loaded.catalog,
    )
