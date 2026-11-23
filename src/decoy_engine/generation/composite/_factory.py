"""The one table of composite generators: name, factory and output columns.

Masking and generation both build composites from this table, so a composite's name, its
canonical output columns and the way its generator is constructed are each stated once.
The registry binding, the compile-time wiring check, the `CompositeHandler` dispatch and the
column-access declarations all read it.

A factory takes `(coherent_namespace, registry, provider_config)` and returns the generator.
Most ignore `provider_config`; `composite_custom` reads its `bundle` there. The shape check for
that bundle stays in the masking handler, because this package must not raise execution errors.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from decoy_engine.generation.composite._address import CompositeAddress, composite_address
from decoy_engine.generation.composite._city_state_zip import (
    CompositeCityStateZip,
    composite_city_state_zip,
)
from decoy_engine.generation.composite._custom import composite_custom
from decoy_engine.generation.composite._name_email import CompositeNameEmail, composite_name_email
from decoy_engine.generation.composite._person import CompositePerson, composite_person
from decoy_engine.generation.composite._provider import CompositeProvider, composite_provider

if TYPE_CHECKING:
    from decoy_engine.generation.composite._generator import CompositeGenerator
    from decoy_engine.providers_v2 import ProviderRegistry

__all__ = ["COMPOSITES", "OPTIONAL_FIELDS_KEY", "CompositeDescriptor", "CompositeFactory"]

# The factory-config key that carries the optional slots a generation group asks for.
OPTIONAL_FIELDS_KEY = "optional_fields"

CompositeFactory = Callable[
    [str, "ProviderRegistry | None", Mapping[str, Any]], "CompositeGenerator"
]


@dataclass(frozen=True)
class CompositeDescriptor:
    """One composite: how to build it and which columns it writes.

    `output_columns` is the sorted canonical set the wiring check compares a coherent group
    against; it is empty for a composite whose outputs the config declares
    (`variable_output`). `optional_columns` are extra slots a caller may request; the wiring check
    never counts them, so masking is unchanged by their existence.
    """

    name: str
    factory: CompositeFactory
    output_columns: tuple[str, ...]
    optional_columns: tuple[str, ...] = ()
    variable_output: bool = False


def _name_email(
    namespace: str, registry: ProviderRegistry | None, _config: Mapping[str, Any]
) -> CompositeGenerator:
    return composite_name_email(coherent_namespace=namespace, registry=registry)


def _city_state_zip(
    namespace: str, _registry: ProviderRegistry | None, _config: Mapping[str, Any]
) -> CompositeGenerator:
    return composite_city_state_zip(coherent_namespace=namespace)


def _person(
    namespace: str, registry: ProviderRegistry | None, config: Mapping[str, Any]
) -> CompositeGenerator:
    # Generation hands the requested optional slots over as a frozenset. Masking passes the
    # column's user config, which cannot hold one, so a masking person never gets optional slots.
    requested = config.get(OPTIONAL_FIELDS_KEY)
    optional = requested if isinstance(requested, frozenset) else frozenset()
    return composite_person(
        coherent_namespace=namespace, registry=registry, optional_fields=optional
    )


def _address(
    namespace: str, registry: ProviderRegistry | None, _config: Mapping[str, Any]
) -> CompositeGenerator:
    return composite_address(coherent_namespace=namespace, registry=registry)


def _provider(
    namespace: str, registry: ProviderRegistry | None, _config: Mapping[str, Any]
) -> CompositeGenerator:
    return composite_provider(coherent_namespace=namespace, registry=registry)


def _custom(
    namespace: str, registry: ProviderRegistry | None, config: Mapping[str, Any]
) -> CompositeGenerator:
    return composite_custom(
        coherent_namespace=namespace, bundle=config.get("bundle") or [], registry=registry
    )


def _canonical(columns: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(columns))


COMPOSITES: Mapping[str, CompositeDescriptor] = {
    d.name: d
    for d in (
        CompositeDescriptor(
            "composite_name_email", _name_email, _canonical(CompositeNameEmail.output_columns)
        ),
        CompositeDescriptor(
            "composite_city_state_zip",
            _city_state_zip,
            _canonical(CompositeCityStateZip.output_columns),
        ),
        CompositeDescriptor("composite_custom", _custom, output_columns=(), variable_output=True),
        CompositeDescriptor(
            "composite_person",
            _person,
            _canonical(CompositePerson.output_columns),
            optional_columns=_canonical(CompositePerson.optional_columns),
        ),
        CompositeDescriptor(
            "composite_address", _address, _canonical(CompositeAddress.output_columns)
        ),
        CompositeDescriptor(
            "composite_provider", _provider, _canonical(CompositeProvider.output_columns)
        ),
    )
}
