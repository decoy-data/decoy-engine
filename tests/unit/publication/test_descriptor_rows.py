"""DELIV E2f (AT-57): the descriptor reader's role/rows rule and the one unit-path rule.

Documents are hand-built with `json` only (see `_doc`), so the reader is checked against the
plan's wire rules and not against the writer. Every refusal is value-free: closed token, no
exception context (recurring-defect class 3).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit.publication import _doc

PREFIX = "descriptor_refused:"


def _decode(document: dict[str, Any]) -> Any:
    from decoy_engine.publication import decode_descriptor

    return decode_descriptor(_doc.encode(document))


def _with_artifacts(*arts: dict[str, Any]) -> dict[str, Any]:
    document = _doc.doc()
    document["artifacts"] = sorted(arts, key=lambda a: a["path"])
    return _doc.resign(document)


def _refused(document: dict[str, Any], check: str) -> None:
    with pytest.raises(ValueError) as caught:
        _decode(document)
    assert str(caught.value) == PREFIX + check
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_accepts_nested_csv_quarantine_report_with_null_rows() -> None:
    document = _with_artifacts(
        _doc.artifact("masked/customers.csv", rows=None),
        _doc.artifact("orders.parquet", rows=3),
        _doc.artifact("quarantine/rows.jsonl", role="quarantine", rows=None),
        _doc.artifact("report.json", role="report", rows=None),
    )
    got = _decode(document)
    assert [(a.path, a.role, a.rows) for a in got.artifacts] == [
        ("masked/customers.csv", "table", None),
        ("orders.parquet", "table", 3),
        ("quarantine/rows.jsonl", "quarantine", None),
        ("report.json", "report", None),
    ]


@pytest.mark.parametrize(
    "art",
    [
        _doc.artifact("t.parquet", rows=None),  # a Parquet table needs its footer count
        _doc.artifact("t.csv", rows=4),  # a CSV carries no count
        _doc.artifact("q.jsonl", role="quarantine", rows=4),
    ],
)
def test_role_rows_rule_is_refused(art: dict[str, Any]) -> None:
    _refused(_with_artifacts(art), "wrong_type")


def test_rows_key_stays_required() -> None:
    art = _doc.artifact("t.csv", rows=None)
    del art["rows"]
    _refused(_with_artifacts(art), "missing_field")


def test_rows_must_be_exact_int_or_null() -> None:
    _refused(_with_artifacts(_doc.artifact("t.parquet", rows=True)), "wrong_type")
    _refused(_with_artifacts(_doc.artifact("t.parquet", rows="3")), "wrong_type")


def test_unknown_role_is_refused() -> None:
    _refused(_with_artifacts(_doc.artifact("t.csv", role="record", rows=None)), "bad_token")


@pytest.mark.parametrize(
    "path",
    [
        "/".join(["d"] * 8) + "/f.csv",  # nine components
        "_decoy_publication.json",
        "_DECOY_PUBLICATION.JSON",
        "a//b.csv",
        "../x.csv",
    ],
)
def test_bad_single_path_is_refused(path: str) -> None:
    _refused(_with_artifacts(_doc.artifact(path, rows=None)), "bad_path")


def test_eight_components_are_accepted() -> None:
    path = "/".join(["d"] * 7) + "/f.csv"
    assert _decode(_with_artifacts(_doc.artifact(path, rows=None))).artifacts[0].path == path


def test_duplicate_path_is_refused() -> None:
    a = _doc.artifact("t.csv", rows=None)
    b = _doc.artifact("t.csv", rows=None, sha256="3" * 64)
    document = _doc.doc()
    document["artifacts"] = [a, b]
    _refused(_doc.resign(document), "bad_path")


def test_prefix_clash_is_refused() -> None:
    _refused(
        _with_artifacts(_doc.artifact("a", rows=None), _doc.artifact("a/b.csv", rows=None)),
        "bad_path",
    )


def test_member_applies_the_same_single_path_rule() -> None:
    from decoy_engine.publication import Member

    for bad in ("/".join(["d"] * 8) + "/f", "_decoy_publication.json", "a//b", 5):
        with pytest.raises(ValueError) as caught:
            Member(bad, "table")  # type: ignore[arg-type]
        assert caught.value.__cause__ is None and caught.value.__context__ is None
    with pytest.raises(ValueError):
        Member("a.csv", "record")  # type: ignore[arg-type]
    assert Member("a/b.csv", "quarantine").role == "quarantine"
