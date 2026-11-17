"""AT-E9: the pinned expectations document, read through the one strict reader and one spec."""

from __future__ import annotations

import ast
import copy
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.signed_evidence import SignedEvidenceError, parse_expectations
from tests.unit.signed_evidence import _expectations_doc as ed

PKG = Path(__file__).resolve().parents[3] / "src" / "decoy_engine" / "signed_evidence"


def _load(doc: Any, *, pin: str | None = None):  # type: ignore[no-untyped-def]
    raw = doc if isinstance(doc, bytes) else ed.encode(doc)
    return parse_expectations(raw, pinned_sha256=ed.pin(raw) if pin is None else pin)


def _code(doc: Any, *, pin: str | None = None) -> str:
    with pytest.raises(SignedEvidenceError) as caught:
        _load(doc, pin=pin)
    err = caught.value
    assert err.__cause__ is None and err.__context__ is None
    return err.code


def _with(**over: Any) -> dict[str, Any]:
    doc = ed.valid_doc()
    for key, value in over.items():
        if value is KeyError:
            del doc[key]
        else:
            doc[key] = value
    return doc


def test_a_valid_document_parses_and_normalizes_the_digests() -> None:
    exp = _load(ed.valid_doc())
    assert exp.tenant == "tenant-acme" and exp.snapshot_id == "snap-001"
    assert exp.unbound_outputs == 0
    assert [a.sha256.startswith("sha256:") and len(a.sha256) == 71 for a in exp.artifacts] == [
        True
    ] * 3
    assert exp.catalog.id


def test_a_null_snapshot_id_is_allowed() -> None:
    assert _load(_with(snapshot_id=None)).snapshot_id is None


def test_a_wrong_pin_is_refused_before_the_bytes_are_read() -> None:
    other = "sha256:" + "0" * 64
    assert _code(b"{this is not json", pin=other) == "EXPECTATIONS_DIGEST_MISMATCH"
    assert _code(ed.valid_doc(), pin=other) == "EXPECTATIONS_DIGEST_MISMATCH"


@pytest.mark.parametrize("pin", ["", "abc", "sha256:" + "A" * 64, "sha256:" + "0" * 63, "0" * 64])
def test_a_malformed_pin_is_refused(pin: str) -> None:
    assert _code(ed.valid_doc(), pin=pin) == "EXPECTATIONS_PIN_INVALID"


@pytest.mark.parametrize(
    ("version", "code"),
    [
        (KeyError, "EXPECTATIONS_MISSING_FIELD"),
        (2, "EXPECTATIONS_SCHEMA_UNKNOWN"),
        (True, "EXPECTATIONS_SCHEMA_UNKNOWN"),
        ("1", "EXPECTATIONS_SCHEMA_UNKNOWN"),
        (1.0, "EXPECTATIONS_FLOAT_NOT_ALLOWED"),
    ],
)
def test_the_version_is_exactly_integer_one(version: Any, code: str) -> None:
    assert _code(_with(v=version)) == code


def test_an_unknown_member_is_refused() -> None:
    doc = ed.valid_doc()
    doc["extra"] = 1
    assert _code(doc) == "EXPECTATIONS_UNKNOWN_FIELD"


@pytest.mark.parametrize(
    "member",
    [
        "v",
        "tenant",
        "job_id",
        "attempt_id",
        "bundle_id",
        "snapshot_id",
        "artifacts",
        "unbound_outputs",
        "catalog",
    ],
)
def test_each_required_member_must_be_present(member: str) -> None:
    assert _code(_with(**{member: KeyError})) == "EXPECTATIONS_MISSING_FIELD"


@pytest.mark.parametrize("member", ["tenant", "job_id", "attempt_id", "bundle_id", "snapshot_id"])
@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("", "EXPECTATIONS_BAD_TOKEN"),
        (5, "EXPECTATIONS_WRONG_TYPE"),
        ("not an id!", "EXPECTATIONS_BAD_TOKEN"),
        ("job-1\n", "EXPECTATIONS_BAD_TOKEN"),
        ("a" * 129, "EXPECTATIONS_BAD_TOKEN"),
    ],
)
def test_an_id_is_a_string_that_fullmatches_the_id_rule(member: str, value: Any, code: str) -> None:
    assert _code(_with(**{member: value})) == code


