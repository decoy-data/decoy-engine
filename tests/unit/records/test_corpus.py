"""The corpus samples a later engine must still read: one per persisted record format."""

from __future__ import annotations

import json

from decoy_engine import records
from decoy_engine.records._payloads import SampleRunPayload
from decoy_engine.records._read_model import read_model_of
from tests.unit.records._helpers import CORPUS, INVOCATION, corpus

RECORD_ID = "sha256:28a69ab98840ee3aa6a396287621a841b6ffaa6b116b09ee21c0588782696c26"


def test_decoy_record_v1_sample_decodes_to_its_recorded_id() -> None:
    got = records.decode((CORPUS / "decoy-record-v1.json").read_bytes())
    assert isinstance(got, records.DecodedRecord)
    assert got.id == RECORD_ID and got.kind == "sample-run"


def test_sample_run_v1_payload_reads_under_both_models() -> None:
    payload = corpus("sample-run-v1.json")
    assert SampleRunPayload.model_validate(payload).sample_size == 50
    assert read_model_of(SampleRunPayload).model_validate(payload).root_table == "médecins"


def test_decoy_library_export_v1_sample_reads_whole() -> None:
    items = list(
        records.read_export((CORPUS / "decoy-library-export-v1.jsonl").read_bytes().splitlines())
    )
    header, record, log = items
    assert header.record_count == 1 and header.withheld_logs == ()
    assert record.record.id == RECORD_ID and record.source_id is None
    assert isinstance(log, records.ExportedLog) and log.verified and log.invocation_id == INVOCATION


def test_decoy_job_log_v1_sample_reads_header_and_events() -> None:
    log = records.read_job_log((CORPUS / "decoy-job-log-v1.jsonl").read_bytes())
    assert log.header.invocation_id == INVOCATION and log.header.command == "run"
    assert len(log.events) == 2 and not log.truncated_tail and log.bad_lines == 0
    assert json.loads((CORPUS / "decoy-job-log-v1.jsonl").read_text().splitlines()[0])["log_schema"]


# -- scan-set/v1 written before the basis labels (PROFILE-SAMPLE-LABELS E1) ---------------------
# Both files were written once at the engine head before E1 and are never regenerated: they are
# what an older engine saved, so a later engine must still read and export them.


def test_a_pre_basis_scan_set_record_decodes_exports_and_reads_back() -> None:
    from decoy_engine.records import canonical_bytes
    from tests.unit.records._helpers import PRODUCER, T0

    data = (CORPUS / "scan-set-v1.json").read_bytes()
    got = records.decode(data)
    assert isinstance(got, records.DecodedRecord) and got.kind == "scan-set"
    lines = list(records.export_lines([got.raw], producer=PRODUCER, exported_at=T0))
    items = list(records.read_export(lines))
    header, exported = items[0], items[1]
    assert header.withheld_records == () and header.record_count == 1
    payload = exported.record.raw["payload"]
    assert payload["tables"][0]["descriptor"]["path"] == "claims.csv"
    # The stored keys were never proven by a whole read, so export drops them.
    assert payload["tables"][0]["key_candidates"] == []
    again = records.decode(canonical_bytes(exported.record.raw))
    assert isinstance(again, records.DecodedRecord) and again.id == exported.record.id
