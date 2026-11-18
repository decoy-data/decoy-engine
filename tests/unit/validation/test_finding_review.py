"""INIT-WIZARD E2: `finding_edits` turns post-scan findings and decisions into config edits.

AT-E5: confirm gives one replacement built by the catalog writer; reject on a dismissible finding
gives one dismissal with every field; any other reject is refused; skip and a repeat reject give
nothing; decisions in any order give the same edits and the dismissal binds the column's final
strategy. The FK-shape cases cover key columns of a single, a composite and a self-referencing
relationship.
"""

from __future__ import annotations

import copy
import itertools
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from decoy_engine.detection.types import ModelRef
from decoy_engine.profiling import detector_entry
from decoy_engine.validation.finding_review import (
    ConfigEdit,
    FindingDecision,
    ReviewConflictError,
    ReviewDismissRefusedError,
    finding_edits,
)
from decoy_engine.validation.starter_review import (
    ReviewDuplicateError,
    ReviewEntryError,
    ReviewInputError,
    ReviewKeyColumnError,
    ReviewUnknownColumnError,
    ReviewVerdict,
    column_entry,
)

V = ReviewVerdict
CANARY = "CANARY-e2-91bc"
MODEL = ModelRef("en_core_web_md", "3.7.1")


def _config(**extra: Any) -> dict[str, Any]:
    return {
        "version": 2,
        "tables": [
            {
                "name": "customers",
                "columns": [
                    {"name": "id", "strategy": "hash", "namespace": "id"},
                    {"name": "email", "strategy": "passthrough"},
                    {"name": "notes", "strategy": "redact"},
                ],
            },
            {"name": "orders", "columns": [{"name": "cust", "strategy": "hash", "namespace": "k"}]},
        ],
        **extra,
    }


_STRATEGY = {"id": "hash", "email": "passthrough", "notes": "redact", "cust": "hash"}


def _row(column: str, detector: str, severity: str = "warning", **kw: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "table": "customers",
        "column": column,
        "detector_id": detector,
        "match_rate": 0.9,
        "sample_match_count": 3,
        "message": "",
        "band": None,
        "severity": severity,
        # What the plan said at scan time; the config above holds the same strategies.
        "configured_strategy": _STRATEGY.get(column),
        "source": "regex",
        "model": None,
        "dismissed": False,
        "promoted": False,
        "source_identity_rate": None,
        "source_compared": False,
    }
    row.update(kw)
    return row


def _report(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "post-scan-integrity/v3", "residual_pii": list(rows)}


def _decision(row: dict[str, Any], verdict: ReviewVerdict, **kw: Any) -> FindingDecision:
    model = row["model"]
    return FindingDecision(
        row["table"],
        row["column"],
        row["detector_id"],
        row["source"],
        None if model is None else ModelRef(model["id"], model["version"]),
        verdict,
        **kw,
    )


def _refusal(call: Any) -> ReviewInputError:
    with pytest.raises(ReviewInputError) as caught:
        call()
    err = caught.value
    assert err.__cause__ is None and err.__context__ is None
    assert CANARY not in str(err)
    return err


EMAIL = _row("email", "email")


def test_confirm_replaces_the_column_with_the_detector_default() -> None:
    edits = finding_edits(_config(), _report(EMAIL), [_decision(EMAIL, V.CONFIRM)])
    assert edits == (
        ConfigEdit(("tables", 0, "columns", 1), "replace", detector_entry("email", "email")),
    )


def test_confirm_on_a_column_with_no_entry_appends_one() -> None:
    row = _row("phone", "us_phone")
    edits = finding_edits(_config(), _report(row), [_decision(row, V.CONFIRM)])
    assert edits == (
        ConfigEdit(("tables", 0, "columns"), "append", detector_entry("us_phone", "phone")),
    )


def test_a_confirm_that_changes_nothing_gives_no_edit() -> None:
    config = _config()
    config["tables"][0]["columns"][1] = detector_entry("email", "email")
    assert finding_edits(config, _report(EMAIL), [_decision(EMAIL, V.CONFIRM)]) == ()