def test_artifacts_must_be_a_non_empty_list_of_closed_entries() -> None:
    assert _code(_with(artifacts=[])) == "EXPECTATIONS_ARTIFACTS_EMPTY"
    assert _code(_with(artifacts={})) == "EXPECTATIONS_WRONG_TYPE"
    assert _code(_with(artifacts="x")) == "EXPECTATIONS_WRONG_TYPE"
    doc = ed.valid_doc()
    doc["artifacts"][0]["extra"] = 1
    assert _code(doc) == "EXPECTATIONS_UNKNOWN_FIELD"
    doc = ed.valid_doc()
    del doc["artifacts"][0]["media_type"]
    assert _code(doc) == "EXPECTATIONS_MISSING_FIELD"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda h: h.upper(),
        lambda h: h[:-1],
        lambda h: h + "\n",
        lambda h: "sha256:" + h,
        lambda h: "",
    ],
)
def test_a_sha256_is_64_lowercase_hex_and_nothing_else(mutate: Any) -> None:
    doc = ed.valid_doc()
    doc["artifacts"][0]["sha256"] = mutate(doc["artifacts"][0]["sha256"])
    assert _code(doc) == "EXPECTATIONS_BAD_TOKEN"


def test_a_media_type_must_fullmatch() -> None:
    doc = ed.valid_doc()
    doc["artifacts"][0]["media_type"] = "text/csv\n"
    assert _code(doc) == "EXPECTATIONS_BAD_TOKEN"


def test_duplicate_artifact_ids_are_refused() -> None:
    doc = ed.valid_doc()
    doc["artifacts"].append(copy.deepcopy(doc["artifacts"][0]))
    assert _code(doc) == "EXPECTATIONS_ARTIFACT_ID_DUPLICATE"


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (True, "EXPECTATIONS_WRONG_TYPE"),
        (-1, "EXPECTATIONS_OUT_OF_RANGE"),
        (1.0, "EXPECTATIONS_FLOAT_NOT_ALLOWED"),
        ("1", "EXPECTATIONS_WRONG_TYPE"),
        (None, "EXPECTATIONS_WRONG_TYPE"),
    ],
)
def test_unbound_outputs_is_a_non_negative_integer(value: Any, code: str) -> None:
    assert _code(_with(unbound_outputs=value)) == code


def test_a_malformed_catalog_is_refused() -> None:
    assert _code(_with(catalog={})) == "EXPECTATIONS_BAD_TOKEN"
    assert _code(_with(catalog=[])) == "EXPECTATIONS_BAD_TOKEN"
    doc = ed.valid_doc()
    doc["catalog"]["requirements"] = []
    assert _code(doc) == "EXPECTATIONS_BAD_TOKEN"


def test_a_duplicate_member_and_a_float_are_refused_by_the_strict_reader() -> None:
    raw = ed.encode(ed.valid_doc()).replace(b'"v": 1,', b'"v": 1, "v": 1,', 1)
    assert _code(raw) == "EXPECTATIONS_DUPLICATE_MEMBER"
    assert _code(b"[1.5]") == "EXPECTATIONS_FLOAT_NOT_ALLOWED"
    assert _code(b"\xef\xbb\xbf{}") == "EXPECTATIONS_BOM"


def test_no_refusal_echoes_the_input() -> None:
    doc = _with(tenant="canary-id\n")
    assert "canary" not in _code(doc)


# -- the one pin check ----------------------------------------------------------------------------


def _functions(path: Path) -> dict[str, ast.AST]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _calls(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            names.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return names


def test_both_loaders_call_the_one_pin_helper_and_nothing_else_compares_a_pin() -> None:
    trust = _functions(PKG / "_trust.py")
    expectations = _functions(PKG / "_expectations.py")
    assert "_check_pinned_digest" in _calls(trust["from_bytes"])
    assert "_check_pinned_digest" in _calls(expectations["parse_expectations"])
    for name, fn in {**trust, **expectations}.items():
        if name == "_check_pinned_digest":
            continue
        assert not ({"compare_digest"} & _calls(fn)) or "pinned" not in ast.unparse(fn), name
    for path in PKG.glob("*.py"):
        for name, fn in _functions(path).items():
            if name != "_check_pinned_digest" and "pinned_sha256" in ast.unparse(fn):
                assert "compare_digest" not in _calls(fn), (path.name, name)
