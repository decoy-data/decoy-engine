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

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast

from decoy_engine import reasons
from decoy_engine.generators.derivation import (
    DEFAULT_GENERATE_LOCALE,
    TABLE_KEY,
    GenDeriveContext,
    pool_seeds,
)

if TYPE_CHECKING:
    from decoy_engine.generation.kinds._provider_group import BundleCache
    from decoy_engine.providers_v2 import CapabilityMatrix, ProviderRegistry

__all__ = ["as_text", "draw_path", "guarded_values", "provider_column_values", "provider_generate"]

DrawPath = Literal["pool", "keyed", "batch"]
_T = TypeVar("_T")

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


def provider_column_values(
    col: dict[str, Any],
    n: int,
    seed: int,
    derive_key: Any,
    instance_default_locale: str | None,
    bundle_cache: BundleCache | None,
    siblings: Sequence[Mapping[str, Any]] = (),
) -> list[Any]:
    """``n`` values for a ``provider`` generate column, in its locale or the instance default.

    A column with a ``field`` takes its values from its group's bundle (see
    `_provider_group`); every other column draws on its own seed.
    """
    from decoy_engine.generation.kinds._provider_group import provider_group_values
    from decoy_engine.providers_v2 import get_default_registry

    registry = get_default_registry()
    locale = str(col.get("locale") or instance_default_locale or DEFAULT_GENERATE_LOCALE)
    if col.get("field") is not None:
        return provider_group_values(
            col, n, seed, derive_key, registry, locale, bundle_cache, siblings
        )
    ctx = GenDeriveContext.for_column(derive_key=derive_key, column_config=col, fallback_seed=seed)
    return provider_generate(col, n, ctx, registry, locale)


def provider_generate(
    col: dict[str, Any],
    n: int,
    gen_ctx: GenDeriveContext,
    registry: ProviderRegistry,
    locale: str,
) -> list[Any]:
    """``n`` values of the provider ``col`` names, in the effective ``locale``."""
    return guarded_values(
        col, lambda: [as_text(v) for v in _draw(col, n, gen_ctx, registry, locale)]
    )


def guarded_values(col: dict[str, Any], produce: Callable[[], _T]) -> _T:
    """``produce()``, or one fixed-text error when it fails for any reason.

    The one translation site for provider and composite draws. The error is raised after the
    ``except`` block closes, so it has neither a cause nor a context.
    """
    # Imported here: the provider and pool packages import `generation` while it initializes.
    from decoy_engine.generation.pool import GenerationError

    failed = False
    result: _T | None = None
    try:
        result = produce()
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
    return cast(_T, result)


def as_text(value: Any) -> str | None:
    """The value as text; a ``__str__`` that raises is a draw failure, caught by the caller."""
    return value if value is None or isinstance(value, str) else str(value)


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