def test_edit_uses_the_catalog_writer_and_refuses_what_it_refuses() -> None:
    edits = finding_edits(
        _config(),
        _report(EMAIL),
        [_decision(EMAIL, V.EDIT, entry={"strategy": "truncate", "length": 2})],
    )
    assert edits[0].value == column_entry("truncate", "email", options={"length": 2})
    bad = _decision(EMAIL, V.EDIT, entry={"strategy": "truncate", "length": CANARY})
    assert _refusal(lambda: finding_edits(_config(), _report(EMAIL), [bad])).identity == (
        "config.entry_invalid"
    )


def test_a_ner_confirm_builds_text_redact_from_the_model_and_entity() -> None:
    row = _row(
        "notes", "person_name", source="ner", model={"id": MODEL.id, "version": MODEL.version}
    )
    edits = finding_edits(_config(), _report(row), [_decision(row, V.CONFIRM)])
    assert edits[0].value == column_entry(
        "text_redact", "notes", options={"ner_model": MODEL.id, "ner_entities": ["person_name"]}
    )


def test_reject_dismisses_a_warning_with_every_field() -> None:
    dismissal = {
        "table": "customers",
        "column": "email",
        "detector_id": "email",
        "source": "regex",
        "model_id": None,
        "model_version": None,
        "strategy": "passthrough",
    }
    block = finding_edits(_config(), _report(EMAIL), [_decision(EMAIL, V.REJECT)])
    assert block == (ConfigEdit(("post_scan",), "append_block", {"dismissed": [dismissal]}),)
    config = _config(post_scan={"integrity": True})
    inside = finding_edits(config, _report(EMAIL), [_decision(EMAIL, V.REJECT)])
    assert inside == (ConfigEdit(("post_scan", "dismissed"), "append", dismissal),)


def test_a_promoted_ner_finding_can_be_dismissed_with_its_model() -> None:
    row = _row(
        "notes",
        "person_name",
        severity="fail",
        source="ner",
        promoted=True,
        model={"id": MODEL.id, "version": MODEL.version},
    )
    config = _config(post_scan={"integrity": True})
    (edit,) = finding_edits(config, _report(row), [_decision(row, V.REJECT)])
    assert edit.value["model_id"] == MODEL.id and edit.value["model_version"] == MODEL.version
    assert edit.value["strategy"] == "redact"


@pytest.mark.parametrize(
    "row",
    [
        _row("email", "email", severity="fail"),
        _row("email", "email", severity="fail", source="ner", promoted=False),
        _row("email", "email", severity="warning", source_identity_rate=0.95, source_compared=True),
        _row("email", "email", severity="info"),
    ],
)
def test_any_other_reject_is_refused(row: dict[str, Any]) -> None:
    err = _refusal(lambda: finding_edits(_config(), _report(row), [_decision(row, V.REJECT)]))
    assert isinstance(err, ReviewDismissRefusedError)
    assert err.identity == "post_scan.dismiss_refused"


def test_skip_a_repeat_reject_and_an_already_dismissed_finding_give_nothing() -> None:
    assert finding_edits(_config(), _report(EMAIL), [_decision(EMAIL, V.SKIP)]) == ()
    done = {
        "table": "customers",
        "column": "email",
        "detector_id": "email",
        "source": "regex",
        "model_id": None,
        "model_version": None,
        "strategy": "passthrough",
    }
    config = _config(post_scan={"integrity": True, "dismissed": [done]})
    assert finding_edits(config, _report(EMAIL), [_decision(EMAIL, V.REJECT)]) == ()
    shown = _row("email", "email", severity="info", dismissed=True)
    assert finding_edits(_config(), _report(shown), [_decision(shown, V.REJECT)]) == ()


def test_the_dismissal_binds_the_columns_final_strategy() -> None:
    other = _row("email", "us_phone")
    report = _report(EMAIL, other)
    decisions = [_decision(EMAIL, V.REJECT), _decision(other, V.CONFIRM)]
    config = _config(post_scan={"integrity": True})
    final = detector_entry("us_phone", "email")
    for ordered in itertools.permutations(decisions):
        edits = finding_edits(config, report, list(ordered))
        assert edits[0] == ConfigEdit(("tables", 0, "columns", 1), "replace", final)
        assert edits[1].value["strategy"] == final["strategy"]
        assert len(edits) == 2


