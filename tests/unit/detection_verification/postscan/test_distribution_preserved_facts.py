"""DI-T2: the facts a column keeps are derived from the one behaviour contract (row 31, DI-1a).

`preserved_facts` reads `distribution_behavior_for` and `NULLS_NOT_PRESERVED`; there is no second
per-strategy table. A generated property test runs every strategy that is not in
`NULLS_NOT_PRESERVED` over a null-bearing column and asserts that the output null positions equal
the source null positions, so a wrong entry in the set fails here, not in a customer's run.
"""

from __future__ import annotations

from typing import Any, get_args

import pyarrow as pa
import pytest

from decoy_engine.contracts import distribution_behavior as contract
from decoy_engine.contracts.column_shape import NO_SOURCES
from decoy_engine.contracts.distribution_behavior import (
    NULLS_NOT_PRESERVED,
    distribution_behavior_for,
)
from decoy_engine.execution import PandasExecutionAdapter
from decoy_engine.execution._strategies import SCALAR_HANDLERS
from decoy_engine.verification.postmask.distribution import FACTS, preserved_facts

ALL = frozenset(FACTS)
ROW = frozenset({"row_count"})
NULLS = frozenset({"row_count", "null_rate"})
CARDINALITY = frozenset({"row_count", "null_rate", "distinct_ratio"})


def test_the_fact_names_are_the_five_of_the_plan() -> None:
    assert FACTS == ("row_count", "null_rate", "distinct_ratio", "mean", "std")


def test_group_key_is_labelled_destroys_frequency() -> None:
    assert distribution_behavior_for("group_key") == "destroys_frequency"


def test_the_null_set_names_joint_mask_and_not_redact() -> None:
    assert "joint_mask" in NULLS_NOT_PRESERVED
    assert "redact" not in NULLS_NOT_PRESERVED
    assert isinstance(NULLS_NOT_PRESERVED, frozenset)


def test_every_name_in_the_null_set_is_a_known_strategy() -> None:
    assert set(SCALAR_HANDLERS) >= NULLS_NOT_PRESERVED


def test_every_strategy_has_a_behaviour_label_and_a_fact_set() -> None:
    for name in SCALAR_HANDLERS:
        assert distribution_behavior_for(name) is not None, name
        facts = preserved_facts(name)
        assert "row_count" in facts, name
        assert facts <= ALL, name


def test_every_behaviour_label_is_covered() -> None:
    labels = set(get_args(contract._DistributionBehavior))
    expected = {
        "preserves_all": ALL,
        "preserves_cardinality_only": CARDINALITY,
        "destroys_frequency": NULLS,
        "coarsens": NULLS,
        "collapses": NULLS,
        "varies_shape": NULLS,
        "mixed": NULLS,
        "inherits": NULLS,
    }
    assert set(expected) == labels
    seen: dict[str, frozenset[str]] = {}
    for name in sorted(set(SCALAR_HANDLERS) - NULLS_NOT_PRESERVED):
        label = distribution_behavior_for(name)
        assert label is not None
        seen.setdefault(label, preserved_facts(name))
        assert preserved_facts(name) == expected[label], name
    # Every label is reached by some null-keeping strategy, plain categorical included.
    assert set(seen) == labels


@pytest.mark.parametrize(
    ("strategy", "config", "facts"),
    [
        ("passthrough", None, ALL),
        ("shuffle", None, ALL),
        # Categorical maps values into a fixed category list: no cardinality or moments, whatever
        # its label says.
        ("categorical", (("weights", [0.5, 0.5]),), NULLS),
        ("categorical", (("from_profile", True),), NULLS),
        ("categorical", None, NULLS),
        ("categorical", (("weights", []),), NULLS),
        ("hash", None, CARDINALITY),
        ("fpe", None, CARDINALITY),
        ("tokenize", None, CARDINALITY),
        ("faker", None, NULLS),
        ("redact", None, NULLS),
        ("truncate", None, NULLS),
        ("nested", None, NULLS),
        ("joint_mask", None, ROW),
        ("geo_generalize", None, ROW),
        ("group_key", None, ROW),
        ("windowed_date", None, ROW),
        ("grouped_series", None, ROW),
        ("derived", None, ROW),
        ("derived_aggregate", None, ROW),
        ("formula", None, ROW),
    ],
)
def test_facts_per_strategy(strategy: str, config: Any, facts: frozenset[str]) -> None:
    assert preserved_facts(strategy, config) == facts


def test_categorical_is_checked_on_nulls_even_though_its_label_claims_more() -> None:
    weighted = (("weights", [0.5, 0.5]),)
    assert distribution_behavior_for("categorical", weighted) == "preserves_all"
    assert preserved_facts("categorical", weighted) == NULLS
    assert preserved_facts("categorical", (("from_profile", True),)) == NULLS


def test_a_conditional_column_keeps_only_the_row_count_and_a_safe_null_rate() -> None:
    assert preserved_facts("passthrough", conditional=True) == NULLS
    assert preserved_facts("hash", conditional=True) == NULLS
    assert preserved_facts("redact", conditional=True) == NULLS
    assert preserved_facts("joint_mask", conditional=True) == ROW
    assert preserved_facts("formula", conditional=True) == ROW


def test_an_unknown_strategy_is_checked_for_the_row_count_only() -> None:
    assert preserved_facts("not_a_strategy") == ROW
    assert preserved_facts(None) == ROW


# --- the generated null-position property test --------------------------------------------

