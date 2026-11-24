"""PM-1a: a passthrough is exempt from the source comparison only when the writer query proves no
other writer owns its column, and a detector-flagged column keeps its final grade when the source
count is unknown.

Each writer case runs the frame check and the batch check on one input. The comparison on the
column raises, so only the writer query decides whether that is reported.
"""

from __future__ import annotations

import typing
from collections.abc import Mapping
from typing import Any

import pandas as pd
import pytest

from decoy_engine.config import TransformOp
from decoy_engine.plan.column_access import (
    KnownEmpty,
    KnownSet,
    Unknown,
    may_write,
    written_columns_by_table,
)
from decoy_engine.plan.column_access._writes import NON_WRITING_OPS
from decoy_engine.providers_v2 import get_default_registry
from decoy_engine.verification.postmask._column_facts import (
    ColumnFacts,
    DetectorRate,
    standalone_writes,
)
from decoy_engine.verification.postmask.residual_pii import (
    check_residual_pii,
    residual_pii_findings,
)
from tests.unit.detection_verification.test_residual_pii_source_compare import (
    _PLAIN,
    _RAISE,
    _both_paths,
)

_EMAILS = [f"user{i}@realmail.com" for i in range(100)]
_JOINT = {
    "name": "city",
    "strategy": "joint_mask",
    "provider_config": {
        "columns": ["zip", "city", "state"],
        "reference": "us_zip5_city_state",
        "key_by": "pid",
    },
}
_PASS_ZIP = {"name": "zip", "strategy": "passthrough"}


def _config(columns: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"version": 2, "tables": [{"name": "t", "columns": columns}], **extra}


def _fk_config(column: str) -> dict[str, Any]:
    return {
        "version": 2,
        "tables": [
            {"name": "p", "columns": []},
            {"name": "t", "columns": [{"name": column, "strategy": "passthrough"}]},
        ],
        "relationships": [
            {
                "parent": {"table": "p", "columns": ["id"]},
                "children": [{"table": "t", "columns": [column]}],
                "orphan_policy": "preserve",
            }
        ],
    }


# (config, the passthrough column a writer other than its own entry owns)
_OWNED = {
    "joint mask sibling": (_config([_JOINT, _PASS_ZIP]), "zip"),
    "fk child key": (_fk_config("zip"), "zip"),
    "unknown writer": (_config([_PASS_ZIP, {"name": "x", "strategy": "no_such_strategy"}]), "zip"),
}


def _severities(findings) -> list[tuple[str, str]]:
    return [(f.column, f.severity) for f in findings]


@pytest.mark.parametrize("case", list(_OWNED))
def test_an_owned_passthrough_reports_a_failed_comparison_without_a_hit(
    case, tmp_path, monkeypatch
):
    config, column = _OWNED[case]
    frame, batch, _, _ = _both_paths(
        {column: [_RAISE] * 100}, {column: _PLAIN}, config, tmp_path, monkeypatch
    )
    assert frame == batch
    assert _severities(frame) == [(column, "error")]


@pytest.mark.parametrize("case", list(_OWNED))
def test_an_owned_passthrough_reports_a_failed_comparison_with_a_hit(case, tmp_path, monkeypatch):
    config, column = _OWNED[case]
    config = _swap_column(config, column, "email")
    frame, batch, _, _ = _both_paths(
        {"email": [_RAISE] * 100}, {"email": _EMAILS}, config, tmp_path, monkeypatch
    )
    assert frame == batch
    assert _severities(frame) == [("email", "error")]
    assert frame[0].source_compared is False


def _swap_column(config: Mapping[str, Any], old: str, new: str) -> dict[str, Any]:
    """The same config with every mention of column `old` renamed `new`."""

    def swap(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: swap(v) for k, v in node.items()}
        if isinstance(node, list):
            return [swap(v) for v in node]
        return new if node == old else node

    return swap(dict(config))


def test_a_proven_passthrough_in_a_sibling_table_stays_quiet(tmp_path, monkeypatch):
    """`u` sits beside the FK child `t`: its passthrough is the only writer, so it is exempt."""
    config = _fk_config("zip")
    config["tables"].append({"name": "u", "columns": [{"name": "zip", "strategy": "passthrough"}]})
    source = pd.DataFrame({"zip": [_RAISE] * 100})
    for out, expected in ((_PLAIN, []), (_EMAILS, [("zip", "info")])):
        findings = check_residual_pii(
            {"u": pd.DataFrame({"zip": out})}, config, source_frames={"u": source.copy()}
        )
        assert _severities(findings) == expected


def test_the_query_names_every_component_of_a_composite_child_key():
    config = {
        "version": 2,
        "tables": [{"name": "p", "columns": []}, {"name": "c", "columns": []}],
        "relationships": [
            {
                "parent": {"table": "p", "columns": ["a", "b"]},
                "children": [{"table": "c", "columns": ["x", "y"]}],
                "orphan_policy": "preserve",
            }
        ],
    }
    writes = standalone_writes(config, {"p": ["a", "b", "z"], "c": ["x", "y", "z"]})
    assert writes.get("c") == KnownSet(frozenset({"x", "y"}))
    assert [may_write(writes, "c", col) for col in ("x", "y", "z")] == [True, True, False]
    # The parent end is only looked up, so it writes nothing.
    assert writes["p"] == KnownEmpty()
    assert not may_write(writes, "p", "a")


