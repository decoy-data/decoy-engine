# Signed evidence and offline verification

**Status:** current for the engine-owned verifier (F33 V1, slices E1a and E1b). A signing CLI,
platform KMS, key lifecycle operations, the engine check ledger, the release staging coordinator and
a Windows implementation are not shipped; see [Scope of this release](#scope-of-this-release). The
plan is `docs/plans/2026-11-17-f33-v1.md`.

## What a signature does and does not say

A valid signature says a key the verifier was told to trust asserted this exact statement. It
does not say the detector was correct, the signer is honest, the output is private or the job
is compliant. **A valid signature is never a release pass.** Release also needs complete,
passing required checks evaluated against a catalog the verifier holds independently, artifacts
that match byte for byte, and identity that matches the request.

## Wire format

| Part | Definition |
|---|---|
| Statement | `EvidenceStatementV1`, a closed JSON schema (`decoy.evidence.statement/v1`), serialized as RFC 8785 (JCS) canonical bytes with no BOM and no trailing newline. The received bytes must equal the canonical form, otherwise the result is `NON_CANONICAL`. |
| Signature | A detached, flattened JWS (RFC 7515 section 7.2.2, Appendix F) with exactly `protected` and `signature`. No `payload`, `header` or `signatures`. |
| Algorithm | ES256 only (ECDSA P-256 with SHA-256). The signature is the fixed-width 64-byte R\|\|S form; DER, truncated and over-long encodings are rejected. Low-s canonicalisation is **not** enforced: standard JOSE accepts both forms and release binds to the statement digest, not to signature uniqueness. |
| Protected header | `alg`, `kid`, `typ` (`application/vnd.decoy.evidence-signature.v1+jws`), `cty` (`application/vnd.decoy.evidence.v1+json`), `crit` (exactly `decoy_signer` and `decoy_key_version`), `decoy_signer`, `decoy_key_version`. Any other member, including `jwk`, `jku`, `x5u`, `x5c` and `b64`, is refused. |
| Files | `evidence.json` (statement) and `evidence.sig.json` (signature object), next to `artifacts/`. `open_signed_bundle` reads both through one held directory handle. |

The statement carries no floating-point number. Counts are integers up to 2^53 - 1 and a
decimal string only beyond it, so every value has one spelling. Free text never enters a signed
field: reason codes, dispositions and metric names are closed vocabularies, metric values are
integers, booleans or canonical decimal strings, and exception messages, regexes, source values
and secret references are structurally unable to appear.

Verification is over the protected segment **exactly as transmitted**, never a re-serialisation,
and the header is parsed with duplicate-member rejection so a last-wins parser cannot disagree
with the signer.

## Trust

Nothing the verifier compares against comes from the bundle. A `VerificationContext` is the sole
source of trusted expectations: the trust policy (loaded only against an out-of-band pinned
SHA-256 digest), the required-check catalog, the expected tenant, job, attempt, snapshot and
artifact digests, the purpose and the evaluation time. A valid signature for one job therefore
cannot be replayed as evidence for another.

A trusted key binds signer, tenant, immutable key version and RFC 7638 thumbprint. The `kid` is
only a lookup hint.

| Purpose | Meaning |
|---|---|
| `RELEASE_GATE` | Authorizing a new release now. The signer must be `ACTIVE`. |
| `CONSUMER_ACCEPTANCE` | A recipient accepting an existing bundle. `RETIRED` (routine rotation) is accepted and reported as retired. |
| `HISTORICAL_AUDIT` | Inspecting past evidence. Never returns full success and never current clearance. |

Lifecycle keeps three questions apart. May this key sign now (`ACTIVE`)? May it still verify
(`ACTIVE` or `RETIRED`)? Has it been revoked or compromised (`REVOKED`)? Revocation changes the
trust answer, not the bytes: a revoked key's signature stays mathematically valid and is reported
as such. `created_at` is signer-asserted. It can refuse a claim (signed after revocation) but can
never grant history, because a compromised signer can backdate. Only an operator-supplied
decision bound to the exact statement and signature digests establishes
`historical_authorization` as `ESTABLISHED`. An expired or stale trust snapshot gives no current
clearance.

## Result dimensions

`verify_signed_evidence` (a caller-named artifact directory) and `verify_signed_bundle` (an
engine-issued `SignedBundle`) return independent dimensions, not one boolean: `schema`, `signature`,
`trust`, `artifacts`, `checks`, `identity`, `release`, `historical_authorization`, an `exit_class`
and the two distinct times (`created_at` as untrusted text, `evaluation_time` from the verifier's
own clock). Only `ExitClass.OK` is full success, and `release` is `ALLOW` exactly when the exit
class is `OK`. A signature-only run (no artifact root) can never be `OK`. Numeric process exit
codes are assigned by the CLI after it inspects its existing contract.

## Required checks

A check outcome is `PASS`, `FAIL`, `INCONCLUSIVE` or `NOT_APPLICABLE`. The expected set of
(check, subject) pairs is compiled from the verifier's own catalog and the caller's expected
artifacts, never from the results the producer included, so absent, duplicate and unknown
outcomes fail closed. A no-match `PASS` counts only with adequate machine-readable coverage: a
zero-row subject or a sample is `INCONCLUSIVE`. `NOT_APPLICABLE` needs a catalog rule. A catalog
with no required check is refused at load, and the statement's signed policy digest must equal
the verifier's catalog digest, so a producer cannot satisfy strict verification by signing a
smaller catalog. A required `INCONCLUSIVE` blocks release even with a valid signature.

## Artifact binding

Every delivered file is opened through the engine file-access layer: rooted, no-follow opens
beneath one held directory descriptor, with `fstat` on the same descriptor, and hashed from the
bytes read, with the signed length checked first. Symlinks, FIFOs, devices and directories in place
of files are refused (`UNAVAILABLE`, never `MISSING`). A file that changes while it is hashed
(size, `mtime` or `ctime` differ, or the same path now names another inode) is
`ARTIFACT_CHANGED_DURING_READ`. A listing error anywhere under the root is
`ARTIFACT_ENUMERATION_FAILED`, never a match. Extra files under the root are reported as unbound
and block release. Hashing is bounded and streaming. A filesystem with a coarse `ctime` can miss a
same-size write inside one tick.

The bundle form opens `artifacts/` beneath the held bundle handle, so a missing or symlinked
`artifacts/` is a verification result. The path form opens the caller's directory once under the
ambient file-access policy and follows a symlink only at the final component the caller named.

An expectations document (`expectations` version 1) supplies the trusted values. Its SHA-256 is
pinned out of band and checked before any parse, exactly as the trust policy's is. A count of
outputs the producer left unbound makes an otherwise complete verification `PARTIAL`.

## Signing and publication

`sign_evidence` is the only constructor of the signed carrier. It validates the draft before the
signer is consulted, resolves the signer identity exactly once, signs through the `ResolvedSigner`
seam, and **verifies its own output locally** against the signer's advertised public key before
returning, so a provider that returns a malformed, wrong-key, wrong-curve, DER or double-hashed
signature yields no carrier. A provider failure becomes `SIGNING_FAILED` with no provider text.
There is no unsigned fallback.

The carrier and the release permit refuse pickling and are guarded constructors, so a persisted
worker result or cache entry cannot be turned back into authority. Persist the two byte strings
and re-verify them with `adopt_verified_evidence`, which preserves the original bytes, signer and
key version and never re-signs history under today's key.

The seam is Sigstore's `Signer`/`PublicKeyProvider` split. A provider that emits DER (AWS KMS
`Sign` with `ECDSA_SHA_256` and `MessageType=DIGEST`) converts with `der_to_p1363`; AWS KMS
takes the SHA-256 of the full JOSE signing input exactly once.

