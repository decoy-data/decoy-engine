"""AT-13 (GEN-NONFAKER-DRAWS): the Faker draw arguments, defaults and method names have one owner.

`providers_v2/_faker_draw_contracts.py` holds one row per computed draw (uuid, bounded integer,
element choice). Consumers read it: the Faker adapter (method map and default kwargs), the
numeric-typing integer table and the computed-draw parser. This guard scans every module under
`src/decoy_engine`. A string literal that equals a computed provider name or its Faker method name
is a violation unless the file is on `NAME_OWNER_SITES` (a file that owns a name for a stated reason, not a debt list); the computed-draw
parser may not also hold an argument name. The live tables are checked against the rows. The two
adapter defaults that are not computed draws (`synthetic_member_id`, `synthetic_plan_id`) stay
adapter-owned.

Each rule is shown red against a seeded bypass: a local `random_int` default of 1 in the numeric
table, a local `random_choice -> random_elements` adapter mapping, a local `min` default in the
computed-draw parser and a bare `"uuid"` comparison in an execution module.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from decoy_engine.generation import _numeric_typing
from decoy_engine.providers_v2 import _faker_adapter, get_default_registry
from decoy_engine.providers_v2._faker_draw_contracts import (
    FAKER_DRAW_CONTRACTS,
    faker_draw_adapter_defaults,
    faker_draw_contract,
    faker_draw_method_view,
)

SRC = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"
ADAPTER = "providers_v2/_faker_adapter.py"
NUMERIC = "generation/_numeric_typing.py"
SPEC = "generation/pool/_computed_draw.py"
POSITIONAL = "execution/_strategies/_faker_positional.py"
# Adapter defaults that belong to no computed draw.
ADAPTER_OWNED_DEFAULTS = frozenset({"synthetic_member_id", "synthetic_plan_id"})

# Files that may hold a computed provider or Faker method name as a literal, and why. Every other
# module reads the contract (or the registry capability `draw`) instead.
NAME_OWNER_SITES: dict[str, str] = {
    "providers_v2/_faker_draw_contracts.py": "the contract rows themselves",
    "providers_v2/_real_registry.py": "declares each provider's capability row, keyed by name",
    "connectors/postgres_snapshot.py": "a SQL column type name, not a provider",
    "profiling/eval/corpus.py": "evaluation corpus labels for detected column kinds",
    "profiling/recommendations.py": "recommends a provider to the user by its public name",
    "generation/_bounds.py": "generate-side output width by Faker method name (GEN-NONFAKER-DRAWS S3)",
    "execution/_mem_estimate_schema.py": "memory estimate by Faker method name (width table)",
}


def _names() -> frozenset[str]:
    return frozenset(
        {c.provider for c in FAKER_DRAW_CONTRACTS} | {c.faker_type for c in FAKER_DRAW_CONTRACTS}
    )


def _args() -> frozenset[str]:
    return frozenset(a for c in FAKER_DRAW_CONTRACTS for a in c.arguments)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                found.add(id(body[0].value))
    return found


def violations(sources: dict[str, str]) -> list[str]:
    """Every string literal that restates a contract fact outside an allowed site."""
    names, args = _names(), _args()
    found: list[str] = []
    for rel, text in sources.items():
        tree = ast.parse(text)
        skip = _docstring_nodes(tree)
        forbidden = set() if rel in NAME_OWNER_SITES else set(names)
        if rel == SPEC:
            forbidden |= args
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in skip
                and node.value in forbidden
            ):
                found.append(f"{rel}:{node.lineno}: restates {node.value!r}")
    return found


def _real_sources() -> dict[str, str]:
    return {
        path.relative_to(SRC).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(SRC.rglob("*.py"))
    }


def test_the_consumers_hold_no_local_contract_literal() -> None:
    assert violations(_real_sources()) == []


def test_the_inventory_is_derived_from_the_contract_not_a_fixed_list() -> None:
    assert {c.provider for c in FAKER_DRAW_CONTRACTS} == {
        "uuid",
        "random_int_range",
        "random_choice",
    }
    assert {c.faker_type for c in FAKER_DRAW_CONTRACTS} == {"uuid4", "random_int", "random_element"}


class TestSeededBypassesAreSeen:
    def test_a_local_random_int_default_in_the_numeric_table(self) -> None:
        sources = _real_sources()
        needle = '"random_digit": ("", "", 0, 9),'
        assert needle in sources[NUMERIC]
        sources[NUMERIC] = sources[NUMERIC].replace(
            needle, needle + '\n    "random_int": ("min", "max", 0, 1),'
        )
        found = violations(sources)
        assert found and all(line.startswith(NUMERIC) for line in found)

    def test_a_local_random_choice_mapping_in_the_adapter(self) -> None:
        sources = _real_sources()
        needle = '"lorem_text": "text",'
        assert needle in sources[ADAPTER]
        sources[ADAPTER] = sources[ADAPTER].replace(
            needle, needle + '\n    "random_choice": "random_elements",'
        )
        found = violations(sources)
        assert any("random_choice" in line for line in found)

    def test_a_local_default_in_the_computed_draw_parser(self) -> None:
        sources = _real_sources()
        sources[SPEC] += '\n_LOCAL_DEFAULTS = {"min": 1}\n'
        assert any("'min'" in line for line in violations(sources))

    def test_a_bare_uuid_comparison_in_an_execution_module(self) -> None:
        sources = _real_sources()
        sources[POSITIONAL] += '\n_BAD = lambda spec: spec.provider == "uuid"\n'
        assert any(line.startswith(POSITIONAL) and "'uuid'" in line for line in violations(sources))

    def test_a_new_module_naming_a_provider_is_seen(self) -> None:
        sources = _real_sources()
        sources["execution/_new_module.py"] = 'KIND = "random_int_range"\n'
        assert violations(sources) == ["execution/_new_module.py:1: restates 'random_int_range'"]

    def test_every_allowed_site_exists_and_still_needs_its_entry(self) -> None:
        sources = _real_sources()
        for rel in NAME_OWNER_SITES:
            assert rel in sources
            names = _names()
            tree = ast.parse(sources[rel])
            assert any(isinstance(n, ast.Constant) and n.value in names for n in ast.walk(tree)), (
                f"{rel} no longer names a computed provider; drop it from NAME_OWNER_SITES"
            )

    def test_a_local_alias_default_in_the_adapter_defaults(self) -> None:
        sources = _real_sources()
        sources[ADAPTER] += '\n_FAKER_DEFAULT_KWARGS["random_choice"] = {"elements": ("z",)}\n'
        assert violations(sources)


class TestLiveTablesAgreeWithTheRows:
    def test_adapter_method_map_exposes_every_alias_through_the_contract(self) -> None:
        view = faker_draw_method_view()
        for contract in FAKER_DRAW_CONTRACTS:
            assert view[contract.provider] == contract.faker_type
            assert _faker_adapter._FAKER_METHOD_MAP[contract.provider] == contract.faker_type

    def test_adapter_defaults_are_the_contract_defaults_plus_the_two_owned_ones(self) -> None:
        live = _faker_adapter._FAKER_DEFAULT_KWARGS
        for alias, defaults in faker_draw_adapter_defaults().items():
            assert live[alias] == dict(defaults)
        computed = {c.provider for c in FAKER_DRAW_CONTRACTS}
        assert set(live) - computed == ADAPTER_OWNED_DEFAULTS

    def test_numeric_typing_bounds_are_the_contract_defaults(self) -> None:
        contract = faker_draw_contract("random_int")
        assert contract is not None
        lo_key, hi_key, _step = contract.arguments
        assert _numeric_typing._INT_PROVIDERS[contract.faker_type] == (
            lo_key,
            hi_key,
            contract.defaults[lo_key],
            contract.defaults[hi_key],
        )

    def test_both_lookup_keys_resolve_to_the_same_row(self) -> None:
        for contract in FAKER_DRAW_CONTRACTS:
            assert faker_draw_contract(contract.provider) is contract
            assert faker_draw_contract(contract.faker_type) is contract

    def test_registry_marks_exactly_the_contract_providers_as_computed(self) -> None:
        registry = get_default_registry()
        computed = {
            name
            for name in registry.known_providers()
            if registry.get_capabilities(name).draw == "computed"
        }
        assert computed == {c.provider for c in FAKER_DRAW_CONTRACTS}

    @pytest.mark.parametrize("contract", FAKER_DRAW_CONTRACTS, ids=lambda c: c.provider)
    def test_defaults_name_only_accepted_arguments(self, contract) -> None:
        assert set(contract.defaults) <= set(contract.arguments)
        assert set(contract.adapter_defaults) <= set(contract.defaults)
