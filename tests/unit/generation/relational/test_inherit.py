"""GEN-INHERIT E1: a child column copies its parent row's value through the child's foreign key.

`inherit` with `via` (an earlier `reference` column of the table) and `column` (a column of that
reference's parent table) gives each row the parent row's value, with the parent column's type.

AT-1 every registry names the type; AT-3 the shared lookup refusals; AT-4 every row agrees with
its parent and keeps its type; AT-5 chains; AT-6 the parent column is read, never a same-named
column elsewhere; AT-7 routes; AT-13 a conditional categorical over an inherited column; AT-14
numeric typing through the copy. AT-2 is in `tests/unit/config/test_generate_options.py` and
AT-12 in `tests/sentry/defects/test_reference_pool_choke_point.py`.
"""

from __future__ import annotations

import copy
import json
import math
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from pydantic import ValidationError

from decoy_engine import reasons, run_config_only_checks
from decoy_engine.config import _generate_relational as relational
from decoy_engine.config import reference_root
from decoy_engine.config._pipeline import PipelineConfig
from decoy_engine.generation._admission import classify_plan
from decoy_engine.generation._numeric_typing import numeric_plan
from decoy_engine.generation._plan_entry import generate_tables, generate_tables_streamed
from decoy_engine.generation._reproducibility import reproducibility_exclusions
from decoy_engine.generation.pinned import (
    PinnedModeError,
    PinnedPlan,
    compile_pinned_plan,
    execute_pinned,
)
from decoy_engine.generation.pool import GenerationError
from decoy_engine.plan import PlanCompileError
from tests.unit.generation.relational._support import REF, is_safe, plan_of
from tests.unit.generation.unique._gu_e2_support import cfg, ref, table

SENTINEL = "SENTINELVALUE"
CLAIMS = 1000
MEMBERS = 50
MEMBER_ID = {"name": "member_id", "type": "sequence", "start": 1}
STATE = {"name": "state", "type": "categorical", "categories": ["CA", "NY", "TX"]}
CLAIM_ID = {"name": "claim_id", "type": "sequence", "start": 1}


def inherit(name: str, column: str, via: str = "member_id", **extra: Any) -> dict[str, Any]:
    return {"name": name, "type": "inherit", "via": via, "column": column, **extra}


def member_fk(**extra: Any) -> dict[str, Any]:
    return ref("member_id", "members", "member_id", **extra)


def claims_config(
    *,
    member_cols: list[dict[str, Any]] | None = None,
    claim_cols: list[dict[str, Any]] | None = None,
    members: int = MEMBERS,
    claims: int = CLAIMS,
    seed: int = 4242,
) -> dict[str, Any]:
    """`members(member_id, state)` and `claims(claim_id, member_id, member_state)`."""
    parents = member_cols if member_cols is not None else [MEMBER_ID, STATE]
    kids = (
        claim_cols
        if claim_cols is not None
        else [
            CLAIM_ID,
            member_fk(),
            inherit("member_state", "state"),
        ]
    )
    return cfg([table("members", members, parents), table("claims", claims, kids)], seed)


def resident(config: dict[str, Any]) -> dict[str, pa.Table]:
    return generate_tables(plan_of(config))


def parent_rows(out: dict[str, pa.Table], parent: str, key: str) -> dict[Any, dict[str, Any]]:
    """The parent table's rows by key (test oracle only)."""
    return {row[key]: row for row in out[parent].to_pylist()}


def disagreements(
    out: dict[str, pa.Table], copies: dict[str, str], *, child: str = "claims"
) -> list[int]:
    """Rows of `child` whose copy is not its parent's value, or not null beside a null key."""
    members = parent_rows(out, "members", "member_id")
    bad: list[int] = []
    for i, row in enumerate(out[child].to_pylist()):
        fk = row["member_id"]
        for copy_name, source in copies.items():
            want = None if fk is None else members[fk][source]
            if row[copy_name] != want:
                bad.append(i)
    return bad


def _summary(namespace: str, code: str) -> str:
    return reasons.get(namespace, code).summary


# ---- AT-1: every registry names the type ------------------------------------------------------