_N = 20
_NULL_AT = {i for i in range(_N) if i % 5 == 2}


class _Vault:
    derivation_scope = b"fake-vault-scope-0123456789abcde"

    def __init__(self) -> None:
        self.map: dict[tuple[str, str], str] = {}

    def lookup_existing(self, namespace: str, plaintext: str) -> str | None:
        return self.map.get((namespace, plaintext))

    def put(self, namespace: str, plaintext: str, token: str) -> str:
        return self.map.setdefault((namespace, plaintext), token)


def _strs(fmt: str) -> list[str]:
    return [fmt.format(i=i) for i in range(_N)]


def _fixtures() -> dict[str, tuple[list[dict[str, Any]], list[Any]]]:
    """strategy -> (configured columns with the strategy under test as `val`, source values)."""

    def col(strategy: str, **extra: Any) -> list[dict[str, Any]]:
        return [{"name": "val", "strategy": strategy, **extra}]

    dates = [f"19{60 + (i % 40):02d}-03-{1 + (i % 28):02d}" for i in range(_N)]
    return {
        "passthrough": (col("passthrough"), _strs("keep-{i}")),
        "shuffle": (col("shuffle", namespace="sh", deterministic=True), _strs("s{i}")),
        "hash": (col("hash", namespace="h_ns"), _strs("u{i}@example.com")),
        "fpe": (
            col("fpe", namespace="f_ns", provider_config={"charset": "digits"}),
            _strs("{i:09d}"),
        ),
        "tokenize": (col("tokenize", namespace="t_ns"), _strs("4111{i:012d}")),
        "faker": (
            col(
                "faker",
                provider="person_first_name",
                deterministic=True,
                namespace="n_ns",
                cardinality_mode="reuse",
                provider_config={"pool_size": 20},
            ),
            _strs("name{i}"),
        ),
        "categorical": (
            col("categorical", namespace="c_ns", provider_config={"categories": ["a", "b", "c"]}),
            [["a", "b", "c"][i % 3] for i in range(_N)],
        ),
        "bucketize": (
            col("bucketize", provider_config={"width": 50}),
            [i * 13 % 997 for i in range(_N)],
        ),
        "truncate": (col("truncate", provider_config={"length": 3}), _strs("{i:05d}")),
        "code_set": (
            col("code_set", provider_config={"code_set": "icd10"}),
            [["A00", "B20", "C34", "E11"][i % 4] for i in range(_N)],
        ),
        "bucket_perturb": (
            col(
                "bucket_perturb",
                namespace="bp",
                provider_config={"bucket": "month", "date_format": "%Y-%m-%d"},
            ),
            [f"2021-{1 + (i % 12):02d}-15" for i in range(_N)],
        ),
        "top_code": (
            col("top_code", provider_config={"preset": "hipaa_age"}),
            [20 + i * 2 for i in range(_N)],
        ),
        "date_shift": (
            col(
                "date_shift",
                namespace="dob_ns",
                provider_config={"min_days": -30, "max_days": 30, "date_format": "%Y-%m-%d"},
            ),
            dates,
        ),
        "text_mask": (
            col("text_mask", namespace="tm_ns"),
            _strs("contact user{i}@example.com or 123-45-6789 today"),
        ),
        "text_redact": (
            col("text_redact"),
            _strs("contact user{i}@example.com or 123-45-6789 today"),
        ),
        "nested": (
            col(
                "nested",
                namespace="n_ns",
                provider_config={"target": "$.ssn", "strategy": "redact"},
            ),
            [f'{{"ssn": "12{i}-45-6789"}}' for i in range(_N)],
        ),
        "redact": (col("redact"), _strs("secret-{i}")),
    }


def _run(columns: list[dict[str, Any]], values: list[Any]) -> list[Any]:
    from decoy_engine.execution._chunked_profile import first_chunk_profile
    from decoy_engine.plan import compile_plan
    from decoy_engine.providers_v2 import get_default_registry
    from decoy_engine.relationships import RelationshipGraph, build_namespace_registry
    from tests.native._chunked_entry_support import key_provider

    source = pa.table(
        {"val": pa.array([None if i in _NULL_AT else v for i, v in enumerate(values)])}
    )
    config = {
        "global_settings": {"seed": 7, "unconfigured_column_policy": "warn"},
        "tables": [{"name": "t", "columns": columns}],
    }
    profile = first_chunk_profile(source, table="t", engine_version="di-1a")
    plan = compile_plan(
        config, profile, decoy_engine_version="di-1a", no_profile=True, sources=NO_SOURCES
    )
    result = PandasExecutionAdapter().run(
        plan,
        {"t": source},
        registry=get_default_registry(),
        relationship_graph=RelationshipGraph(edges=(), ordering=()),
        namespace_registry=build_namespace_registry(config, profile),
        key_provider=key_provider(),
        token_vault_writer=_Vault(),
    )
    return list(result.outputs["t"].column("val").to_pylist())


def test_every_null_keeping_strategy_has_a_fixture() -> None:
    assert set(_fixtures()) == set(SCALAR_HANDLERS) - NULLS_NOT_PRESERVED


@pytest.mark.parametrize("strategy", sorted(_fixtures()))
def test_a_strategy_outside_the_null_set_keeps_the_source_null_positions(strategy: str) -> None:
    columns, values = _fixtures()[strategy]
    out = _run(columns, values)
    assert len(out) == _N
    null_at = {i for i, v in enumerate(out) if v is None}
    assert null_at == _NULL_AT, strategy
