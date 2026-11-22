"""INIT-WIZARD E1: `column_entry` and `apply_review` fold review verdicts into a starter config.

AT-E1 (every verdict, drop and the empty-table refusal), AT-E2 (a non-live suggestion applies only
on a matching confirm), AT-E3 (refusals are coded, name no value and carry no exception context),
AT-E4 (Hypothesis property over random decision sets, plain and keyed starters) and AT-E8 (no
retired product word in any note). The verdict results in AT-E1 are compiled through
`profile_source` and `compile_plan`; the property runs the profile-free plan checks on each
success.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from decoy_engine import strategy_catalog
from decoy_engine.config import PipelineConfig, parse_pipeline_config
from decoy_engine.contracts.column_shape import NO_SOURCES
from decoy_engine.contracts.strategy_requirements import SHAPE_REQUIREMENTS_BY_STRATEGY
from decoy_engine.detection.ner import DEFAULT_NER_MODEL, model_installed, spacy_installed
from decoy_engine.detection.types import ModelRef
from decoy_engine.plan import compile_plan, run_config_only_checks
from decoy_engine.plan.checks import check_required_strategy_settings
from decoy_engine.profile import profile_source
from decoy_engine.profiling import (
    DETECTOR_DESCRIPTORS,
    ColumnSuggestion,
    StarterConfig,
    detector_entry,
    scan_sources,
    starter_config,
    swap_placeholder_namespaces,
)
from decoy_engine.validation.starter_review import (
    ReviewDecision,
    ReviewInputError,
    ReviewVerdict,
    SuggestionRef,
    apply_review,
    column_entry,
)
from tests._ner import needs_ner, ner_available

CANARY = "CANARY-e1-7f3a"
V = ReviewVerdict


def _compile(config: dict[str, Any]) -> Any:
    dumped = PipelineConfig.model_validate(config).model_dump()
    return compile_plan(
        dumped, profile_source(dumped, seed=1), decoy_engine_version="test", sources=NO_SOURCES
    )


def _sources(root: Path) -> dict[str, dict[str, Any]]:
    pd.DataFrame(
        {
            "customer_id": range(1, 31),
            "email": [f"user{i}@example.com" for i in range(1, 31)],
            "memo": [f"{CANARY}-{i}" for i in range(1, 31)],
            "zip5": [f"{i + 10000}" for i in range(1, 31)],
        }
    ).to_csv(root / "customers.csv", index=False)
    pd.DataFrame(
        {
            "order_id": range(1, 41),
            "customer_email": [f"user{(i % 30) + 1}@example.com" for i in range(40)],
            "amount": [i * 3 for i in range(40)],
        }
    ).to_csv(root / "orders.csv", index=False)
    return {
        name: {
            "type": "file",
            "format": "csv",
            "path": str(root / f"{name}.csv"),
            "has_header": True,
        }
        for name in ("customers", "orders")
    }


def _relationship() -> dict[str, Any]:
    return {
        "parent": {"table": "customers", "columns": ["email"]},
        "children": [{"table": "orders", "columns": ["customer_email"]}],
        "orphan_policy": "warn",
        "namespace": "cust",
    }


@pytest.fixture(scope="module")
def starter(tmp_path_factory: pytest.TempPathFactory) -> StarterConfig:
    return starter_config(scan_sources(_sources(tmp_path_factory.mktemp("review"))))


@pytest.fixture(scope="module")
def keyed(tmp_path_factory: pytest.TempPathFactory) -> StarterConfig:
    sources = _sources(tmp_path_factory.mktemp("keyed"))
    return starter_config(scan_sources(sources), relationships=[_relationship()])


def _entry_of(result: StarterConfig, table: str, column: str) -> dict[str, Any] | None:
    cols = next(t for t in result.config["tables"] if t["name"] == table)["columns"]
    return next((c for c in cols if c["name"] == column), None)


def _table(result: StarterConfig, table: str) -> dict[str, Any]:
    return next(t for t in result.config["tables"] if t["name"] == table)


def _ref(s: ColumnSuggestion) -> SuggestionRef:
    return SuggestionRef(s.source, s.detector_id, s.model, s.strategy)


def _suggestion(result: StarterConfig, table: str, column: str) -> ColumnSuggestion:
    return next(s for s in result.suggestions if (s.table, s.column) == (table, column))


def _refusal(call: Any) -> ReviewInputError:
    with pytest.raises(ReviewInputError) as caught:
        call()
    err = caught.value
    assert err.__cause__ is None
    assert err.__context__ is None
    assert CANARY not in str(err)
    return err


# AT-E1 ------------------------------------------------------------------------------------


def test_every_verdict_on_one_column(starter: StarterConfig) -> None:
    before = _entry_of(starter, "customers", "email")
    assert before is not None
    note = starter.notes[("customers", "email")]
    sug = _suggestion(starter, "customers", "email")
    assert sug.live and sug.source == "regex" and sug.detector_id == "email"

    def one(verdict: ReviewVerdict, **kw: Any) -> StarterConfig:
        return apply_review(starter, [ReviewDecision("customers", "email", verdict, **kw)])

    confirm = one(V.CONFIRM, confirmed=_ref(sug))
    assert _entry_of(confirm, "customers", "email") == before
    assert ("customers", "email") not in confirm.notes

    reject = one(V.REJECT)
    assert _entry_of(reject, "customers", "email") == column_entry("redact", "email")
    assert reject.notes[("customers", "email")] == "rejected (suggested faker)"

    edit = one(V.EDIT, entry={"strategy": "truncate", "length": 4})
    assert _entry_of(edit, "customers", "email") == column_entry(
        "truncate", "email", options={"length": 4}
    )
    assert ("customers", "email") not in edit.notes

    skip = one(V.SKIP)
    assert _entry_of(skip, "customers", "email") == before
    assert skip.notes[("customers", "email")] == note

    drop = one(V.DROP)
    assert _entry_of(drop, "customers", "email") is None
    assert _table(drop, "customers")["transforms"] == [{"op": "drop_column", "columns": ["email"]}]
    assert ("customers", "email") not in drop.notes
    for result in (confirm, reject, edit, skip, drop):
        _compile(result.config)
    assert starter.config["tables"][0]["columns"][1] == before  # the input is not mutated


def test_a_second_drop_joins_the_one_transform_in_source_order(starter: StarterConfig) -> None:
    first = apply_review(starter, [ReviewDecision("customers", "zip5", V.DROP)])
    both = apply_review(
        first,
        [ReviewDecision("customers", "memo", V.DROP), ReviewDecision("customers", "email", V.DROP)],
    )
    ops = _table(both, "customers")["transforms"]
    assert ops == [{"op": "drop_column", "columns": ["zip5", "email", "memo"]}]
    _compile(both.config)


def test_several_emptied_tables_name_the_same_table_in_any_decision_order(
    starter: StarterConfig,
) -> None:
    tables = [t["name"] for t in starter.config["tables"]]
    assert len(tables) >= 2
    every = [
        ReviewDecision(t, c["name"], V.DROP) for t in tables for c in _table(starter, t)["columns"]
    ]
    named = {
        _refusal(lambda order=order: apply_review(starter, order)).table
        for order in (every, list(reversed(every)))
    }
    assert named == {sorted(tables)[0]}


def test_dropping_every_column_is_refused_but_all_but_one_passes(starter: StarterConfig) -> None:
    names = [c["name"] for c in _table(starter, "orders")["columns"]]
    every = [ReviewDecision("orders", n, V.DROP) for n in names]
    err = _refusal(lambda: apply_review(starter, every))
    assert err.identity == "pre_scan.review_empty_table"
    assert err.table == "orders" and "orders" in str(err)
    result = apply_review(starter, every[:-1])
    assert [c["name"] for c in _table(result, "orders")["columns"]] == names[-1:]
    _compile(result.config)


# AT-E2 ------------------------------------------------------------------------------------


def _with_classifier(starter: StarterConfig) -> tuple[StarterConfig, ColumnSuggestion]:
    classifier = ColumnSuggestion(
        "customers",
        "memo",
        "faker",
        provider="person_first_name",
        namespace="memo",
        source="classifier",
        detector_id="first_name",
        model=ModelRef("lgbm-v1", "1.0.0"),
        band="review",
        entry=column_entry("faker", "memo", options={"provider": "person_first_name"}),
        live=False,
    )
    return dataclasses.replace(starter, suggestions=(*starter.suggestions, classifier)), classifier


def test_a_classifier_suggestion_is_never_live_and_applies_only_on_a_matching_confirm(
    starter: StarterConfig,
) -> None:
    plus, classifier = _with_classifier(starter)
    assert _entry_of(plus, "customers", "memo") == _entry_of(starter, "customers", "memo")
    assert all(s.live for s in starter.suggestions if s.source == "regex")
    ok = apply_review(
        plus, [ReviewDecision("customers", "memo", V.CONFIRM, confirmed=_ref(classifier))]
    )
    assert _entry_of(ok, "customers", "memo") == dict(classifier.entry)
    wrong_model = dataclasses.replace(_ref(classifier), model=ModelRef("lgbm-v1", "2.0.0"))
    wrong_model_none = dataclasses.replace(_ref(classifier), model=None)
    wrong_strategy = dataclasses.replace(_ref(classifier), strategy="hash")
    wrong_detector = dataclasses.replace(_ref(classifier), detector_id="last_name")
    for ref, field in (
        (wrong_model, "model"),
        (wrong_model_none, "model"),
        (wrong_strategy, "strategy"),
        (wrong_detector, "detector"),
    ):
        err = _refusal(
            lambda r=ref: apply_review(
                plus, [ReviewDecision("customers", "memo", V.CONFIRM, confirmed=r)]
            )
        )
        assert err.identity == "pre_scan.review_stale" and f"{field} differs" in str(err)
    none = _refusal(lambda: apply_review(plus, [ReviewDecision("customers", "memo", V.CONFIRM)]))
    assert none.identity == "pre_scan.review_stale"


# AT-E3 ------------------------------------------------------------------------------------


def test_unknown_and_duplicate_columns_are_refused_with_their_codes(starter: StarterConfig) -> None:
    unknown = _refusal(lambda: apply_review(starter, [ReviewDecision("customers", "nope", V.SKIP)]))
    assert unknown.identity == "pre_scan.review_unknown_column"
    assert (unknown.table, unknown.column) == ("customers", "nope")
    no_table = _refusal(lambda: apply_review(starter, [ReviewDecision("nope", "email", V.SKIP)]))
    assert no_table.identity == "pre_scan.review_unknown_column"
    twice = [
        ReviewDecision("customers", "email", V.SKIP),
        ReviewDecision("customers", "email", V.DROP),
    ]
    assert _refusal(lambda: apply_review(starter, twice)).identity == "pre_scan.review_duplicate"


@pytest.mark.parametrize(
    ("strategy", "options", "option"),
    [
        ("nope", {}, None),
        ("formula", {}, None),  # known but not offered for review
        ("truncate", {"length": True}, "length"),  # a bool is not an int
        ("truncate", {"length": "3"}, "length"),
        ("truncate", {"length": 3, "bogus": 1}, "bogus"),
        ("truncate", {"length": 3, "keep": CANARY}, "keep"),  # outside choices
        ("truncate", {"keep": "tail"}, "length"),  # required option missing
        ("truncate", {"provider_config": {"length": 3}}, "provider_config"),  # misplaced
        ("faker", {"provider": ["a"]}, "provider"),
        ("categorical", {"categories": [1, 2]}, "categories"),
        ("categorical", {"categories": ["a"], "weights": [True]}, "weights"),
        ("hash", {"salt": CANARY}, "salt"),
    ],
)
def test_column_entry_refuses_what_the_catalog_does_not_allow(
    strategy: str, options: dict[str, Any], option: str | None
) -> None:
    err = _refusal(lambda: column_entry(strategy, "c", options=options))
    assert err.identity == "config.entry_invalid"
    assert err.column == "c" and err.option == option


def test_column_entry_places_options_and_sets_the_namespace() -> None:
    assert column_entry("truncate", "c", options={"length": 2}) == {
        "name": "c",
        "strategy": "truncate",
        "provider_config": {"length": 2},
    }
    assert column_entry("faker", "c", options={"provider": "uuid", "deterministic": True}) == {
        "name": "c",
        "strategy": "faker",
        "provider": "uuid",
        "namespace": "c",
        "deterministic": True,
    }
    assert column_entry("hash", "c")["namespace"] == "c"
    assert column_entry("hash", "c", namespace="shared")["namespace"] == "shared"
    assert "namespace" not in column_entry("redact", "c")
    ner = column_entry(
        "text_redact", "c", options={"ner_model": "en_core_web_md", "ner_entities": ["person_name"]}
    )
    assert ner["provider_config"]["ner"] == {"model": "en_core_web_md", "entities": ["person_name"]}


def test_key_columns_keep_their_namespace_and_refuse_unsafe_changes(keyed: StarterConfig) -> None:
    table, col = "customers", "email"
    start = _entry_of(keyed, table, col)
    assert start is not None and start["strategy"] == "hash" and start["namespace"] == "cust"

    ok = apply_review(
        keyed,
        [ReviewDecision(table, col, V.EDIT, entry={"strategy": "hash", "namespace": "other"})],
    )
    assert _entry_of(ok, table, col) == start  # the relationship's namespace wins
    reject = apply_review(keyed, [ReviewDecision(table, col, V.REJECT)])
    assert _entry_of(reject, table, col) == start
    for decision in (
        ReviewDecision(table, col, V.DROP),
        ReviewDecision(table, col, V.EDIT, entry={"strategy": "redact"}),
        ReviewDecision(table, col, V.EDIT, entry={"strategy": "categorical", "categories": ["a"]}),
    ):
        err = _refusal(lambda d=decision: apply_review(keyed, [d]))
        assert err.identity == "config.key_column_not_join_safe"
        assert (err.table, err.column) == (table, col)
    _compile(ok.config)


def test_a_config_the_validator_refuses_is_a_coded_error_without_values(
    starter: StarterConfig,
) -> None:
    bad = dataclasses.replace(
        starter, config={**starter.config, "global_settings": {"seed": CANARY}}
    )
    err = _refusal(lambda: apply_review(bad, [ReviewDecision("customers", "email", V.SKIP)]))
    assert err.identity == "config.entry_invalid"


# AT-E4 ------------------------------------------------------------------------------------


def _ner_runnable(entry: dict[str, Any]) -> bool:
    model = entry.get("ner_model", DEFAULT_NER_MODEL)
    return spacy_installed() and model_installed(model)


def _uses_ner(entry: dict[str, Any]) -> bool:
    return "ner_model" in entry or "ner_entities" in entry


def _example_entries() -> list[dict[str, Any]]:
    """Every wizard example entry the config validator accepts on this machine.

    An entry that names an NER model validates only where spaCy and the model are installed (the
    validator reports `ner_spacy_not_installed` otherwise), so the property draws those only
    there. The two NER tests below pin both outcomes.
    """
    rows = []
    for info in strategy_catalog():
        if info.offer_in_wizard:
            shaped = SHAPE_REQUIREMENTS_BY_STRATEGY.get(info.name)
            if shaped is not None and shaped.cast_declared:
                # A wizard entry has no F06 cast, which these need on a csv text column (E3). The
                # starter and the wizard learn that in E5; until then they are not drawn here.
                continue
            entry = {"strategy": info.name, **info.example_options}
            if not _uses_ner(entry) or _ner_runnable(entry):
                rows.append(entry)
    return rows


@needs_ner
def test_an_ner_edit_applies_where_the_model_is_installed(starter: StarterConfig) -> None:
    entry = {
        "strategy": "text_redact",
        "ner_model": DEFAULT_NER_MODEL,
        "ner_entities": ["person_name"],
    }
    result = apply_review(starter, [ReviewDecision("customers", "email", V.EDIT, entry=entry)])
    assert _entry_of(result, "customers", "email")["provider_config"]["ner"]["entities"] == [
        "person_name"
    ]


@pytest.mark.skipif(ner_available(), reason="the model is installed; the refusal needs it absent")
def test_an_ner_edit_is_refused_without_values_where_spacy_is_missing(
    starter: StarterConfig,
) -> None:
    entry = {
        "strategy": "text_redact",
        "ner_model": DEFAULT_NER_MODEL,
        "ner_entities": ["person_name"],
    }
    err = _refusal(
        lambda: apply_review(starter, [ReviewDecision("customers", "email", V.EDIT, entry=entry)])
    )
    assert err.identity == "config.entry_invalid"


@st.composite
def _decision_sets(draw: Any, starter: StarterConfig, *, drop_all: bool) -> list[ReviewDecision]:
    examples = _example_entries()
    out: list[ReviewDecision] = []
    for table in starter.config["tables"]:
        names = [c["name"] for c in table["columns"]]
        # About one table in five is dropped whole, so the empty-table refusal is exercised.
        whole = drop_all and draw(st.sampled_from([False, False, False, False, True]))
        for name in names:
            if not whole and draw(st.booleans()):
                continue
            verdict = V.DROP if whole else draw(st.sampled_from(list(V)))
            kw: dict[str, Any] = {}
            if verdict is V.EDIT:
                kw["entry"] = draw(st.sampled_from(examples))
            if verdict is V.CONFIRM:
                kw["confirmed"] = _ref(_suggestion(starter, table["name"], name))
            out.append(ReviewDecision(table["name"], name, verdict, **kw))
    return draw(st.permutations(out))


KEY_COLUMNS = {("customers", "email"), ("orders", "customer_email")}


@settings(
    max_examples=80,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(data=st.data())
def test_property_random_decision_sets(
    starter: StarterConfig, keyed: StarterConfig, data: st.DataObject
) -> None:
    on_keys = data.draw(st.booleans())
    base = keyed if on_keys else starter
    decisions = data.draw(_decision_sets(base, drop_all=True))
    join_safe = {i.name for i in strategy_catalog() if i.join_safe}
    dropped: dict[str, set[str]] = {}
    for d in decisions:
        if d.verdict is V.DROP:
            dropped.setdefault(d.table, set()).add(d.column)
    emptied = [
        t["name"]
        for t in base.config["tables"]
        if len(dropped.get(t["name"], ())) == len(t["columns"])
    ]
    key_violation = on_keys and any(
        (d.table, d.column) in KEY_COLUMNS
        and (d.verdict is V.DROP or (d.verdict is V.EDIT and d.entry["strategy"] not in join_safe))
        for d in decisions
    )
    if key_violation:
        err = _refusal(lambda: apply_review(base, decisions))
        assert err.identity == "config.key_column_not_join_safe"
        return
    if emptied:
        err = _refusal(lambda: apply_review(base, decisions))
        assert err.identity == "pre_scan.review_empty_table"
        # Several emptied tables: the error names the same one whatever the decision order.
        again = _refusal(lambda: apply_review(base, list(reversed(decisions))))
        assert again.identity == err.identity and again.table == err.table
        return
    result = apply_review(base, decisions)
    parse_pipeline_config(result.config)
    run_config_only_checks(swap_placeholder_namespaces(result.config)[0])
    check_required_strategy_settings(
        result.config, sources=NO_SOURCES
    )  # every namespace-needing entry has one
    named = {(d.table, d.column) for d in decisions}
    for table in base.config["tables"]:
        kept = {c["name"] for c in _table(result, table["name"])["columns"]}
        assert kept and kept.isdisjoint(dropped.get(table["name"], set()))
        gone = {
            n for op in _table(result, table["name"]).get("transforms", []) for n in op["columns"]
        }
        assert gone == dropped.get(table["name"], set())
        for column in table["columns"]:
            slot = (table["name"], column["name"])
            if slot not in named:
                assert _entry_of(result, *slot) == column
            elif on_keys and slot in KEY_COLUMNS:
                entry = _entry_of(result, *slot)
                if entry is not None:
                    assert entry["namespace"] == "cust" and entry["strategy"] in join_safe
    assert result.config["tables"] is not base.config["tables"]
    again = apply_review(base, list(reversed(decisions)))
    assert again.config == result.config and dict(again.notes) == dict(result.notes)


# EDIT entries through apply_review, ColumnSuggestion guard, catalog parity ---------------------


@pytest.mark.parametrize(
    ("entry", "option"),
    [
        ({"strategy": "truncate", "length": True}, "length"),
        ({"strategy": "truncate", "length": 3, "bogus": CANARY}, "bogus"),
        ({"strategy": "truncate", "length": 3, "keep": CANARY}, "keep"),
        ({"strategy": 5}, None),
        ({"strategy": ["hash"]}, None),
        ({"length": 3}, None),
        ({"strategy": "hash", "namespace": "   "}, "namespace"),
        ({"strategy": "hash", "namespace": 7}, "namespace"),
    ],
)
def test_invalid_edit_entries_are_refused_through_apply_review(
    starter: StarterConfig, entry: dict[str, Any], option: str | None
) -> None:
    decision = ReviewDecision("customers", "email", V.EDIT, entry=entry)
    err = _refusal(lambda: apply_review(starter, [decision]))
    assert err.identity == "config.entry_invalid"
    assert (err.table, err.column, err.option) == ("customers", "email", option)


def test_a_config_the_plan_checks_refuse_is_a_coded_error_without_values(
    starter: StarterConfig,
) -> None:
    # The catalog does not know provider names; the profile-free plan checks do.
    bad = ReviewDecision(
        "customers", "email", V.EDIT, entry={"strategy": "faker", "provider": CANARY}
    )
    err = _refusal(lambda: apply_review(starter, [bad]))
    assert err.identity == "config.entry_invalid"
    assert "unknown_provider" in str(err) and "customers" in str(err)


def test_a_blank_namespace_is_refused_by_the_entry_writer() -> None:
    for blank in ("", " ", "\t\n"):
        err = _refusal(lambda b=blank: column_entry("hash", "c", namespace=b))
        assert err.option == "namespace"


def test_the_base_error_cannot_be_raised_directly() -> None:
    with pytest.raises(TypeError):
        ReviewInputError("text")


@pytest.mark.parametrize(
    "bad",
    [
        {"source": "classifier", "live": True, "detector_id": "x"},
        {"entry": {"name": "other", "strategy": "faker", "namespace": "c"}, "namespace": "c"},
        {"entry": {"name": "c", "strategy": "hash", "namespace": "c"}, "namespace": "c"},
        {"entry": {"name": "c", "strategy": "faker", "namespace": "z"}, "namespace": "c"},
        {"entry": {"name": "c", "strategy": "faker"}, "namespace": "c"},
    ],
)
def test_a_suggestion_whose_parts_disagree_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        ColumnSuggestion("t", "c", "faker", **bad)


def test_a_consistent_suggestion_is_accepted() -> None:
    entry = {"name": "c", "strategy": "faker", "namespace": "c", "provider": "uuid"}
    assert ColumnSuggestion("t", "c", "faker", namespace="c", entry=entry).entry == entry
    assert ColumnSuggestion("t", "c", "faker", source="classifier", live=False).live is False


_NOT_OFFERED = {("fpe", "validate_luhn")}  # a starter setting the wizard catalog does not offer


def test_every_starter_choice_matches_what_the_entry_writer_builds() -> None:
    checked = 0
    for detector_id, descriptor in DETECTOR_DESCRIPTORS.items():
        choice = descriptor.starter
        if choice is None:
            continue
        options: dict[str, Any] = {}
        if choice.provider:
            options["provider"] = choice.provider
        options.update(
            {
                k: v
                for k, v in choice.provider_config.items()
                if (choice.strategy, k) not in _NOT_OFFERED
            }
        )
        date_format = "%Y-%m-%d" if choice.detected_date_format else None
        if date_format:
            options["date_format"] = date_format
        built = column_entry(choice.strategy, "c", options=options)
        starter_entry = detector_entry(detector_id, "c", date_format=date_format)
        assert starter_entry is not None
        for entry in (built, starter_entry):
            entry.pop("namespace", None)
            for name in ("validate_luhn",):
                entry.get("provider_config", {}).pop(name, None)
        assert built == starter_entry, detector_id
        checked += 1
    assert checked > 10


# AT-E8 ------------------------------------------------------------------------------------


def test_no_note_or_descriptor_copy_names_the_retired_product_word(starter: StarterConfig) -> None:
    from tests.sentry.test_no_residual_removed_surface import RETIRED_NAME

    texts = list(starter.notes.values())
    texts += [d.starter.review for d in DETECTOR_DESCRIPTORS.values() if d.starter is not None]
    assert texts
    assert [t for t in texts if RETIRED_NAME in t.lower()] == []


# S4b --------------------------------------------------------------------------------------


def _date_starter(tmp_path: Path) -> StarterConfig:
    path = tmp_path / "d.csv"
    pd.DataFrame({"born": ["15.01.2024", "16.02.2024", "17.03.2024"] * 4}).to_csv(path, index=False)
    src = {"d": {"type": "file", "format": "csv", "path": str(path), "has_header": True}}
    return starter_config(scan_sources(src))


def test_starter_review_keeps_required_format(tmp_path: Path) -> None:
    starter = _date_starter(tmp_path)
    (suggestion,) = starter.suggestions
    assert suggestion.strategy == "date_shift"
    entry = starter.config["tables"][0]["columns"][0]
    assert entry["provider_config"]["date_format"] == "%d.%m.%Y"
    assert detector_entry("eu_date", "born", date_format="%d.%m.%Y") == entry
    ref = SuggestionRef(
        suggestion.source, suggestion.detector_id, suggestion.model, suggestion.strategy
    )
    confirm = ReviewDecision("d", "born", V.CONFIRM, confirmed=ref)
    skip = ReviewDecision("d", "born", V.SKIP)
    for decision in (confirm, skip):
        out = apply_review(starter, [decision])
        assert out.config["tables"][0]["columns"][0] == entry
    # EDIT without a format is refused; a valid EDIT passes the config-only checks.
    with pytest.raises(ReviewInputError):
        apply_review(
            starter,
            [ReviewDecision("d", "born", V.EDIT, entry={"strategy": "date_shift"})],
        )
    edited = apply_review(
        starter,
        [
            ReviewDecision(
                "d", "born", V.EDIT, entry={"strategy": "date_shift", "date_format": "%d-%m-%Y"}
            )
        ],
    )
    assert edited.config["tables"][0]["columns"][0]["provider_config"]["date_format"] == "%d-%m-%Y"
    # The static descriptor never builds a date_shift without a detected format.
    for detector in ("iso_date", "us_date", "eu_date"):
        assert detector_entry(detector, "born") is None
        assert detector_entry(detector, "born", date_format="  ") is None