def test_at1_every_registry_names_inherit() -> None:
    from decoy_engine.config import _generate_option_catalog as catalog
    from decoy_engine.config import _generate_options as opts
    from decoy_engine.config._tables import GENERATE_TYPES
    from decoy_engine.execution.native import _determinism_protocol as protocol
    from decoy_engine.execution.native._capabilities import _GEN_ONLY
    from decoy_engine.generation._admission import ADMISSION_MATRIX
    from decoy_engine.generation._numeric_typing import READERS
    from decoy_engine.generation._pinned_compile import PINNABLE_TYPES, REJECTED_TYPES

    assert "inherit" in GENERATE_TYPES
    assert "inherit" in opts.GENERATE_OPTIONS
    assert "inherit" in catalog.generate_option_catalog()
    assert ADMISSION_MATRIX["inherit"] == (
        False,
        "reads a parent row by FK; no cross-table row seam",
    )
    assert "inherit" in REJECTED_TYPES and "inherit" not in PINNABLE_TYPES
    assert REJECTED_TYPES["inherit"][0] == str(reasons.plan.PINNED_RELATIONAL_OPTION_UNSUPPORTED)
    assert READERS["inherit.via"].safe is True
    assert READERS["inherit.column"].safe is True
    assert protocol.GEN_KIND_TO_SITE["inherit"] == protocol.DETERMINISTIC_NO_DRAW
    assert "inherit" in _GEN_ONLY
    root = Path(__file__).resolve().parents[4]
    assert "`inherit`" in (root / "docs" / "capability-matrix.md").read_text()


# ---- AT-3: the lookup refusals are GEN-REL's ---------------------------------------------------


def _config_error(config: dict[str, Any]) -> dict[str, Any]:
    with pytest.raises(ValidationError) as exc:
        PipelineConfig.model_validate(config)
    (error,) = exc.value.errors()
    assert SENTINEL not in str(exc.value) and is_safe(exc.value)
    return error


@pytest.mark.parametrize(
    "key",
    [
        {"name": "member_id", "type": "categorical", "categories": [f"{SENTINEL}a", "b"]},
        {**MEMBER_ID, "null_probability": 0.1},
    ],
    ids=["categorical", "nullable-sequence"],
)
def test_at3_a_parent_key_that_is_not_unique_is_refused(key: dict[str, Any]) -> None:
    error = _config_error(claims_config(member_cols=[key, STATE]))
    code = "generate_parent_lookup_key_not_unique"
    assert error["type"] == code
    assert error["loc"] == ("tables", 1, "generate_columns", 2, "via")
    assert error["msg"] == _summary("config", code)
    assert error["input"] is None


def test_at3_a_via_that_is_not_a_reference_is_refused_as_not_unique() -> None:
    kids = [CLAIM_ID, {"name": "member_id", "type": "sequence", "start": 1}]
    kids.append(inherit("member_state", "state"))
    error = _config_error(claims_config(claim_cols=kids))
    assert error["type"] == "generate_parent_lookup_key_not_unique"
    assert error["loc"] == ("tables", 1, "generate_columns", 2, "via")


def test_at3_a_self_referencing_via_is_refused() -> None:
    kids = [CLAIM_ID, ref("parent_claim", "claims", "claim_id"), STATE]
    kids.append(inherit("parent_state", "state", via="parent_claim"))
    error = _config_error(claims_config(claim_cols=kids))
    code = "generate_parent_lookup_self_reference"
    assert error["type"] == code
    assert error["loc"] == ("tables", 1, "generate_columns", 3, "via")
    assert error["msg"] == _summary("config", code)


def _plan_refusal(config: dict[str, Any]) -> PlanCompileError:
    with pytest.raises(PlanCompileError) as exc:
        run_config_only_checks(config)
    assert is_safe(exc.value)
    return exc.value


def test_at3_a_column_missing_from_the_parent_is_the_shared_forward_reference() -> None:
    kids = [CLAIM_ID, member_fk(), inherit("member_state", "nope")]
    exc = _plan_refusal(claims_config(claim_cols=kids))
    assert exc.code == "generate_column_forward_reference"
    assert exc.path == "tables.claims.generate_columns.member_state.column"


def test_at3_a_foreign_key_with_no_parent_row_is_the_lookup_refusal() -> None:
    from decoy_engine.generation import synthesize

    kids = [CLAIM_ID, member_fk(), inherit("member_state", "state")]
    pools = {"members": pa.table({"member_id": [1, 2], "state": [f"{SENTINEL}1", "NY"]})}
    with pytest.raises(GenerationError) as exc:
        synthesize._generate_column(
            kids[2],
            2,
            7,
            None,
            pools,
            None,
            {"claim_id": [1, 2], "member_id": [1, 3]},
            table_name="claims",
            siblings=kids,
        )
    code = "parent_lookup_key_missing"
    assert exc.value.code == reasons.runtime.PARENT_LOOKUP_KEY_MISSING
    assert str(exc.value) == (
        f"[{code}] {_summary('runtime', code)} Table 'claims', column 'member_id'."
    )
    assert SENTINEL not in str(exc.value) and is_safe(exc.value)


