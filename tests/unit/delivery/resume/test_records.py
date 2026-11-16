"""AT-C1 and AT-C2: the two resume store records, written and read under one strict rule set.

Plan `f23-plan` 4.2 and 7.1 (slice E2; recurring-defect classes 1, 2, 3 and 4). Every document is
built by hand in `_docs.py` and the reader is held to the wire rules; each refusal cell breaks
exactly one rule of a document the reader otherwise accepts, and the token pins which rule did.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.delivery.resume import (
    RunFingerprint,
    RunRecord,
    TableEntry,
    TableRecord,
    decode_run_record,
    decode_table_record,
    encode_run_record,
    encode_table_record,
)
from decoy_engine.publication import Artifact
from tests.unit.delivery.resume import _docs
from tests.unit.delivery.resume._docs import DELETE, edit

PREFIX = "resume_record_refused:"
CORPUS = Path(__file__).resolve().parents[3] / "integration" / "compat_corpus" / "resume"


def _run() -> RunRecord:
    return RunRecord(
        run_id="20261116T101500123456Z-0a1b2c3d",
        invocation_id="0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
        operation_id="run-0a1b2c3d",
        route="chunked",
        fingerprint=RunFingerprint(
            config_hash=_docs.bare("config"),
            components=(
                ("decoy-cli", "1.0.0"),
                ("decoy-engine", "0.23.0"),
                ("pyarrow", "18.0.0"),
            ),
            key_check="0123456789abcdef",
            key_version="v1",
            chunk_size=50000,
        ),
        tables=tuple(
            TableEntry(i, _docs.tagged(f"name-{i}"), _docs.tagged(f"binding-{i}")) for i in range(5)
        ),
    )


def _table(index: int = 0) -> TableRecord:
    return TableRecord(
        index=index,
        name_digest=_docs.tagged(f"name-{index}"),
        binding_digest=_docs.tagged(f"binding-{index}"),
        artifact=Artifact(
            path=f"tables/{index}-0123456789ab.parquet",
            role="table",
            rows=1200,
            sha256=_docs.bare(f"file-{index}"),
            size=48213,
        ),
        source_sha256=_docs.tagged(f"source-{index}"),
        fingerprint_digest=_docs.tagged("fingerprint"),
    )


def _refused(decode: Any, data: Any) -> ValueError:
    with pytest.raises(ValueError) as caught:
        decode(data)
    return caught.value


def test_round_trip() -> None:
    """AT-C1: records encode and decode equal, and the bytes are the canonical form."""
    run, table = _run(), _table(2)
    run_bytes, table_bytes = encode_run_record(run), encode_table_record(table)
    assert decode_run_record(run_bytes) == run
    assert decode_table_record(table_bytes) == table
    assert encode_run_record(decode_run_record(run_bytes)) == run_bytes
    assert run_bytes == _docs.canonical(_docs.run_doc())
    assert table_bytes == _docs.canonical(_docs.table_doc(2))
    assert run_bytes == encode_run_record(_run())  # stable across calls


@pytest.mark.parametrize("name", ["resume-run-v1.json", "resume-table-v1.json"])
def test_corpus_samples_read_and_rewrite_byte_for_byte(name: str) -> None:
    """The frozen samples: a later engine keeps reading what this one wrote."""
    data = (CORPUS / name).read_bytes().removesuffix(b"\n")
    if "run" in name:
        assert encode_run_record(decode_run_record(data)) == data
    else:
        assert encode_table_record(decode_table_record(data)) == data


def _run_cell(path: str, value: Any, token: str) -> tuple[str, Any, str]:
    return ("run", edit(_docs.run_doc(), path, value), token)


def _table_cell(path: str, value: Any, token: str) -> tuple[str, Any, str]:
    return ("table", edit(_docs.table_doc(), path, value), token)


SHA = "sha256:" + "a" * 64
_CELLS = {
    "table_unknown_field": _table_cell("extra", 1, "unknown_field"),
    "table_artifact_unknown_field": _table_cell("artifact.extra", 1, "unknown_field"),
    "table_missing_field": _table_cell("fingerprint_digest", DELETE, "missing_field"),
    "table_artifact_missing_field": _table_cell("artifact.size", DELETE, "missing_field"),
    "table_bool_index": _table_cell("index", True, "wrong_type"),
    "table_bool_rows": _table_cell("artifact.rows", True, "wrong_type"),
    "table_numeric_string_index": _table_cell("index", "1", "wrong_type"),
    "table_numeric_string_size": _table_cell("artifact.size", "48213", "wrong_type"),
    "table_float_rows": _table_cell("artifact.rows", 1.0, "wrong_type"),
    "table_negative_rows": _table_cell("artifact.rows", -1, "out_of_range"),
    "table_non_hex_name_digest": _table_cell("name_digest", "sha256:" + "z" * 64, "bad_token"),
    "table_untagged_name_digest": _table_cell("name_digest", "a" * 64, "bad_token"),
    "table_uppercase_digest": _table_cell("binding_digest", "sha256:" + "A" * 64, "bad_token"),
    "table_short_artifact_sha": _table_cell("artifact.sha256", "a" * 63, "bad_token"),
    "table_bare_source": _table_cell("source_sha256", "a" * 64, "bad_token"),
    "table_source_trailing_newline": _table_cell("source_sha256", SHA + "\n", "bad_token"),
    "table_digest_trailing_newline": _table_cell("fingerprint_digest", SHA + "\n", "bad_token"),
    "table_artifact_sha_trailing_newline": _table_cell(
        "artifact.sha256", "a" * 64 + "\n", "bad_token"
    ),
    "table_non_string_source": _table_cell("source_sha256", 7, "wrong_type"),
    "table_absolute_path": _table_cell("artifact.path", "/tables/0.parquet", "bad_path"),
    "table_parent_path": _table_cell("artifact.path", "../0.parquet", "bad_path"),
    "table_inner_parent_path": _table_cell("artifact.path", "tables/../0.parquet", "bad_path"),
    "table_empty_part_path": _table_cell("artifact.path", "tables//0.parquet", "bad_path"),
    "table_descriptor_path": _table_cell("artifact.path", "_decoy_publication.json", "bad_path"),
    "table_role": _table_cell("artifact.role", "vault", "bad_token"),
    "table_wrong_tag": _table_cell("schema", "decoy-resume-table/v2", "schema_unknown"),
    "table_run_tag": _table_cell("schema", "decoy-resume-run/v1", "schema_unknown"),
    "table_tag_trailing_newline": _table_cell(
        "schema", "decoy-resume-table/v1\n", "schema_unknown"
    ),
    "table_missing_tag": _table_cell("schema", DELETE, "schema_missing"),
    "run_unknown_field": _run_cell("extra", 1, "unknown_field"),
    "run_fingerprint_unknown_field": _run_cell("fingerprint.extra", 1, "unknown_field"),
    "run_entry_unknown_field": _run_cell("tables.0.extra", 1, "unknown_field"),
    "run_missing_field": _run_cell("operation_id", DELETE, "missing_field"),
    "run_fingerprint_missing_field": _run_cell("fingerprint.key_check", DELETE, "missing_field"),
    "run_bool_chunk_size": _run_cell("fingerprint.chunk_size", True, "wrong_type"),
    "run_numeric_string_chunk_size": _run_cell("fingerprint.chunk_size", "50000", "wrong_type"),
    "run_zero_chunk_size": _run_cell("fingerprint.chunk_size", 0, "out_of_range"),
    "run_bool_index": _run_cell("tables.1.index", False, "wrong_type"),
    "run_route": _run_cell("route", "plain", "bad_token"),
    "run_config_hash_tagged": _run_cell("fingerprint.config_hash", SHA, "bad_token"),
    "run_key_check_short": _run_cell("fingerprint.key_check", "0123456789abcde", "bad_token"),
    "run_key_check_trailing_newline": _run_cell(
        "fingerprint.key_check", "0123456789abcdef\n", "bad_token"
    ),
    "run_invocation_not_v4": _run_cell(
        "invocation_id", "0a1b2c3d-4e5f-1a6b-8c7d-9e0f1a2b3c4d", "bad_token"
    ),
    "run_operation_id_newline": _run_cell("operation_id", "run-0a1b2c3d\n", "bad_token"),
    "run_run_id_path": _run_cell("run_id", "../x", "bad_token"),
    "run_run_id_newline": _run_cell("run_id", "20261116T101500123456Z-0a1b2c3d\n", "bad_token"),
    "run_key_version_newline": _run_cell("fingerprint.key_version", "v1\n", "bad_token"),
    "run_binding_untagged": _run_cell("tables.0.binding_digest", "a" * 64, "bad_token"),
    "run_components_not_list": _run_cell("fingerprint.components", "pyarrow", "wrong_type"),
    "run_component_triple": _run_cell(
        "fingerprint.components.0", ["a", "b", "c"], "components_invalid"
    ),
    "run_component_single": _run_cell("fingerprint.components.0", ["a"], "components_invalid"),
    "run_components_empty": _run_cell("fingerprint.components", [], "components_invalid"),
    "run_components_unsorted": _run_cell(
        "fingerprint.components", [["pyarrow", "1"], ["decoy-cli", "1"]], "components_invalid"
    ),
    "run_tables_not_ascending": _run_cell("tables.1.index", 0, "tables_order"),
    "run_tables_descending": _run_cell("tables", [_docs.entry(3), _docs.entry(1)], "tables_order"),
    "run_wrong_tag": _run_cell("schema", "decoy-resume-run/v2", "schema_unknown"),
    "run_table_tag": _run_cell("schema", "decoy-resume-table/v1", "schema_unknown"),
    "run_missing_tag": _run_cell("schema", DELETE, "schema_missing"),
}


@pytest.mark.parametrize("cell", sorted(_CELLS))
def test_reader_refuses(cell: str) -> None:
    """AT-C2: one broken rule per cell; the refusal is the closed token and nothing else."""
    kind, doc, token = _CELLS[cell]
    decode = decode_run_record if kind == "run" else decode_table_record
    error = _refused(decode, _docs.canonical(doc))
    assert str(error) == PREFIX + token
    assert error.__cause__ is None and error.__context__ is None


def test_the_intact_documents_are_read() -> None:
    """The cells above start from documents the reader accepts, so each token is its own cell."""
    assert decode_run_record(_docs.canonical(_docs.run_doc())).tables[4].index == 4
    assert decode_table_record(_docs.canonical(_docs.table_doc())).artifact.rows == 1200


@pytest.mark.parametrize("decode", [decode_run_record, decode_table_record])
def test_reader_refuses_a_bad_byte_stream(decode: Any) -> None:
    doc = _docs.run_doc() if decode is decode_run_record else _docs.table_doc()
    good = _docs.canonical(doc)
    big = b"{" + b" " * (65 * _docs.KIB) + b"}"
    assert str(_refused(decode, big)) == PREFIX + "oversize"
    assert str(_refused(decode, good + b" " * 70000)) == PREFIX + "oversize"
    assert str(_refused(decode, good + b"\n")) == PREFIX + "not_canonical"
    assert str(_refused(decode, good.replace(b"{", b"{ ", 1))) == PREFIX + "not_canonical"
    pretty = json.dumps(json.loads(good), sort_keys=True, indent=1).encode()
    assert str(_refused(decode, pretty)) == PREFIX + "not_canonical"
    reversed_keys = dict(reversed(list(json.loads(good).items())))
    unsorted = json.dumps(reversed_keys, separators=(",", ":"))
    assert str(_refused(decode, unsorted.encode())) == PREFIX + "not_canonical"
    assert str(_refused(decode, b"[]")) == PREFIX + "not_object"
    assert str(_refused(decode, b"{")) == PREFIX + "not_json"
    assert str(_refused(decode, b"")) == PREFIX + "not_json"
    assert str(_refused(decode, b'{"schema":"x","schema":"x"}')) == PREFIX + "duplicate_key"
    assert str(_refused(decode, b'{"schema":NaN}')) == PREFIX + "non_finite"
    assert str(_refused(decode, str(good, "utf-8"))) == PREFIX + "wrong_type"
    assert str(_refused(decode, bytearray(good))) == PREFIX + "wrong_type"
    assert str(_refused(decode, None)) == PREFIX + "wrong_type"


def test_a_refusal_carries_nothing_from_the_bytes() -> None:
    """Class 3: the text is the closed token; a planted name and value never reach it."""
    planted = _docs.table_doc()
    planted["customers_ssn_column"] = "123-45-6789"
    error = _refused(decode_table_record, _docs.canonical(planted))
    assert "ssn" not in str(error) and "123-45" not in str(error)
    assert error.args == (PREFIX + "unknown_field",)
    assert error.__cause__ is None and error.__context__ is None
    planted_path = _docs.table_doc()
    planted_path["artifact"]["path"] = "/home/alice/secret/customers.parquet"
    error = _refused(decode_table_record, _docs.canonical(planted_path))
    assert "alice" not in str(error)
    assert error.__cause__ is None and error.__context__ is None


def test_the_writer_refuses_what_the_reader_refuses() -> None:
    """One declaration drives both directions: a record the reader would refuse is never written."""
    run, table = _run(), _table()
    bad_run = [
        RunRecord(**{**run.__dict__, "route": "plain"}),
        RunRecord(**{**run.__dict__, "tables": tuple(reversed(run.tables))}),
        RunRecord(
            **{
                **run.__dict__,
                "fingerprint": RunFingerprint(**{**run.fingerprint.__dict__, "chunk_size": True}),
            }
        ),
    ]
    for record in bad_run:
        with pytest.raises(ValueError, match=PREFIX):
            encode_run_record(record)
    bad_table = [
        TableRecord(**{**table.__dict__, "source_sha256": "a" * 64}),
        TableRecord(**{**table.__dict__, "index": True}),
        TableRecord(**{**table.__dict__, "name_digest": table.name_digest + "\n"}),
        TableRecord(
            **{**table.__dict__, "artifact": Artifact(**{**table.artifact.__dict__, "path": "/x"})}
        ),
    ]
    for table_record in bad_table:
        with pytest.raises(ValueError, match=PREFIX):
            encode_table_record(table_record)
    with pytest.raises(ValueError, match=PREFIX + "wrong_type"):
        encode_table_record(_run())  # type: ignore[arg-type]


def test_the_writer_refuses_an_oversize_run_record() -> None:
    """A run with too many tables cannot be resumed: the cap is on the record, not the caller."""
    many = tuple(TableEntry(i, _docs.tagged(f"n{i}"), _docs.tagged(f"b{i}")) for i in range(400))
    run = RunRecord(**{**_run().__dict__, "tables": many})
    with pytest.raises(ValueError, match=PREFIX + "oversize"):
        encode_run_record(run)


def test_an_unpaired_surrogate_in_a_path_is_refused_not_raised() -> None:
    """A path the component validator cannot take is a closed refusal on write and on read."""
    table = _table()
    broken = TableRecord(
        **{**table.__dict__, "artifact": Artifact(**{**table.artifact.__dict__, "path": "a\ud800"})}
    )
    error = _refused(encode_table_record, broken)
    assert str(error) == PREFIX + "bad_path"
    assert error.__cause__ is None and error.__context__ is None
    raw = json.dumps(_docs.table_doc(artifact=_docs.artifact(path="a\ud800")), sort_keys=True)
    error = _refused(decode_table_record, raw.encode("ascii"))
    assert str(error) == PREFIX + "bad_path"
    assert error.__cause__ is None and error.__context__ is None