def test_decisions_in_any_order_give_the_same_edits() -> None:
    rows = [_row("email", "email"), _row("email", "us_phone"), _row("notes", "person_name")]
    decisions = [
        _decision(rows[0], V.CONFIRM),
        _decision(rows[1], V.CONFIRM),
        _decision(rows[2], V.REJECT),
    ]
    config = _config(post_scan={"integrity": True})
    conflict = _refusal(lambda: finding_edits(config, _report(*rows), decisions))
    assert (
        isinstance(conflict, ReviewConflictError)
        and conflict.identity == "post_scan.review_conflict"
    )
    ok = [_decision(rows[0], V.CONFIRM), _decision(rows[2], V.REJECT), _decision(rows[1], V.SKIP)]
    results = {
        repr(finding_edits(config, _report(*rows), list(p))) for p in itertools.permutations(ok)
    }
    assert len(results) == 1


def test_identical_proposals_on_one_column_fold_to_one_replacement() -> None:
    a, b = _row("email", "email"), _row("email", "us_phone")
    entry = {"strategy": "truncate", "length": 3}
    edits = finding_edits(
        _config(),
        _report(a, b),
        [_decision(a, V.EDIT, entry=entry), _decision(b, V.EDIT, entry=dict(entry))],
    )
    assert len(edits) == 1


def test_unknown_duplicate_and_inapplicable_decisions_are_refused() -> None:
    ghost = _row("nope", "email")
    unknown = _refusal(lambda: finding_edits(_config(), _report(EMAIL), [_decision(ghost, V.SKIP)]))
    assert isinstance(unknown, ReviewUnknownColumnError)
    twice = [_decision(EMAIL, V.SKIP), _decision(EMAIL, V.CONFIRM)]
    assert isinstance(
        _refusal(lambda: finding_edits(_config(), _report(EMAIL), twice)), ReviewDuplicateError
    )
    drop = _refusal(lambda: finding_edits(_config(), _report(EMAIL), [_decision(EMAIL, V.DROP)]))
    assert isinstance(drop, ReviewEntryError)
    other_model = _row("email", "email", source="ner", model={"id": "x", "version": "1"})
    miss = [_decision(other_model, V.SKIP)]
    assert isinstance(
        _refusal(lambda: finding_edits(_config(), _report(EMAIL), miss)), ReviewUnknownColumnError
    )


def test_a_malformed_or_foreign_report_is_refused() -> None:
    for report in (
        {"schema_version": "post-scan-integrity/v9", "residual_pii": []},
        {"residual_pii": []},
        _report({**EMAIL, "source": "magic"}),
        _report({**EMAIL, "table": 7}),
    ):
        assert isinstance(
            _refusal(lambda r=report: finding_edits(_config(), r, [])), ReviewEntryError
        )


def test_a_stale_report_cannot_dismiss_under_a_strategy_nobody_reviewed() -> None:
    """The finding came from `passthrough`; the column is `redact` now and the review leaves it."""
    config = _config(post_scan={"integrity": True})
    config["tables"][0]["columns"][1]["strategy"] = "redact"
    err = _refusal(lambda: finding_edits(config, _report(EMAIL), [_decision(EMAIL, V.REJECT)]))
    assert err.identity == "pre_scan.review_stale"
    assert (err.table, err.column) == ("customers", "email")
    # The same review changing the strategy is not stale: the dismissal binds the new one.
    other = _row("email", "us_phone")
    edits = finding_edits(
        config, _report(EMAIL, other), [_decision(EMAIL, V.REJECT), _decision(other, V.CONFIRM)]
    )
    assert edits[-1].value["strategy"] == detector_entry("us_phone", "email")["strategy"]


def test_a_v2_report_row_without_source_or_model_reads_as_regex() -> None:
    row = {k: v for k, v in EMAIL.items() if k not in ("source", "model", "dismissed", "promoted")}
    report = {"schema_version": "post-scan-integrity/v2", "residual_pii": [row]}
    decision = FindingDecision("customers", "email", "email", "regex", None, V.REJECT)
    config = _config(post_scan={"integrity": True})
    (edit,) = finding_edits(config, report, [decision])
    assert edit.value["source"] == "regex" and edit.value["model_id"] is None


