"""Sentry: what a fixed composite generator returns is exactly what its declaration writes.

`CompositeHandler` refuses a bundle key outside the compiled operation's `writes` (which come
from `_COMPOSITE_OUTPUT_COLUMNS`), so a generator that ever returned a `coherent_with` member or a
renamed column would turn a working run into an `ExecutionError`. Each generator is run for real
and its bundle keys are compared with the one table the declaration reads. Guard only: the cells
pass on a correct build and go red when a generator or the table drifts.
"""

from __future__ import annotations

import pytest

from decoy_engine.execution._column_access import SURFACE_DECLARATIONS
from decoy_engine.generation.composite._address import CompositeAddress
from decoy_engine.generation.composite._city_state_zip import CompositeCityStateZip
from decoy_engine.generation.composite._name_email import CompositeNameEmail
from decoy_engine.generation.composite._person import CompositePerson
from decoy_engine.generation.composite._provider import CompositeProvider
from decoy_engine.generation.composite._validate import _COMPOSITE_OUTPUT_COLUMNS
from decoy_engine.providers_v2._adapter import ProviderSpec

_SEED = (0x0123456789).to_bytes(8, "big")
_GENERATORS = {
    CompositeNameEmail.composite_name: lambda: CompositeNameEmail(
        coherent_namespace="ns", pool_size=50
    ),
    CompositeCityStateZip.composite_name: lambda: CompositeCityStateZip(coherent_namespace="ns"),
    CompositePerson.composite_name: lambda: CompositePerson(coherent_namespace="ns", pool_size=50),
    CompositeAddress.composite_name: lambda: CompositeAddress(
        coherent_namespace="ns", pool_size=50
    ),
    CompositeProvider.composite_name: lambda: CompositeProvider(
        coherent_namespace="ns", pool_size=50
    ),
}


def test_the_sentry_covers_every_fixed_composite() -> None:
    assert set(_GENERATORS) == set(_COMPOSITE_OUTPUT_COLUMNS)


@pytest.mark.parametrize("provider", sorted(_GENERATORS))
def test_bundle_keys_equal_the_declared_output_columns(provider: str) -> None:
    spec = ProviderSpec(locale="en_US", deterministic=False, namespace=None, seed=_SEED, extra={})
    bundle = _GENERATORS[provider]().generate_bundle(spec, 3, source=None, deterministic=False)
    assert tuple(sorted(bundle)) == _COMPOSITE_OUTPUT_COLUMNS[provider]
    declared = SURFACE_DECLARATIONS[f"composite:{provider}"](
        {"name": "a", "provider": provider, "coherent_with": ["zz_member"]}
    )
    assert declared.writes == frozenset(bundle)
