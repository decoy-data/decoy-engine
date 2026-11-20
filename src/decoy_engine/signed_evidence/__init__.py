"""Signed evidence: detached ES256 JWS over a JCS statement, with offline verification (F33).

Public surface: the verifier entries (the path form and the bundle capability form), the pinned
expectations loader, the typed inputs and results, and the signer side. The low-level ES256 check
is private by design; see ``_verifier``. The package sits in the engine's ``signed_evidence``
layer and imports only the engine's ``_canonical``, ``_error_base``, ``reasons`` and
``fileaccess`` owners, the standard library, ``joserfc``, ``rfc8785`` (through ``_canonical``) and
``cryptography``.

Plan: docs/plans/2026-11-17-f33-v1.md.
"""

from __future__ import annotations

from ._boundary import sign_evidence
from ._bundle import (
    EVIDENCE_FILENAME,
    MAX_SIGNATURE_BYTES,
    MAX_STATEMENT_BYTES,
    SIGNATURE_FILENAME,
    SignedBundle,
    open_signed_bundle,
)
from ._catalog import RequiredCatalog
from ._context import ExpectedArtifact, HistoricalDecision, Purpose, VerificationContext
from ._errors import SignedEvidenceError
from ._expectations import MAX_EXPECTATIONS_BYTES, Expectations, parse_expectations
from ._result import (
    ArtifactStatus,
    CheckStatus,
    ExitClass,
    HistoricalAuthorization,
    IdentityBinding,
    ReleaseVerdict,
    SchemaStatus,
    SignatureStatus,
    TrustStatus,
    VerificationResult,
)
from ._signer import LocalEs256Signer, SigningIdentity, der_to_p1363
from ._trust import MAX_POLICY_BYTES, TrustPolicy
from ._verifier import verify_signed_bundle, verify_signed_evidence

__all__ = [
    "EVIDENCE_FILENAME",
    "MAX_EXPECTATIONS_BYTES",
    "MAX_POLICY_BYTES",
    "MAX_SIGNATURE_BYTES",
    "MAX_STATEMENT_BYTES",
    "SIGNATURE_FILENAME",
    "ArtifactStatus",
    "CheckStatus",
    "ExitClass",
    "Expectations",
    "ExpectedArtifact",
    "HistoricalAuthorization",
    "HistoricalDecision",
    "IdentityBinding",
    "LocalEs256Signer",
    "Purpose",
    "ReleaseVerdict",
    "RequiredCatalog",
    "SchemaStatus",
    "SignatureStatus",
    "SignedBundle",
    "SignedEvidenceError",
    "SigningIdentity",
    "TrustPolicy",
    "TrustStatus",
    "VerificationContext",
    "VerificationResult",
    "der_to_p1363",
    "open_signed_bundle",
    "parse_expectations",
    "sign_evidence",
    "verify_signed_bundle",
    "verify_signed_evidence",
]