def test_the_query_states_for_unknown_and_unnamed_tables():
    registry = get_default_registry()
    writes = written_columns_by_table(
        _config([{"name": "x", "strategy": "no_such_strategy"}]),
        schemas={"t": ["x"], "v": ["y"]},
        edges=(),
        registry=registry,
    )
    assert writes == {"t": Unknown(), "v": KnownEmpty()}
    assert may_write(writes, "absent", "y")


# ----- grading with an unknown source count ---------------------------------------------------


def _fact(
    *, detector: str, distinct: int, failed: bool, output_failed: bool = False, identical: int = 100
):
    error = "TypeError" if failed or output_failed else None
    return ColumnFacts(
        table="t",
        column="email",
        source_rows=100,
        output_rows=100,
        comparable_rows=100,
        identical_rows=identical,
        bytes_identical=identical == 100,
        source_distinct=0 if failed else distinct,
        output_distinct=0 if output_failed else distinct,
        detectors=(DetectorRate(detector, 1.0, "high"),),
        distinct_error=error,
        source_distinct_failed=failed,
    )


def _grade(strategy: str, fact: ColumnFacts, column: str = "email") -> tuple[str, ...]:
    config = _config([{"name": column, "strategy": strategy}])
    facts = {"t": {column: fact}}
    findings = residual_pii_findings(
        facts, config, writes=standalone_writes(config, {"t": [column]})
    )
    return tuple(f.severity for f in findings)


@pytest.mark.parametrize(
    "fact",
    [
        _fact(detector="email", distinct=1, failed=False),
        _fact(detector="email", distinct=2, failed=False),
        _fact(detector="email", distinct=0, failed=True),
    ],
    ids=["source count 1", "source count 2", "source count failed"],
)
def test_unchanged_hash_output_fails_whatever_the_source_count(fact):
    assert _grade("hash", fact) == ("fail",)


def test_a_failed_count_whose_final_grades_differ_is_an_error():
    grades = {_grade("faker", _fact(detector="email", distinct=n, failed=False))[0] for n in (1, 2)}
    assert len(grades) == 2
    assert _grade("faker", _fact(detector="email", distinct=0, failed=True)) == ("error",)


def test_a_failed_output_count_grades_with_the_known_source_count():
    for distinct in (1, 2):
        known = _grade("faker", _fact(detector="email", distinct=distinct, failed=False))
        output_only = _fact(detector="email", distinct=distinct, failed=False, output_failed=True)
        assert _grade("faker", output_only) == known


@pytest.mark.parametrize(("identical", "expected"), [(100, "fail"), (0, "info")])
def test_a_gated_hit_keeps_the_gated_grade_with_a_failed_count(identical, expected):
    def fact(failed: bool) -> ColumnFacts:
        return _fact(
            detector="mrn", distinct=0 if failed else 2, failed=failed, identical=identical
        )

    known = _grade("redact", fact(False), "customer_id")
    assert known == _grade("redact", fact(True), "customer_id") == (expected,)


# ----- inputs the query cannot read -----------------------------------------------------------


def test_a_relationship_the_profile_drops_leaves_every_column_may_written():
    """The child's key columns are not a list, so the profile drops the relationship. The query
    cannot name the key, so it answers {} and the passthrough key is still compared."""
    config = _fk_config("email")
    config["relationships"][0]["children"][0]["columns"] = "email"
    writes = standalone_writes(config, {"p": ["id"], "t": ["email"]})
    assert writes == {}
    assert may_write(writes, "t", "email")
    source = pd.DataFrame({"email": _EMAILS})
    findings = check_residual_pii({"t": source.copy()}, config, source_frames={"t": source.copy()})
    assert [(f.column, f.source_compared, f.source_identity_rate) for f in findings] == [
        ("email", True, 1.0)
    ]


def test_a_relationship_that_does_not_build_fails_the_check_by_class_name():
    """Key lists of different lengths make the relationship raise while it is built."""
    config = _fk_config("email")
    config["relationships"][0]["parent"]["columns"] = ["id", "id2"]
    source = pd.DataFrame({"email": _EMAILS})
    findings = check_residual_pii({"t": source.copy()}, config, source_frames={"t": source.copy()})
    assert [(f.table, f.column, f.severity) for f in findings] == [("", "", "error")]
    assert findings[0].message == "residual_pii check raised ValueError (see job log for details)"


def _op_names() -> set[str]:
    (union, *_) = typing.get_args(TransformOp)
    return {
        name
        for cls in typing.get_args(union)
        for name in typing.get_args(cls.model_fields["op"].annotation)
    }


def test_every_transform_op_is_classified_as_writing_or_not():
    """A new op stays red here until it joins `NON_WRITING_OPS` or the writing side."""
    assert _op_names() == NON_WRITING_OPS | {"derive"}
    assert "derive" not in NON_WRITING_OPS


@pytest.mark.parametrize(
    ("ops", "expected"),
    [
        ([{"op": "filter", "expr": "x > 1"}, {"op": "drop_column", "column": "y"}], KnownEmpty()),
        ([{"op": "derive", "column": "z", "expr": "x"}], KnownSet(frozenset({"z"}))),
        ([{"op": "pivot"}], Unknown()),
        ([{"op": "filter"}, {}], Unknown()),
    ],
)
def test_an_op_the_query_does_not_know_makes_its_table_unknown(ops, expected):
    config = {"version": 2, "tables": [{"name": "t", "columns": [], "transforms": ops}]}
    assert standalone_writes(config, {"t": ["x"]}) == {"t": expected}