@pytest.mark.parametrize(
    "rows",
    [
        [None],
        ["email"],
        [[1, 2]],
        [{**EMAIL, "model": {"id": ["x"], "version": "1"}}],
        [{**EMAIL, "model": {"id": "x", "version": {}}}],
        [{**EMAIL, "model": {"version": "1"}}],
        [{**EMAIL, "model": "en_core"}],
        [{**EMAIL, "detector_id": ["email"]}],
        [{**EMAIL, "configured_strategy": 3}],
        [{**EMAIL, "source_identity_rate": "high"}],
    ],
)
def test_a_malformed_row_raises_the_value_free_error(rows: list[Any]) -> None:
    report = {"schema_version": "post-scan-integrity/v3", "residual_pii": rows}
    err = _refusal(lambda: finding_edits(_config(), report, []))
    assert isinstance(err, ReviewEntryError)


_V3_FIELDS = [
    "table",
    "column",
    "detector_id",
    "severity",
    "match_rate",
    "configured_strategy",
    "sample_match_count",
    "message",
    "source_identity_rate",
    "source_compared",
    "source",
    "model",
    "band",
    "dismissed",
    "promoted",
]


@pytest.mark.parametrize("missing", _V3_FIELDS)
def test_a_v3_row_must_carry_every_field(missing: str) -> None:
    """The v2 defaults must not leak into v3: a v3 row missing a field is malformed."""
    row = {k: v for k, v in EMAIL.items() if k != missing}
    err = _refusal(lambda: finding_edits(_config(), _report(row), []))
    assert isinstance(err, ReviewEntryError)


@pytest.mark.parametrize("dropped", ["source", "model", "band", "dismissed", "promoted"])
def test_the_v3_only_fields_default_for_a_v2_row_alone(dropped: str) -> None:
    v2 = {
        k: v
        for k, v in EMAIL.items()
        if k not in ("source", "model", "band", "dismissed", "promoted")
    }
    assert (
        finding_edits(
            _config(), {"schema_version": "post-scan-integrity/v2", "residual_pii": [v2]}, []
        )
        == ()
    )
    v3 = {k: v for k, v in EMAIL.items() if k != dropped}
    _refusal(lambda: finding_edits(_config(), _report(v3), []))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dismissed", "true"),
        ("dismissed", 1),
        ("promoted", "yes"),
        ("promoted", 0),
        ("source_compared", "False"),
        ("sample_match_count", True),
        ("sample_match_count", "3"),
        ("match_rate", True),
        ("match_rate", "0.9"),
        ("message", 3),
        ("band", 7),
        ("severity", "critical"),
        ("severity", ["warning"]),
        ("source", ["regex"]),
    ],
)
@pytest.mark.parametrize("version", ["post-scan-integrity/v3", "post-scan-integrity/v2"])
def test_every_consumed_field_is_type_checked(field: str, value: Any, version: str) -> None:
    row = {**EMAIL, field: value}
    report = {"schema_version": version, "residual_pii": [row]}
    assert isinstance(_refusal(lambda: finding_edits(_config(), report, [])), ReviewEntryError)


@pytest.mark.parametrize("version", [["post-scan-integrity/v3"], {"a": 1}, 3, None, b"x"])
def test_an_unhashable_or_foreign_schema_version_is_a_coded_refusal(version: Any) -> None:
    report = {"schema_version": version, "residual_pii": []}
    assert isinstance(_refusal(lambda: finding_edits(_config(), report, [])), ReviewEntryError)


def test_a_report_that_is_not_a_mapping_is_refused() -> None:
    for report in ([], "report", None):
        assert isinstance(
            _refusal(lambda r=report: finding_edits(_config(), r, [])), ReviewEntryError
        )


def test_a_malformed_container_raises_the_value_free_error() -> None:
    for bad in (5, "rows", {"a": 1}):
        report = {"schema_version": "post-scan-integrity/v3", "residual_pii": bad}
        assert isinstance(
            _refusal(lambda r=report: finding_edits(_config(), r, [])), ReviewEntryError
        )