The release permit and its deny-all default evaluator exist inside the package and are not
exported. There is no staging coordinator: no engine route writes a signed bundle yet.

## Platform support

The verifier is POSIX only for now. On a platform without `dir_fd` and `O_NOFOLLOW`, the two
filesystem entries refuse with `ARTIFACT_PLATFORM_UNSUPPORTED` before any open. The Windows chain is
a V1 follow-up.

## Scope of this release

Shipped here: the statement, envelope, canonicalisation and verifier core; the pinned expectations
loader; the bundle capability and both verifier entries; the signer seam with a local test signer;
the signing boundary; the independent conformance corpus.

Not shipped, and not claimed: no engine route writes a signed bundle; the engine does not yet record
per-detector completion; there is no signing CLI, platform KMS adapter, key rotation or revocation
tooling, or migration of legacy r3.1 evidence. The platform's existing `output-passport/v1`
Ed25519 signature is a different, operator-attested format; F33 neither uses nor replaces it.

## Conformance corpus

`tests/fixtures/signed_evidence/v1/` holds 129 vectors generated by an implementation
independent of the production verifier (Node: the RFC 8785 author's `canonicalize`, `jose`, and
OpenSSL through `node:crypto`). The corpus is frozen; its manifest records a digest per file, and
expected results are written from the contract, never regenerated from the code under test. Test
private keys under `keys/` are synthetic and must never be trusted by a real policy.
