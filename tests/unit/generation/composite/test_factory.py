"""One descriptor table for every composite: the set guard and the factory contract.

The registry binding, the wiring check, the masking handler, the column-access declarations,
the leak check's literal and the coherence audit all name the same six composites. This test
holds them to one set, so a composite added to the table without the matching binding, checker
or literal fails here before a run does.
"""

from __future__ import annotations

import pyarrow as pa
import pytest

from decoy_engine.execution._column_access import _FIXED_COMPOSITES, column_access
from decoy_engine.generation.composite import COMPOSITES, CompositeDescriptor, _generator
from decoy_engine.generation.composite import _validate as wiring
from decoy_engine.providers_v2 import get_default_registry
from decoy_engine.validation.post._checks._composite_coherence import _audit
from decoy_engine.validators._leak_check import _COMPOSITE_PROVIDERS

REGISTRY = get_default_registry()
FIXED = sorted(n for n, d in COMPOSITES.items() if not d.variable_output)


def test_the_registry_the_wiring_check_and_every_name_list_are_one_set() -> None:
    bound = {
        p
        for p in REGISTRY.known_providers()
        if REGISTRY.get_capabilities(p).backend_type == "composite"
    }
    names = set(COMPOSITES)
    assert len(names) == 6
    assert bound == names
    assert set(_generator._COMPOSITE_NAMES) == names
    assert set(wiring._COMPOSITE_OUTPUT_COLUMNS) | set(wiring._VARIABLE_OUTPUT_COMPOSITES) == names
    assert set(wiring._COMPOSITE_OUTPUT_COLUMNS).isdisjoint(wiring._VARIABLE_OUTPUT_COMPOSITES)
    # The leak check is a leaf that imports only pyarrow, so it keeps a literal; this pins it.
    assert set(_COMPOSITE_PROVIDERS) == names
    assert set(_FIXED_COMPOSITES) == set(FIXED)


def test_the_variable_output_set_comes_from_the_descriptor() -> None:
    assert {"composite_custom"} == wiring._VARIABLE_OUTPUT_COMPOSITES
    assert {n for n, d in COMPOSITES.items() if d.variable_output} == {"composite_custom"}
    assert COMPOSITES["composite_custom"].output_columns == ()


@pytest.mark.parametrize("name", FIXED)
def test_every_fixed_composite_has_a_coherence_checker(name: str) -> None:
    columns = COMPOSITES[name].output_columns
    table = pa.table({c: pa.array(["x"], pa.string()) for c in columns})
    assert _audit(name, table) is not None


@pytest.mark.parametrize("name", FIXED)
def test_the_column_access_declaration_reads_the_descriptor(name: str) -> None:
    entry = {
        "name": COMPOSITES[name].output_columns[0],
        "strategy": "<composite>",
        "provider": name,
    }
    assert column_access(entry, REGISTRY).writes == frozenset(COMPOSITES[name].output_columns)


@pytest.mark.parametrize("name", sorted(COMPOSITES))
def test_the_factory_builds_the_named_generator_for_its_namespace(name: str) -> None:
    descriptor: CompositeDescriptor = COMPOSITES[name]
    config = {"bundle": [{"column": "a", "provider": "person_first_name"}]}
    generator = descriptor.factory("ns", REGISTRY, config)
    assert generator.composite_name == name
    assert generator.coherent_namespace == "ns"
    if not descriptor.variable_output:
        assert tuple(sorted(generator.output_columns)) == descriptor.output_columns
    # Only composite_person has optional slots; they never join the canonical set.
    expected = ("age", "sex") if name == "composite_person" else ()
    assert descriptor.optional_columns == expected
    assert set(descriptor.optional_columns).isdisjoint(descriptor.output_columns)