# FK shapes: single, composite and self-referencing keys ---------------------------------------


def _keyed(parent: tuple[str, list[str]], children: list[tuple[str, list[str]]]) -> dict[str, Any]:
    config = _config()
    config["relationships"] = [
        {
            "parent": {"table": parent[0], "columns": parent[1]},
            "children": [{"table": t, "columns": c} for t, c in children],
            "namespace": "k",
            "orphan_policy": "warn",
        }
    ]
    return config


FK_SHAPES = {
    "single": _keyed(("customers", ["id"]), [("orders", ["cust"])]),
    "composite": _keyed(("customers", ["id", "email"]), [("orders", ["cust", "cust"])]),
    "self": _keyed(("customers", ["id"]), [("customers", ["id"])]),
}


@pytest.mark.parametrize("shape", sorted(FK_SHAPES))
def test_key_columns_keep_the_namespace_and_refuse_unsafe_strategies(shape: str) -> None:
    config = FK_SHAPES[shape]
    row = _row("id", "ssn")
    unsafe = (
        _decision(row, V.EDIT, entry={"strategy": "redact"}),
        _decision(row, V.EDIT, entry={"strategy": "categorical", "categories": ["a"]}),
        _decision(_row("id", "email"), V.CONFIRM),  # the email default is faker
    )
    for decision in unsafe:
        err = _refusal(lambda d=decision: finding_edits(config, _report(row, EMAIL_ID), [d]))
        assert isinstance(err, ReviewKeyColumnError)
        assert err.identity == "config.key_column_not_join_safe"
    (edit,) = finding_edits(config, _report(row), [_decision(row, V.CONFIRM)])
    assert edit.value["strategy"] == "hash" and edit.value["namespace"] == "k"


EMAIL_ID = _row("id", "email")


def test_a_join_safe_edit_on_a_key_keeps_the_relationship_namespace() -> None:
    config = FK_SHAPES["single"]
    row = _row("id", "ssn")
    (edit,) = finding_edits(
        config, _report(row), [_decision(row, V.EDIT, entry={"strategy": "fpe", "namespace": "z"})]
    )
    assert edit.value["namespace"] == "k" and edit.value["strategy"] == "fpe"


def test_the_inputs_are_not_changed() -> None:
    config, report = _config(), _report(EMAIL)
    before = copy.deepcopy((config, report))
    finding_edits(config, report, [_decision(EMAIL, V.REJECT)])
    assert (config, report) == before


# Property ----------------------------------------------------------------------------------

_PROP_ROWS = [
    _row("email", "email"),
    _row("email", "us_phone"),
    _row("email", "ssn", severity="fail"),
    _row("notes", "person_name", source="ner", model={"id": MODEL.id, "version": MODEL.version}),
    _row("notes", "address"),
]
_PROP_ENTRIES = [
    None,
    {"strategy": "truncate", "length": 3},
    {"strategy": "redact"},
]


@settings(max_examples=80, deadline=None, derandomize=True)
@given(data=st.data())
def test_property_edits_do_not_depend_on_decision_order(data: st.DataObject) -> None:
    decisions = []
    for row in _PROP_ROWS:
        verdict = data.draw(st.sampled_from([V.CONFIRM, V.REJECT, V.EDIT, V.SKIP, None]))
        if verdict is None:
            continue
        entry = data.draw(st.sampled_from(_PROP_ENTRIES[1:])) if verdict is V.EDIT else None
        decisions.append(_decision(row, verdict, entry=entry))
    config = _config(post_scan={"integrity": True})
    report = _report(*_PROP_ROWS)

    def run(order: list[FindingDecision]) -> Any:
        try:
            return finding_edits(config, report, order)
        except ReviewInputError as err:
            return err.identity

    first = run(decisions)
    assert run(list(reversed(decisions))) == first
    assert run(data.draw(st.permutations(decisions))) == first
    if not isinstance(first, str):
        replaced = [e.path for e in first if e.op == "replace"]
        assert len(replaced) == len(set(replaced))
