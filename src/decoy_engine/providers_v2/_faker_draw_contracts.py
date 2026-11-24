"""The one source for the three computed Faker draws: uuid, bounded integer, element choice.

Each row names a registry alias, the Faker method behind it, the arguments it accepts and the
defaults Faker applies when they are absent. The adapter's method map, the adapter's default
kwargs, the numeric-typing integer table and the computed-draw parser all read these rows, so one
edit changes every reader (dev-rules cross-cutting-concerns: one descriptor per variant). The
guard is `tests/sentry/generation/test_faker_draw_contract_choke_point.py`.

Source pattern: RFC 9562 section 5.4 (uuid version 4); Faker's `random_int(min, max, step)` and
`random_element(elements)` signatures.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Literal

__all__ = [
    "FAKER_DRAW_CONTRACTS",
    "FAMILY_CHOICE",
    "FAMILY_INT",
    "FAMILY_UUID",
    "FakerDrawContract",
    "faker_draw_adapter_defaults",
    "faker_draw_contract",
    "faker_draw_method_view",
]

DrawFamily = Literal["uuid", "int", "choice"]
FAMILY_UUID: Final[DrawFamily] = "uuid"
FAMILY_INT: Final[DrawFamily] = "int"
FAMILY_CHOICE: Final[DrawFamily] = "choice"


@dataclass(frozen=True)
class FakerDrawContract:
    """One computed draw: alias, Faker method, accepted arguments and their defaults.

    `adapter_defaults` is the part of `defaults` the adapter injects into its Faker call. Faker
    supplies the integer defaults itself, so only the choice default is injected (that is what the
    adapter did before this table existed).
    """

    provider: str
    faker_type: str
    family: DrawFamily
    arguments: tuple[str, ...]
    defaults: Mapping[str, Any]
    adapter_defaults: Mapping[str, Any]


def _frozen(items: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(items))


FAKER_DRAW_CONTRACTS: Final[tuple[FakerDrawContract, ...]] = (
    FakerDrawContract(
        provider="uuid",
        faker_type="uuid4",
        family=FAMILY_UUID,
        arguments=(),
        defaults=_frozen({}),
        adapter_defaults=_frozen({}),
    ),
    FakerDrawContract(
        provider="random_int_range",
        faker_type="random_int",
        family=FAMILY_INT,
        arguments=("min", "max", "step"),
        defaults=_frozen({"min": 0, "max": 9999, "step": 1}),
        adapter_defaults=_frozen({}),
    ),
    FakerDrawContract(
        provider="random_choice",
        faker_type="random_element",
        family=FAMILY_CHOICE,
        arguments=("elements",),
        defaults=_frozen({"elements": ("a", "b", "c")}),
        adapter_defaults=_frozen({"elements": ("a", "b", "c")}),
    ),
)

_BY_NAME: Final[Mapping[str, FakerDrawContract]] = MappingProxyType(
    {
        **{c.provider: c for c in FAKER_DRAW_CONTRACTS},
        **{c.faker_type: c for c in FAKER_DRAW_CONTRACTS},
    }
)


def faker_draw_contract(name: str) -> FakerDrawContract | None:
    """The contract for a registry alias (`random_int_range`) or its Faker method (`random_int`)."""
    return _BY_NAME.get(name)


def faker_draw_method_view() -> Mapping[str, str]:
    """Registry alias to Faker method for the computed draws, the adapter's method-map entries."""
    return MappingProxyType({c.provider: c.faker_type for c in FAKER_DRAW_CONTRACTS})


def faker_draw_adapter_defaults() -> Mapping[str, Mapping[str, Any]]:
    """Registry alias to the kwargs the adapter injects, only for contracts that declare any."""
    return MappingProxyType(
        {c.provider: c.adapter_defaults for c in FAKER_DRAW_CONTRACTS if c.adapter_defaults}
    )
