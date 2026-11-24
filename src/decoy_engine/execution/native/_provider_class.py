"""Provider execution classification (engine-efficiency program, Task 0.5).

`classify_provider` is the axis eligibility + fallback decisions read to know
HOW a provider can execute. It is distinct from Task 0.2's per-STRATEGY
`FallbackPolicy` (`execution/native/_requirements.py`): the "faker" strategy
as a whole is native-ready there (its output type is static and it is
row-local), but individual PROVIDERS bound to that strategy still differ in
whether a bounded value pool can be pre-built and selected per row, or
whether the provider only runs safely in Python. This module resolves that
finer axis, per provider, from the live `ProviderRegistry`.

Four classes, total over the registry:

- `pool_native`: a bounded value pool can be built once and selected
  natively per row. Faker-bound providers the registry marks
  `poolable=True`, and every `decoy_native` identifier provider. The
  identifier adapters themselves declare `poolable=False` (per S6 spec
  Section 3.1, `providers_v2/identifiers/__init__.py`), but that flag
  records a routing choice -- deterministic mode calls `derive_value`
  direct instead of going through the `PoolAdapter` wrapper -- not an
  unbounded output space. An SSN, EIN, NPI, and so on are all fixed-format,
  reproducible identifiers, exactly the "native identifier providers" this
  class is named for.
- `computed_native`: drawn from keyed bits with no pool at all (`draw="computed"`
  in the registry: `uuid`, `random_int_range`, `random_choice`). The draw is a pure
  function of the key, so it has a kernel path and never builds a value pool. Its
  argument facts live in `providers_v2._faker_draw_contracts`.
- `python_only`: bounded and reproducible, but currently Python-executed.
  Faker-bound providers the registry marks `poolable=False` (`lorem_text`,
  `address_full` --
  their own capability entry says no bounded pool can be pre-built for
  them) and every `composite` provider. Task 0.2's `<composite>`
  `StrategyCapabilities` row (`_capabilities.py`) declares
  `output_type_is_static=False`, the same signal `_fallback_policy` reads
  to keep a node off the native route; this module must not contradict
  that boundary by calling a composite provider `pool_native`.
- `reject_large`: an arbitrary or unknown callable that cannot be honestly
  made native. The fail-closed default for any `provider_id` NOT in the
  live registry -- including a V1-style custom Faker provider registered
  via `decoy_engine.providers.register_faker_provider`, which lives
  outside this registry entirely -- and, in depth, for any registered
  provider whose `backend_type` this module does not recognize yet.

Classification reads only the registry's own `CapabilityMatrix`
(`backend_type` + `poolable`); it never hardcodes a provider list or a
count, so it stays honest as bindings are added (see `_registry.py`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import pyarrow as pa

from decoy_engine import reasons
from decoy_engine.generation.pool import ComputedDrawSpec, draw_kwargs, parse_computed_draw
from decoy_engine.providers_v2 import ProviderRegistry, get_default_registry

ProviderClass = Literal["pool_native", "computed_native", "python_only", "reject_large"]

# decoy_native routes deterministic mode around the PoolAdapter wrapper by
# design (see the module docstring), so it classifies pool_native regardless
# of its own poolable=False flag.
_ALWAYS_POOL_NATIVE_BACKENDS = frozenset({"decoy_native"})

# faker / mimesis: the registry's own poolable flag is the authoritative
# per-provider signal for whether a bounded pool can be pre-built.
_POOLABLE_FLAG_BACKENDS = frozenset({"faker", "mimesis"})

# composite providers build a multi-column bundle pool in Python; Task 0.2
# already marks the <composite> node non-native (output_type_is_static=False).
_ALWAYS_PYTHON_ONLY_BACKENDS = frozenset({"composite"})


def classify_provider(
    provider_id: str,
    provider_config: Mapping[str, Any] | None,
    *,
    registry: ProviderRegistry | None = None,
) -> ProviderClass:
    """Classify how `provider_id` can execute.

    Total: every `provider_id` (registered, unregistered, or malformed)
    returns one of `pool_native`, `computed_native`, `python_only`, `reject_large`. Never
    raises.

    `provider_config` is accepted for interface parity with a possible
    future small-job threshold, where a job below some row-count bound
    could route a custom callable to `python_only` instead of rejecting
    it outright. Phase 0 ships no such override, so the argument is
    currently unread and an unrecognized `provider_id` always fails
    closed to `reject_large`.

    `registry` defaults to the live `get_default_registry()` singleton.
    Callers that need to classify against a pinned or overridden registry
    (per-pipeline backend pinning, tests) pass one explicitly.
    """
    del provider_config  # reserved; see docstring -- no small-job override yet.
    live_registry = registry if registry is not None else get_default_registry()
    if not live_registry.has(provider_id):
        return "reject_large"

    caps = live_registry.get_capabilities(provider_id)
    if caps.backend_type in _ALWAYS_POOL_NATIVE_BACKENDS:
        return "pool_native"
    if caps.backend_type in _POOLABLE_FLAG_BACKENDS:
        if caps.draw == "computed":
            return "computed_native"
        return "pool_native" if caps.poolable else "python_only"
    if caps.backend_type in _ALWAYS_PYTHON_ONLY_BACKENDS:
        return "python_only"
    # Fail-closed: a registered provider whose backend_type is not one of
    # the recognized families above is rejected rather than assumed native.
    return "reject_large"


@dataclass(frozen=True)
class FakerVariant:
    """How the live binding of a faker provider draws: from a `pool`, from a `computed` draw
    with its `spec`, or `unsupported` (a computed binding the engine has no descriptor for)."""

    kind: Literal["pool", "computed", "unsupported"]
    spec: ComputedDrawSpec | None = None


def resolve_faker_variant(
    provider: object,
    provider_config: Mapping[str, Any] | None,
    registry: ProviderRegistry | None = None,
) -> FakerVariant:
    """The one decision of how a faker column draws, read from the live registry binding.

    Every route calls it, so a rebound provider (`ProviderRegistry.override`) takes the same
    variant everywhere: a `draw="computed"` capability with a descriptor is `computed`, one
    without is `unsupported` (declined before any pool is prepared), and anything else is a
    `pool` provider whose own admission rules apply. A name the registry does not know stays
    `pool` and meets those rules."""
    live = registry if registry is not None else get_default_registry()
    if not isinstance(provider, str) or not live.has(provider):
        return FakerVariant("pool")
    if live.get_capabilities(provider).draw != "computed":
        return FakerVariant("pool")
    found = parse_computed_draw("mask", provider, draw_kwargs(provider_config))
    if isinstance(found, ComputedDrawSpec):
        return FakerVariant("computed", found)
    return FakerVariant("unsupported")


def computed_mask_spec(
    provider: object,
    provider_config: Mapping[str, Any] | None,
    registry: ProviderRegistry | None = None,
) -> ComputedDrawSpec | None:
    """The masking draw of a computed binding, or None for a pool or unsupported one.

    The one reader of a computed column's output type for every route: native admission, the
    out-of-core schema and the route declines all take it from the returned spec."""
    return resolve_faker_variant(provider, provider_config, registry).spec


def computed_output_decline(
    column: str,
    provider: object,
    provider_config: Mapping[str, Any] | None,
    registry: ProviderRegistry | None = None,
) -> str | None:
    """The route decline reason (E11/E13) for a computed draw whose output is not exact `string`.

    None for a pool provider and for an exact-string draw. The reason names the column and the
    provider, never an argument value."""
    spec = computed_mask_spec(provider, provider_config, registry)
    if spec is None or spec.output_type == pa.string():
        return None
    return f"{reasons.route.FAKER_COMPUTED_OUTPUT_TYPE_UNSUPPORTED}:{column}:{spec.provider}"


def draws_computed_string(provider: object, provider_config: Mapping[str, Any] | None) -> bool:
    """True when the stock binding of `provider` is a computed draw whose output is exact `string`.

    The degenerate-output pin reads it: such a column is typed `string` on every route, even
    when every cell is null or the table is empty."""
    spec = computed_mask_spec(provider, provider_config)
    return spec is not None and spec.output_type == pa.string()


__all__ = [
    "FakerVariant",
    "ProviderClass",
    "classify_provider",
    "computed_mask_spec",
    "computed_output_decline",
    "draws_computed_string",
    "resolve_faker_variant",
]