# ---- AT-4: every row is its parent's value, with the parent's type -----------------------------

SCORE = {"name": "score", "type": "sequence", "start": 1, "null_probability": 0.3}
AMOUNT = {
    "name": "amount",
    "type": "categorical",
    "categories": [1.5, 2.25],
    "output_type": "decimal(2)",
}
JOINED = {
    "name": "joined",
    "type": "categorical",
    "categories": ["2020-01-02", "2021-03-04"],
    "output_type": "date",
}
NOTHING = {
    "name": "nothing",
    "type": "categorical",
    "categories": [7],
    "null_probability": 1.0,
    "output_type": "int",
}
COPIES = {
    "member_state": "state",
    "c_score": "score",
    "c_amount": "amount",
    "c_joined": "joined",
    "c_nothing": "nothing",
}


def _typed_config() -> dict[str, Any]:
    kids = [CLAIM_ID, member_fk(null_probability=0.1)]
    kids += [inherit(name, source) for name, source in COPIES.items()]
    return claims_config(
        member_cols=[MEMBER_ID, STATE, SCORE, AMOUNT, JOINED, NOTHING], claim_cols=kids
    )


def test_at4_every_claim_carries_its_members_value() -> None:
    out = resident(_typed_config())
    assert out["claims"].num_rows == CLAIMS and out["members"].num_rows == MEMBERS
    assert disagreements(out, COPIES) == []
    fks = out["claims"].column("member_id").to_pylist()
    # The fixture is not vacuous: null and non-null keys, every member state, present nulls.
    assert None in fks and len({fk for fk in fks if fk is not None}) > 40
    assert set(out["claims"].column("member_state").to_pylist()) == {"CA", "NY", "TX", None}
    scores = out["claims"].column("c_score").to_pylist()
    assert any(s is None and fk is not None for s, fk in zip(scores, fks, strict=True))
    assert any(isinstance(v, Decimal) for v in out["claims"].column("c_amount").to_pylist())


def test_at4_the_copy_has_the_parent_columns_type() -> None:
    out = resident(_typed_config())
    members, claims = out["members"].schema, out["claims"].schema
    for name, source in COPIES.items():
        assert claims.field(name).type == members.field(source).type, name
    assert claims.field("c_score").type == pa.int64()
    assert pa.types.is_decimal(claims.field("c_amount").type)
    assert claims.field("c_joined").type == pa.date32()
    # An all-null copy keeps its parent's type: inference would give `null`.
    assert claims.field("c_nothing").type == pa.int64()
    assert out["claims"].column("c_nothing").null_count == CLAIMS


def test_at4_a_null_foreign_key_gives_a_null_and_null_probability_applies_after() -> None:
    kids = [CLAIM_ID, member_fk(null_probability=0.5)]
    kids.append(inherit("member_state", "state", null_probability=0.5))
    out = resident(claims_config(claim_cols=kids))
    states = parent_rows(out, "members", "member_id")
    rows = out["claims"].to_pylist()
    assert all(r["member_state"] is None for r in rows if r["member_id"] is None)
    copied = [r for r in rows if r["member_state"] is not None]
    assert copied and all(r["member_state"] == states[r["member_id"]]["state"] for r in copied)
    # The column's own null mask nulls some rows whose key is present.
    assert any(r["member_id"] is not None and r["member_state"] is None for r in rows)


# ---- AT-5: a chain of copies agrees on every row ----------------------------------------------


def test_at5_a_chain_of_two_copies_agrees_with_the_member() -> None:
    lines = [
        {"name": "line_id", "type": "sequence", "start": 1},
        ref("claim_id", "claims", "claim_id"),
        inherit("member_state", "member_state", via="claim_id"),
    ]
    config = claims_config(claims=300)
    config["tables"].append(table("claim_lines", 900, lines))
    config["targets"]["claim_lines"] = {"type": "file", "format": "csv", "path": "o.csv"}
    out = resident(config)
    assert disagreements(out, {"member_state": "state"}) == []
    claims = parent_rows(out, "claims", "claim_id")
    members = parent_rows(out, "members", "member_id")
    for row in out["claim_lines"].to_pylist():
        claim = claims[row["claim_id"]]
        assert row["member_state"] == claim["member_state"]
        assert row["member_state"] == members[claim["member_id"]]["state"]


