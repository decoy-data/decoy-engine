"""S7a sentry: each frozen format tag S7a added to contract 3.1 is read from an artifact the
engine writes (AT-S7c), and no internal tag reaches a written file (AT-S7e, failure mode F17).

A producer runs the real writer on minimal input and returns the bytes. Where the engine writes
no file for a tag (a typed constant, a reserved record kind, a reader-only version), the producer
returns the public constant and the map row cites `S7A-KL-1`. `INTERNAL_TAGS` owners run through
their own fixtures, and every artifact from every fixture is scanned for every internal tag.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from decoy_engine.contracts import stability as st
from tests.sentry.release import _tags

ROOT = _tags.ROOT
MAP = ROOT / "docs" / "frozen-surfaces.md"
THIS = "tests/sentry/release/test_tag_artifacts.py"
Producer = Callable[[Path], bytes]


def _json(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True).encode("utf-8")


def _descriptor(_: Path) -> bytes:
    from decoy_engine.publication import _descriptor as d

    artifact = d.Artifact(path="t.parquet", role="table", rows=1, sha256="a" * 64, size=10)
    vault = d.DescriptorVault(sha256="b" * 64, size=5, entry_count=1)
    built = d.build_descriptor(operation_id="job-1.attempt:1", artifacts=[artifact], vault=vault)
    return d.encode_descriptor(built)


def _pinned_plan(_: Path) -> bytes:
    from decoy_engine.generation._pinned_plan import PINNED_PLAN_SCHEMA, PinnedPlan

    plan = PinnedPlan(
        schema_version=PINNED_PLAN_SCHEMA,
        reference_date="2026-10-22T09:30:00Z",
        runtime_identity=(("engine", "0.0.0-test"),),
        tables=(),
        statistical=(),
    )
    return _json(plan.to_dict())


def _safe_output(_: Path) -> bytes:
    from decoy_engine import reasons
    from decoy_engine.reasons import Severity
    from decoy_engine.safe_output import EventKind, SafeEvent

    ref = reasons.get_reason("post_scan", "check_error").ref
    return _json(
        SafeEvent(seq=0, ts_ms=0, sev=Severity.ERROR, kind=EventKind.INVALID, reason=ref).to_dict()
    )


def _quarantine(tmp: Path) -> bytes:
    from decoy_engine.contracts.declared_casting import ProtectedQuarantineConfig
    from decoy_engine.declared_casting import (
        LocalProtectedQuarantineSink,
        QuarantineEnvelope,
        QuarantinePolicy,
        QuarantineRun,
    )
    from decoy_engine.keyprovider import SecretKeyProvider
    from tests.acceptance._f06_support import PROTECTED_QUARANTINE

    sink = LocalProtectedQuarantineSink(tmp / "q", key_provider=SecretKeyProvider(secret=b"q" * 32))
    config = ProtectedQuarantineConfig.model_validate(PROTECTED_QUARANTINE)
    policy = QuarantinePolicy(**config.model_dump())
    session = sink.begin(QuarantineRun(owner="tenant-1", run_id="run-A"), policy)
    sink.write_row(
        session, QuarantineEnvelope(table="t", row_position=0, reasons=(), row={"id": "1"})
    )
    sink.seal(session)
    return b"".join(p.read_bytes() for p in sorted((tmp / "q").rglob("*")) if p.is_file())


def _model_pack(_: Path) -> bytes:
    from decoy_engine.profiling.model_pack.types import ModelPackManifest

    return _json(ModelPackManifest(pack_id="p", version="0.0.1").to_dict())


def _phase_result(_: Path) -> bytes:
    from decoy_engine.phase import PhaseResult, to_wire

    wire = to_wire(
        PhaseResult(phase="pre_scan", check_id="c", status="passed", method="m", method_version="1")
    )
    return _json(wire)


def _phase_event(_: Path) -> bytes:
    from decoy_engine.phase import PhaseEvent, to_wire

    return _json(to_wire(PhaseEvent(phase="pre_scan", event="start", status="completed")))


_EVIDENCE = ROOT / "tests" / "fixtures" / "signed_evidence" / "v1"


def _fixture(name: str) -> Producer:
    path = _EVIDENCE / name
    return lambda _: path.read_bytes()


def _shared(schema: str) -> Producer:
    """The first shared fixture document whose own `schema` member is `schema`."""

    def produce(_: Path) -> bytes:
        for path in sorted((_EVIDENCE / "shared").glob("*.json")):
            if json.loads(path.read_bytes()).get("schema") == schema:
                return path.read_bytes()
        raise AssertionError(f"no shared fixture with schema {schema}")

    return produce


def _kind_schema(kind: str) -> Producer:
    from decoy_engine.records._registry import kind_spec

    def produce(_: Path) -> bytes:
        spec = kind_spec(kind)
        assert spec is not None, kind
        return spec.payload_schema.encode()

    return produce


def _const(module: str, attr: str, member: str | None = None) -> Producer:
    def produce(_: Path) -> bytes:
        import importlib

        value = getattr(importlib.import_module(module), attr)
        if member is not None:
            value = getattr(value, member)
        return str(getattr(value, "value", value)).encode()

    return produce


def _reader_v2(_: Path) -> bytes:
    from decoy_engine.verification.postmask import finding_reader as fr
    from decoy_engine.verification.postmask.types import READABLE_SCHEMA_VERSIONS

    row = {
        "table": "t",
        "column": "c",
        "detector_id": "email",
        "match_rate": 0.5,
        "severity": "warning",
    }
    # A v2 report predates the v3 fields, so its row needs only the base fields.
    assert fr.read_residual_finding(row, version="post-scan-integrity/v2") is not None
    return _json({"readable": sorted(READABLE_SCHEMA_VERSIONS)})


def _redacted_v1(_: Path) -> bytes:
    from decoy_engine.profiling._value_redaction import REDACTED_POLICIES

    return _json({"redacted_policies": sorted(REDACTED_POLICIES)})


# tag -> producer. The keys are the format tags S7a added to the contract 3.1 block.
PRODUCERS: dict[str, Producer] = {
    "decoy-publication/v1": _descriptor,
    "immutable_directory/v1": _descriptor,
    "pinned-plan/v1": _pinned_plan,
    "decoy-safe-output/v1": _safe_output,
    "decoy-quarantine/v1": _quarantine,
    "decoy-model-pack/v1": _model_pack,
    "decoy.evidence.statement/v1": _fixture("vectors/a1_flip_csv/statement.bin"),
    "decoy.trust-policy/v1": _shared("decoy.trust-policy/v1"),
    "decoy.required-catalog/v1": _shared("decoy.required-catalog/v1"),
    # No engine writer: S7A-KL-1. `to_wire` only builds the dict; nothing in the engine calls it.
    "phase-result/v1": _phase_result,
    "phase-event/v1": _phase_event,
    "publication/v1": _kind_schema("publication"),
    "checkpoint-index/v1": _kind_schema("checkpoint"),
    "decoy-support-bundle/v1": _const("decoy_engine.support", "BundleSchema", "V1"),
    "decoy-reasons/v1": _const("decoy_engine.reasons", "REGISTRY_SCHEMA"),
    "dps-marginal/v3": _const("decoy_engine.quality.dp_schema", "DP_SNAPSHOT_SCHEMA_VERSION"),
    "canary-span-report/v1": _const(
        "decoy_engine.verification.canary", "CanarySpanReportSchema", "V1"
    ),
    "post-scan-integrity/v2": _reader_v2,
    "flagged-redacted/v1": _redacted_v1,
}
NO_WRITER = frozenset(
    {
        "phase-result/v1",
        "phase-event/v1",
        "publication/v1",
        "checkpoint-index/v1",
        "decoy-support-bundle/v1",
        "decoy-reasons/v1",
        "dps-marginal/v3",
        "canary-span-report/v1",
        "post-scan-integrity/v2",
        "flagged-redacted/v1",
    }
)


@pytest.mark.parametrize("tag", sorted(PRODUCERS))
def test_a_frozen_tag_is_read_from_its_artifact(tag: str, tmp_path: Path) -> None:
    assert tag.encode() in PRODUCERS[tag](tmp_path), f"{tag} is not in its artifact"


def test_every_s7a_tag_is_in_the_contract_block_and_cites_this_pinning_test() -> None:
    contract = _tags.CONTRACT.read_text(encoding="utf-8")
    assert set(PRODUCERS) <= _tags.contract_3_1_tags(contract)
    table = _tags_table()
    for tag in PRODUCERS:
        row = [r for r in table if re.search(rf"`{re.escape(tag)}`", r.split("|")[1])]
        assert len(row) == 1, f"{tag}: {len(row)} map rows"
        assert THIS in row[0], f"{tag}: its map row does not cite {THIS}"
        assert ("S7A-KL-1" in row[0]) == (tag in NO_WRITER), tag


def _tags_table() -> list[str]:
    text = MAP.read_text(encoding="utf-8")
    block = text.split("## Format tags (contract 3.1, 3.2)", 1)[1].split("\n## ", 1)[0]
    return [ln for ln in block.splitlines() if ln.startswith("| `")]


def _telemetry(_: Path) -> bytes:
    from decoy_engine.progress import PhaseEvent
    from decoy_engine.telemetry import SpanRecorder

    spans: list[object] = []
    recorder = SpanRecorder(spans.append)
    recorder.on_event(PhaseEvent(name="mask", status="start", table="t", ts=1.0))
    recorder.on_event(
        PhaseEvent(name="mask", status="finish", table="t", rows_in=3, rows_out=3, ts=2.0)
    )
    recorder.close()
    assert spans, "the recorder emitted no span"
    return repr(spans).encode()


# The writer fixture of each INTERNAL_TAGS owner, by tag.
INTERNAL_FIXTURES: dict[str, Producer] = {"decoy-telemetry/v1": _telemetry}


def scan(blobs: dict[str, bytes], tags: set[str]) -> list[str]:
    """`fixture: tag` for each internal tag found in any artifact; an empty artifact is a miss."""
    problems = [f"{name}: wrote no artifact" for name, blob in blobs.items() if not blob]
    for name, blob in blobs.items():
        problems += [f"{name}: {tag}" for tag in sorted(tags) if tag.encode() in blob]
    return problems


def _all_artifacts(tmp: Path) -> dict[str, bytes]:
    blobs = {f"internal:{tag}": make(tmp) for tag, make in INTERNAL_FIXTURES.items()}
    blobs.update({f"frozen:{tag}": make(tmp) for tag, make in PRODUCERS.items()})
    return blobs


def test_every_internal_tag_owner_has_a_writer_fixture() -> None:
    assert set(INTERNAL_FIXTURES) == set(st.INTERNAL_TAGS)


def test_no_internal_tag_reaches_a_written_artifact(tmp_path: Path) -> None:
    blobs = _all_artifacts(tmp_path)
    assert len(blobs) >= len(PRODUCERS) + len(INTERNAL_FIXTURES)
    assert scan(blobs, set(st.INTERNAL_TAGS)) == []


def test_the_scan_catches_an_internal_tag_in_a_fixture_output_and_an_empty_artifact() -> None:
    tag = next(iter(st.INTERNAL_TAGS))
    assert scan({"f": b'{"x": "' + tag.encode() + b'"}'}, {tag}) == [f"f: {tag}"]
    assert scan({"f": b""}, {tag}) == ["f: wrote no artifact"]
