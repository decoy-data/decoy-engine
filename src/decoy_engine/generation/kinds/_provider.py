"""The `provider` generate type: a column drawn from the masking provider registry.

The registry (`providers_v2.get_default_registry()`) is the only source of provider names,
adapters and capabilities, so a scalar provider that masking can use works here with no edit.
How a value is drawn follows from the provider's capability row, never from a name list:

- a poolable Faker or Mimesis provider builds one pool and samples it, as the faker pool bridge
  does, through the registry's pool seam;
- a `decoy_native` identifier draws each row through the adapter's keyed path with the row
  ordinal as the source value, the same pattern masking uses for a positional column;
- a non-poolable Faker provider asks the adapter for one seeded batch.

The registry declares no output type, and some providers return an int or a date. Every value
leaves this module as text, like a faker column's, so the plan-time typing can claim one type
for the whole `provider` kind and a formula that reads the column sees what the plan said.

Every failure inside a draw is caught at one site and re-raised after the `except` block closes,
so the new error has no cause and no context. Adapter and pool messages can quote a provider
name or a value, so they are never forwarded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from decoy_engine import reasons
from decoy_engine.generators.derivation import TABLE_KEY, GenDeriveContext, pool_seeds

if TYPE_CHECKING:
    from decoy_engine.providers_v2 import CapabilityMatrix, ProviderRegistry

__all__ = ["draw_path", "provider_generate"]

DrawPath = Literal["pool", "keyed", "batch"]

# A provider column is the registry-backed sibling of a faker column and draws from its family.
_VALUE_FAMILY = "faker"


def draw_path(caps: CapabilityMatrix) -> DrawPath | None:
    """How a provider's values are drawn, or None when generation has no path for its backend."""
    if caps.backend_type in ("faker", "mimesis") and caps.poolable:
        return "pool"
    if caps.backend_type == "decoy_native":
        return "keyed"
    if caps.backend_type == "faker":
        return "batch"
    return None


def provider_generate(
    col: dict[str, Any],
    n: int,
    gen_ctx: GenDeriveContext,
    registry: ProviderRegistry,
    locale: str,
) -> list[Any]:
    """``n`` values of the provider ``col`` names, in the effective ``locale``."""
    # Imported here: the provider and pool packages import `generation` while it initializes.
    from decoy_engine.generation.pool import GenerationError

    failed = False
    values: list[Any] = []
    try:
        values = _draw(col, n, gen_ctx, registry, locale)
    except Exception:
        # Any failure inside the provider, whatever its type, can quote a name or a value.
        failed = True
    if failed:
        raise GenerationError(
            code=reasons.runtime.GENERATION_PROVIDER_FAILED,
            message=(
                "A provider column could not be generated. "
                f"At table {col.get(TABLE_KEY)!r}, column {col.get('name')!r}."
            ),
        )
    return [v if v is None or isinstance(v, str) else str(v) for v in values]


def _draw(
    col: dict[str, Any],
    n: int,
    gen_ctx: GenDeriveContext,
    registry: ProviderRegistry,
    locale: str,
) -> list[Any]:
    from decoy_engine.generation.pool import (
        DEFAULT_POOL_SIZE,
        CardinalityMode,
        PoolBuilder,
        PoolSampler,
    )
    from decoy_engine.providers_v2 import ProviderError, ProviderSpec

    provider = str(col.get("provider"))
    caps = registry.get_capabilities(provider)
    # The plan check ran earlier; a registry override can change the row since.
    if locale not in caps.supported_locales:
        raise ProviderError(code=reasons.provider.UNSUPPORTED_LOCALE)
    path = draw_path(caps)
    adapter = registry.get_adapter(provider)
    namespace = f"gen-provider/{col.get(TABLE_KEY)}/{col.get('name')}"
    if path == "pool":
        build_seed, selection_seed = pool_seeds(gen_ctx)
        pool = PoolBuilder(registry).build(
            provider, size=DEFAULT_POOL_SIZE, job_seed=build_seed, locale=locale
        )
        sampled = PoolSampler().sample(
            pool, n, mode=CardinalityMode.REUSE, seed=selection_seed, deterministic=False
        )
        return list(sampled.tolist())
    if path == "keyed":
        return _draw_keyed(adapter, provider, n, gen_ctx, locale, namespace)
    if path == "batch":
        spec = ProviderSpec(
            locale=locale, deterministic=False, namespace=namespace, seed=pool_seeds(gen_ctx)[0]
        )
        return list(adapter.generate_batch(provider, spec=spec, count=n))
    raise ProviderError(code=reasons.provider.CAPABILITY_VIOLATION)


def _draw_keyed(
    adapter: Any, provider: str, n: int, gen_ctx: GenDeriveContext, locale: str, namespace: str
) -> list[Any]:
    """``n`` identifiers, each drawn through the keyed adapter path with its row ordinal."""
    from decoy_engine.providers_v2 import ProviderSpec

    value_seed = gen_ctx.family_bytes(_VALUE_FAMILY)
    try:
        spec = ProviderSpec(locale=locale, deterministic=True, namespace=namespace, seed=value_seed)
        # The identifier adapters take the row ordinal as the source value; the protocol types
        # it narrower than they accept.
        return [adapter.generate(provider, spec=spec, source_value=i) for i in range(n)]
    except BaseException:
        # The family key is a 32-byte derived key; drop it before the traceback keeps this frame.
        del value_seed
        raise