# ---- AT-6: the parent column, never a same-named column elsewhere ------------------------------

OTHER_STATE = {"name": "state", "type": "categorical", "categories": ["ZZ"]}
OWN_STATE = {"name": "state", "type": "categorical", "categories": ["QQ"]}


def _sibling_config() -> dict[str, Any]:
    """`other` and `claims` both hold a `state`; only `members.state` may be copied.

    `other` is drawn first and has a `member_id` too, so a run that looked the table up again by
    column name would read it.
    """
    config = claims_config(
        claim_cols=[CLAIM_ID, member_fk(), OWN_STATE, inherit("member_state", "state")]
    )
    config["tables"].insert(0, table("other", MEMBERS, [MEMBER_ID, OTHER_STATE]))
    config["targets"]["other"] = {"type": "file", "format": "csv", "path": "o.csv"}
    return config


def test_at6_the_copy_reads_the_parent_and_not_a_same_named_column() -> None:
    out = resident(_sibling_config())
    assert disagreements(out, {"member_state": "state"}) == []
    assert set(out["claims"].column("state").to_pylist()) == {"QQ"}
    assert not {"QQ", "ZZ"} & set(out["claims"].column("member_state").to_pylist())


def test_at6_the_reproducibility_report_follows_the_parent_edge() -> None:
    parent_fresh = _sibling_config()
    parent_fresh["tables"][1]["generate_columns"][1] = {**STATE, "determinism": "fresh"}
    assert ("claims", "member_state") in reproducibility_exclusions(parent_fresh)
    sibling_fresh = _sibling_config()
    sibling_fresh["tables"][2]["generate_columns"][2] = {**OWN_STATE, "determinism": "fresh"}
    excluded = reproducibility_exclusions(sibling_fresh)
    assert ("claims", "state") in excluded
    assert ("claims", "member_state") not in excluded


def test_at6_a_parent_column_the_child_does_not_declare_passes_the_strict_check() -> None:
    config = claims_config()
    run_config_only_checks(config)
    PipelineConfig.model_validate(config)


def test_at6_a_column_declared_only_in_the_child_is_refused() -> None:
    kids = [
        CLAIM_ID,
        member_fk(),
        {**OWN_STATE, "name": "region"},
        inherit("member_region", "region"),
    ]
    exc = _plan_refusal(claims_config(claim_cols=kids))
    assert exc.code == "generate_column_forward_reference"
    assert exc.path == "tables.claims.generate_columns.member_region.column"


def test_at6_a_via_declared_later_is_refused() -> None:
    kids = [CLAIM_ID, inherit("member_state", "state"), member_fk()]
    exc = _plan_refusal(claims_config(claim_cols=kids))
    assert exc.code == "generate_column_forward_reference"
    assert exc.path == "tables.claims.generate_columns.member_state.via"


def test_at6_the_edges_are_the_registry_descriptors() -> None:
    from decoy_engine.config import _generate_options as opts

    keys = opts.GENERATE_OPTIONS["inherit"].keys
    assert (keys["via"].ref_kind, keys["via"].ref_context_key) == ("column", None)
    assert (keys["column"].ref_kind, keys["column"].ref_context_key) == (
        "column_via_reference",
        "via",
    )
    assert keys["column"].ref_phase == "inline"
    claims = claims_config()["tables"][1]
    edges = {
        e.option: e
        for e in relational.iter_generate_input_refs(claims, claims["generate_columns"][2])
    }
    assert (edges["via"].source_table, edges["via"].source_column) == ("claims", "member_id")
    column = edges["column"]
    assert (column.source_table, column.source_column, column.source_key) == (
        "members",
        "state",
        "member_id",
    )


# ---- AT-7: routes ------------------------------------------------------------------------------


