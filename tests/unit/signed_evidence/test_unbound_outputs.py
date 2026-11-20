"""AT-E11: an unbound output count is an engine decision, and the context has one builder."""

from __future__ import annotations

import pytest

from decoy_engine.signed_evidence import (
    ExitClass,
    Purpose,
    SignedEvidenceError,
    VerificationContext,
    parse_expectations,
    verify_signed_evidence,
)
from decoy_engine.signed_evidence._verifier import _decide
from tests.unit.signed_evidence import _bundles
from tests.unit.signed_evidence import _expectations_doc as ed
from tests.unit.signed_evidence import _factory as f


@pytest.mark.parametrize(
    ("count", "exit_class"), [(0, ExitClass.OK), (1, ExitClass.PARTIAL), (7, ExitClass.PARTIAL)]
)
def test_the_count_decides_ok_or_partial(tmp_path, count, exit_class) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = _bundles.make_bundle(tmp_path)
    r = verify_signed_evidence(
        statement=signed.statement,
        signature=signed.signature,
        artifact_root=root / "artifacts",
        context=f.context(policy, expected_unbound_outputs=count),
    )
    assert r.exit_class is exit_class
    assert r.release.name == ("ALLOW" if exit_class is ExitClass.OK else "DENY")


def test_a_specific_failure_keeps_its_own_class_over_partial(tmp_path) -> None:  # type: ignore[no-untyped-def]
    root, signed, _, policy = _bundles.make_bundle(tmp_path)
    flipped = root / "artifacts" / "outputs" / "customers.csv"
    data = bytearray(flipped.read_bytes())
    data[0] ^= 1
    flipped.write_bytes(bytes(data))
    r = verify_signed_evidence(
        statement=signed.statement,
        signature=signed.signature,
        artifact_root=root / "artifacts",
        context=f.context(policy, expected_unbound_outputs=7),
    )
    assert r.exit_class is ExitClass.TAMPERED


def test_decide_returns_partial_only_after_every_other_check() -> None:
    from decoy_engine.signed_evidence import (
        ArtifactStatus,
        CheckStatus,
        IdentityBinding,
        SchemaStatus,
        SignatureStatus,
        TrustStatus,
    )

    ok = dict(
        purpose=Purpose.CONSUMER_ACCEPTANCE,
        schema=SchemaStatus.SUPPORTED,
        signature=SignatureStatus.VALID,
        envelope_malformed=False,
        trust=TrustStatus.TRUSTED,
        artifacts=ArtifactStatus.MATCH,
        checks=CheckStatus.PASS,
        identity=IdentityBinding.BOUND,
        rejected=False,
    )
    assert _decide(**ok, unbound_outputs=0) is ExitClass.OK
    assert _decide(**ok, unbound_outputs=3) is ExitClass.PARTIAL
    assert _decide(**{**ok, "checks": CheckStatus.FAIL}, unbound_outputs=3) is ExitClass.BLOCKED
    assert _decide(**{**ok, "trust": TrustStatus.REVOKED}, unbound_outputs=3) is ExitClass.UNTRUSTED


@pytest.mark.parametrize("bad", [-1, True, 1.0, "1", None])
def test_the_context_refuses_a_non_count(tmp_path, bad) -> None:  # type: ignore[no-untyped-def]
    _, _, _, policy = _bundles.make_bundle(tmp_path)
    with pytest.raises(SignedEvidenceError):
        f.context(policy, expected_unbound_outputs=bad)


def test_expectations_build_the_whole_context_by_themselves(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, _, _, policy = _bundles.make_bundle(tmp_path)
    doc = ed.valid_doc()
    doc["unbound_outputs"] = 7
    raw = ed.encode(doc)
    exp = parse_expectations(raw, pinned_sha256=ed.pin(raw))
    ctx = exp.context(policy, Purpose.CONSUMER_ACCEPTANCE)
    assert isinstance(ctx, VerificationContext)
    assert ctx.purpose is Purpose.CONSUMER_ACCEPTANCE and ctx.trust_policy is policy
    assert ctx.expected_unbound_outputs == 7
    assert (ctx.expected_tenant, ctx.expected_bundle_id) == ("tenant-acme", "bundle-001")
    assert (ctx.expected_job_id, ctx.expected_attempt_id) == ("job-1001", "attempt-1")
    assert ctx.expected_snapshot_id == "snap-001"
    assert ctx.expected_artifacts == f.expected_artifacts()
    assert all(a.sha256.startswith("sha256:") for a in ctx.expected_artifacts)
    # The nested catalog goes through JCS and the catalog loader to the same catalog digest.
    assert ctx.required_catalog.digest == f.catalog().digest
