"""F07 E3b: several rules per nested column, run by the nested handler.

Rules are matched on the parsed cell before any write; two rules that touch the same position or
an ancestor and its descendant fail the column closed. Each rule draws on its own identity while
the evidence still names the real column.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._strategies._hash import HashStrategyHandler
from decoy_engine.execution._strategies._shuffle import ShuffleStrategyHandler
from decoy_engine.execution._strategies.nested import NestedStrategyHandler
from decoy_engine.generation.pool._cache import PoolCache
from decoy_engine.relationships._graph import RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceRegistry
from tests.unit.execution._nested_strategy_support import _seed

JOB = (0x0123456789).to_bytes(8, "big")


def _ctx(table: str = "t") -> StrategyContext:
    return StrategyContext(
        registry=None,  # type: ignore[arg-type]
        pool_cache=PoolCache(),
        relationship_graph=RelationshipGraph(edges=(), ordering=()),
        namespace_registry=NamespaceRegistry(bindings=()),
        job_seed=JOB,
        current_table=table,
    )


def _run(
    cells: list[Any], rules: list[dict], *, namespace: str | None = "events", ctx: Any = None
) -> tuple[pd.DataFrame, list, Any]:
    ctx = ctx or _ctx()
    seed = _seed({"rules": rules}, namespace)
    out, warnings = NestedStrategyHandler().run(
        pd.DataFrame({"payload": cells}), "payload", seed, ctx
    )
    return out, warnings, ctx


def _flat_hash(values: list[Any], namespace: str) -> list[Any]:
    seed = dataclasses.replace(_seed({}, namespace), strategy="hash", provider_config=())
    out, _ = HashStrategyHandler().run(pd.DataFrame({"c": values}), "c", seed, _ctx())
    return out["c"].tolist()


class TestTwoRulesOnePass:
    def test_each_rule_masks_its_own_leaf_under_its_own_namespace(self) -> None:
        cells = [json.dumps({"user": {"email": "a@x.com"}, "customer_id": "c-1"})]
        out, warnings, _ = _run(
            cells,
            [
                {"target": "$.user.email", "strategy": "redact"},
                {"target": "$.customer_id", "strategy": "hash", "namespace": "customer"},
            ],
        )
        parsed = json.loads(out["payload"].iloc[0])
        assert warnings == []
        assert parsed["user"]["email"] == "REDACTED"
        assert parsed["customer_id"] == _flat_hash(["c-1"], "customer")[0]
        assert parsed["customer_id"] != _flat_hash(["c-1"], "events")[0]

    def test_a_rule_without_namespace_uses_the_column_namespace(self) -> None:
        out, _, _ = _run([json.dumps({"id": "c-1"})], [{"target": "$.id", "strategy": "hash"}])
        assert json.loads(out["payload"].iloc[0])["id"] == _flat_hash(["c-1"], "events")[0]


class TestFakerRuleCarriesItsOwnProvider:
    def test_an_email_rule_and_a_hash_rule_in_one_pass(self) -> None:
        from decoy_engine.providers_v2 import get_default_registry

        cells = [json.dumps({"user": {"email": "a@x.com"}, "customer_id": "c-1"})]
        ctx = dataclasses.replace(_ctx(), registry=get_default_registry())
        seed = dataclasses.replace(
            _seed(
                {
                    "rules": [
                        {
                            "target": "$.user.email",
                            "strategy": "faker",
                            "strategy_config": {"provider": "person_email"},
                        },
                        {"target": "$.customer_id", "strategy": "hash", "namespace": "customer"},
                    ]
                },
                "events",
            ),
            deterministic=True,
            backend_type="faker",
            backend_version="v",
        )
        out, _ = NestedStrategyHandler().run(
            pd.DataFrame({"payload": cells}), "payload", seed, ctx
        )
        parsed = json.loads(out["payload"].iloc[0])
        email = parsed["user"]["email"]
        assert "@" in email and email != "a@x.com"
        assert parsed["customer_id"] == _flat_hash(["c-1"], "customer")[0]


class TestAFaultInOneRuleDoesNotHideAnother:
    HUGE = "1" + "0" * 4999

    @pytest.mark.parametrize("order", [("$.a", "$.b"), ("$.b", "$.a")])
    def test_an_out_of_range_number_fails_the_row_not_the_job(self, order: tuple[str, str]) -> None:
        cell = '{"a": ' + self.HUGE + ', "b": "x"}'
        out, _, ctx = _run([cell], [{"target": t, "strategy": "redact"} for t in order])
        assert [e.row_index for e in ctx.row_errors] == [0]
        assert out["payload"].iloc[0] == cell

    def test_a_rule_with_no_match_in_any_clean_cell_still_fails_closed(self) -> None:
        cell = '{"a": ' + self.HUGE + ', "b": "x"}'
        with pytest.raises(StrategyError) as exc:
            _run(
                [cell, json.dumps({"a": 1, "b": "y"})],
                [
                    {"target": "$.a", "strategy": "redact"},
                    {"target": "$.zzz", "strategy": "redact"},
                ],
            )
        assert exc.value.code == "nested_target_matched_nothing"


class TestOverlapFailsClosed:
    @pytest.mark.parametrize(
        ("targets", "cell"),
        [
            (("$.a", "$..a"), {"a": "x"}),
            (("$.a", "$.a.b"), {"a": {"b": "x"}}),
            (("$.a.b", "$.a"), {"a": {"b": "x"}}),
        ],
    )
    def test_equal_or_ancestor_positions_are_refused_and_nothing_is_written(
        self, targets: tuple[str, str], cell: dict
    ) -> None:
        text = json.dumps(cell)
        df = pd.DataFrame({"payload": [text]})
        rules = [{"target": t, "strategy": "redact"} for t in targets]
        with pytest.raises(StrategyError) as exc:
            NestedStrategyHandler().run(df, "payload", _seed({"rules": rules}, "events"), _ctx())
        assert exc.value.code == "nested_rules_overlap"
        assert "payload" in str(exc.value) and "0" in str(exc.value) and "1" in str(exc.value)
        assert df["payload"].iloc[0] == text
        assert exc.value.__cause__ is None

    def test_a_sibling_whose_name_starts_with_the_other_is_not_an_overlap(self) -> None:
        out, _, _ = _run(
            [json.dumps({"a": "x", "ab": "y"})],
            [
                {"target": "$.a", "strategy": "redact"},
                {"target": "$.ab", "strategy": "redact"},
            ],
        )
        assert json.loads(out["payload"].iloc[0]) == {"a": "REDACTED", "ab": "REDACTED"}

    def test_array_indexes_compare_as_positions_not_text(self) -> None:
        out, _, _ = _run(
            [json.dumps({"l": ["x", "y"]})],
            [
                {"target": "$.l[0]", "strategy": "redact"},
                {"target": "$.l[1]", "strategy": "redact"},
            ],
        )
        assert json.loads(out["payload"].iloc[0]) == {"l": ["REDACTED", "REDACTED"]}

    def test_a_key_with_a_dot_does_not_collide_with_a_nested_path(self) -> None:
        out, _, _ = _run(
            [json.dumps({"a.b": "x", "a": {"b": "y"}})],
            [
                {"target": "$['a.b']", "strategy": "redact"},
                {"target": "$.a.b", "strategy": "redact"},
            ],
        )
        assert json.loads(out["payload"].iloc[0]) == {"a.b": "REDACTED", "a": {"b": "REDACTED"}}


class TestZeroMatchPerRule:
    def test_a_rule_that_matches_nothing_fails_closed_even_if_another_matches(self) -> None:
        with pytest.raises(StrategyError) as exc:
            _run(
                [json.dumps({"a": "x"})],
                [
                    {"target": "$.a", "strategy": "redact"},
                    {"target": "$.zzz", "strategy": "redact"},
                ],
            )
        assert exc.value.code == "nested_target_matched_nothing"


class TestDrawIdentityPerRule:
    CELLS = [json.dumps({"a": i, "b": i}) for i in range(12)]

    def _shuffle_rules(self) -> list[dict]:
        return [
            {"target": "$.a", "strategy": "shuffle"},
            {"target": "$.b", "strategy": "shuffle"},
        ]

    @staticmethod
    def _flat_shuffle(values: list[int], column: str) -> list[Any]:
        seed = dataclasses.replace(_seed({}, "events"), strategy="shuffle", provider_config=())
        out, _ = ShuffleStrategyHandler().run(pd.DataFrame({column: values}), column, seed, _ctx())
        return out[column].tolist()

    def test_two_unkeyed_shuffle_rules_draw_independent_permutations(self) -> None:
        out, _, _ = _run(self.CELLS, self._shuffle_rules())
        a = [json.loads(c)["a"] for c in out["payload"]]
        b = [json.loads(c)["b"] for c in out["payload"]]
        assert sorted(a) == sorted(b) == list(range(12))
        assert a != b
        assert a == self._flat_shuffle(list(range(12)), "payload.rules[0]")
        assert b == self._flat_shuffle(list(range(12)), "payload.rules[1]")

    def test_the_single_form_still_draws_on_the_real_column(self) -> None:
        seed = _seed({"target": "$.a", "strategy": "shuffle"}, "events")
        out, _ = NestedStrategyHandler().run(
            pd.DataFrame({"payload": self.CELLS}), "payload", seed, _ctx()
        )
        got = [json.loads(c)["a"] for c in out["payload"]]
        assert got == self._flat_shuffle(list(range(12)), "payload")

    def test_the_draw_identity_is_restored_after_the_call(self) -> None:
        ctx = _ctx()
        _run(self.CELLS, self._shuffle_rules(), ctx=ctx)
        assert ctx.nested_draw_column == "" and ctx.nested_outer_column == ""


def _write_corpus(path: pathlib.Path, codes: list[str]) -> None:
    tbl = pa.table(
        {"code": pa.array(codes, type=pa.string())},
        metadata={
            b"decoy_corpus": path.stem.encode(),
            b"source": b"Test registry",
            b"source_version": b"1",
            b"effective_date": b"2026-01-01",
            b"license": b"Proprietary",
        },
    )
    pq.write_table(tbl, str(path))


def _code_rule(path: pathlib.Path, target: str = "$.code") -> dict:
    return {
        "target": target,
        "strategy": "code_set",
        "strategy_config": {
            "code_set": path.stem,
            "corpus_source": f"customer:{path}",
            "mode": "mask",
        },
    }


class TestCodeSetInRules:
    def test_evidence_names_the_real_column(self, tmp_path: pathlib.Path) -> None:
        corpus = tmp_path / "icd.parquet"
        _write_corpus(corpus, ["A1", "B2", "C3", "D4"])
        out, _, ctx = _run(
            [json.dumps({"name": "n", "code": "A1"})],
            [{"target": "$.name", "strategy": "redact"}, _code_rule(corpus)],
        )
        assert json.loads(out["payload"].iloc[0])["name"] == "REDACTED"
        assert set(ctx.code_set_corpora) == {("t", "payload")}
        assert ctx.code_set_corpora[("t", "payload")]["column"] == "payload"

    def test_preflight_reaches_the_second_rules_child(self, tmp_path: pathlib.Path) -> None:
        corpus = tmp_path / "icd.parquet"
        _write_corpus(corpus, ["A1", "B2"])
        seed = _seed({"rules": [{"target": "$.n", "strategy": "redact"}, _code_rule(corpus)]})
        NestedStrategyHandler().preflight(seed, _ctx())
        missing = tmp_path / "gone.parquet"
        bad = _seed({"rules": [{"target": "$.n", "strategy": "redact"}, _code_rule(missing)]})
        with pytest.raises(Exception) as exc:
            NestedStrategyHandler().preflight(bad, _ctx())
        assert getattr(exc.value, "code", "") == "code_set_corpus_path_not_found"