def test_at7_streaming_declines_the_column_and_the_values_stay_the_same(tmp_path: Path) -> None:
    from decoy_engine.execution import ParquetTransactionalSink

    config = claims_config()
    plan = plan_of(config)
    verdict = classify_plan(json.loads(plan.generation.config_json))
    declined = {(c.table, c.column): c.reason for c in verdict.declines}
    assert declined == {("claims", "member_state"): "family_declined:inherit"}
    result = generate_tables_streamed(
        plan, sink=ParquetTransactionalSink(tmp_path / "out"), budget_bytes=256 * 1024 * 1024
    )
    assert result.mode == "resident"
    want = generate_tables(plan_of(config))
    assert {n: t.to_pylist() for n, t in result.tables.items()} == {
        n: t.to_pylist() for n, t in want.items()
    }


PINNED_UNSUPPORTED = "pinned_relational_option_unsupported"


def test_at7_pinned_compile_refuses_inherit() -> None:
    with pytest.raises(PinnedModeError) as exc:
        compile_pinned_plan(copy.deepcopy(claims_config()), REF)
    assert exc.value.code == reasons.plan.PINNED_RELATIONAL_OPTION_UNSUPPORTED
    assert is_safe(exc.value)
    assert str(exc.value) == (
        f"[{PINNED_UNSUPPORTED}] {_summary('plan', PINNED_UNSUPPORTED)}"
        " Table 'claims', column 'member_state'."
    )


def _tampered_pinned_plan() -> PinnedPlan:
    """A compiled plan whose `member_state` column is turned into `inherit` after compile."""
    config = claims_config()
    config["tables"][1]["generate_columns"][2] = {**STATE, "name": "member_state"}
    stored = compile_pinned_plan(copy.deepcopy(config), REF).to_dict()
    claims = next(t for t in stored["tables"] if t["name"] == "claims")
    entry = next(c for c in claims["columns"] if c["name"] == "member_state")
    entry["config_json"] = json.dumps(inherit("member_state", "state"), sort_keys=True)
    return PinnedPlan.from_dict(stored)


def test_at7_pinned_execute_refuses_inherit_with_the_runtime_twin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decoy_engine.generation import synthesize

    def no_draw(*args: Any, **kw: Any) -> list[Any]:
        raise AssertionError("a column was drawn before the refusal")

    monkeypatch.setattr(synthesize, "_generate_column", no_draw)
    with pytest.raises(GenerationError) as exc:
        execute_pinned(_tampered_pinned_plan(), 7)
    assert exc.value.code == reasons.runtime.PINNED_RELATIONAL_OPTION_UNSUPPORTED
    assert is_safe(exc.value)
    assert str(exc.value) == (
        f"[{PINNED_UNSUPPORTED}] {_summary('runtime', PINNED_UNSUPPORTED)}"
        " Table 'claims', column 'member_state'."
    )


# ---- AT-13: a conditional categorical over an inherited column ---------------------------------

TIER_MIX = {"north": (0.8, 0.2), "south": (0.1, 0.9)}


def test_at13_a_tier_conditioned_on_an_inherited_region_follows_each_region() -> None:
    region = {"name": "region", "type": "categorical", "categories": ["north", "south"]}
    tier = {
        "name": "tier",
        "type": "categorical",
        "categories": ["gold", "basic"],
        "condition_on": "member_region",
        "by": {k: {"weights": list(v)} for k, v in TIER_MIX.items()},
    }
    kids = [CLAIM_ID, member_fk(), inherit("member_region", "region"), tier]
    rows = 50_000
    out = resident(claims_config(member_cols=[MEMBER_ID, region], claim_cols=kids, claims=rows))
    regions = parent_rows(out, "members", "member_id")
    counts: Counter[tuple[str, str]] = Counter()
    for row in out["claims"].to_pylist():
        assert row["member_region"] == regions[row["member_id"]]["region"]
        counts[(row["member_region"], row["tier"])] += 1
    for name, (gold, _) in TIER_MIX.items():
        n = counts[(name, "gold")] + counts[(name, "basic")]
        assert n > 1000, name
        error = math.sqrt(gold * (1 - gold) / n)
        assert abs(counts[(name, "gold")] / n - gold) <= 4 * error, name


# ---- AT-14: numeric typing through the copy ----------------------------------------------------


def _code_config(*extra: dict[str, Any]) -> dict[str, Any]:
    kids = [CLAIM_ID, member_fk(), inherit("member_code", "member_id"), *extra]
    return claims_config(claim_cols=kids)


# `group_key` reads the cell as text, so a reader of the copy keeps the parent key text.
TEXT_READER = {"name": "label", "type": "group_key", "group_by": "member_code"}


def _formula(expr: str) -> dict[str, Any]:
    return {"name": "label", "type": "formula", "formula": expr, "references": ["member_code"]}


def test_at14_a_child_text_reader_of_the_copy_keeps_the_parent_key_text() -> None:
    config = _code_config(TEXT_READER)
    assert ("members", "member_id") not in numeric_plan(config)
    out = resident(config)
    assert out["members"].schema.field("member_id").type == pa.string()
    assert out["claims"].schema.field("member_code").type == pa.string()
    for row in out["claims"].to_pylist():
        assert row["member_code"] == row["member_id"]
        assert row["label"] is not None


def test_at14_a_child_formula_using_the_copy_as_text_is_refused() -> None:
    # A formula binds the copy as the parent's number, so a text spelling is refused at compile.
    config = _code_config(_formula("'M-' + member_code"))
    with pytest.raises(PlanCompileError) as info:
        run_config_only_checks(config)
    assert info.value.code == str(reasons.plan.GENERATE_FORMULA_NUMBER_USED_AS_TEXT)
    assert info.value.path == "tables.claims.generate_columns.label.formula"


@pytest.mark.parametrize("expr", ["'M-' + str(member_code)", "f'M-{member_code}'"])
def test_at14_a_child_formula_reads_the_copy_as_a_number(expr: str) -> None:
    config = _code_config(_formula(expr))
    assert numeric_plan(config).get(("members", "member_id")) == pa.int64()
    out = resident(config)
    assert out["members"].schema.field("member_id").type == pa.int64()
    assert out["claims"].schema.field("member_code").type == pa.int64()
    for row in out["claims"].to_pylist():
        assert row["member_code"] == row["member_id"]
        assert row["label"] == f"M-{row['member_code']}"


def test_at14_without_a_text_reader_the_key_and_its_copy_are_int64() -> None:
    config = _code_config()
    assert numeric_plan(config).get(("members", "member_id")) == pa.int64()
    out = resident(config)
    assert out["members"].schema.field("member_id").type == pa.int64()
    assert out["claims"].schema.field("member_code").type == pa.int64()
    assert (
        out["claims"].column("member_code").to_pylist()
        == out["claims"].column("member_id").to_pylist()
    )


def _root_tables() -> dict[str, dict[str, Any]]:
    """`claims.member_state` copies `members.state`; `claims` and `other` hold a `state` too."""
    config = _sibling_config()
    return {t["name"]: t for t in config["tables"]}


def test_at14_the_copy_joins_the_parent_columns_root() -> None:
    tables = _root_tables()
    assert reference_root(tables, ("claims", "member_state")) == ("members", "state")
    assert reference_root(tables, ("claims", "state")) == ("claims", "state")


def test_at14_the_root_follows_a_chain_of_copies_and_references() -> None:
    config = _code_config()
    config["tables"].append(
        table(
            "lines",
            5,
            [ref("claim_id", "claims", "claim_id"), inherit("code", "member_code", via="claim_id")],
        )
    )
    tables = {t["name"]: t for t in config["tables"]}
    assert reference_root(tables, ("lines", "code")) == ("members", "member_id")


def test_at14_the_root_hop_reads_the_yielded_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    """The yielded `inherit.column` endpoint is followed, even where reading `via` would differ."""
    real = relational.iter_generate_input_refs

    def moved(table: Any, column: Any) -> tuple[Any, ...]:
        return tuple(
            replace(e, source_table="other", source_column="member_id")
            if column.get("type") == "inherit" and e.option == "column"
            else e
            for e in real(table, column)
        )

    monkeypatch.setattr(relational, "iter_generate_input_refs", moved)
    assert reference_root(_root_tables(), ("claims", "member_state")) == ("other", "member_id")


def test_at14_without_a_yielded_edge_the_key_is_returned_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = relational.iter_generate_input_refs

    def dropped(table: Any, column: Any) -> tuple[Any, ...]:
        return tuple(e for e in real(table, column) if e.option != "column")

    monkeypatch.setattr(relational, "iter_generate_input_refs", dropped)
    assert reference_root(_root_tables(), ("claims", "member_state")) == ("claims", "member_state")


def test_at14_a_malformed_copy_with_no_via_is_its_own_root() -> None:
    tables = _root_tables()
    del tables["claims"]["generate_columns"][3]["via"]
    assert reference_root(tables, ("claims", "member_state")) == ("claims", "member_state")
