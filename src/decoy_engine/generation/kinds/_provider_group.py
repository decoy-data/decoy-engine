"""Composite groups on `type: provider` columns: one bundle per (provider, group), many columns.

A composite provider (`composite_person`, `composite_address`, ...) writes several coherent
columns from one latent per row. Here each output column is its own generate column, named by
`field`, and the columns that share a `(provider, group)` in one table take their values from
one bundle, so the email on a row is built from that row's names and the ZIP belongs to that
row's state.

The bundle is drawn once, by the first member that asks, and kept in a table-local cache. Its
seed comes from the group (provider, locale, determinism and the group label), never from a
member, so reordering or renaming members leaves every value alone. The factory table
(`COMPOSITES`) builds the generator, the same way masking's handler does.

Failures follow the scalar path: one fixed-text error, raised after the `except` block closes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from decoy_engine import reasons
from decoy_engine.generation.kinds._provider import as_text, guarded_values, keyed_draw
from decoy_engine.generators.derivation import TABLE_KEY, GenDeriveContext

if TYPE_CHECKING:
    from decoy_engine.providers_v2 import ProviderRegistry

__all__ = ["BundleCache", "group_of", "provider_group_values"]

# One table's finished bundles: (provider, group) -> output column -> its values, in row order.
BundleCache = dict[tuple[str, str], dict[str, list[Any]]]


def group_of(col: dict[str, Any]) -> tuple[str, str]:
    """The (provider, group) key of a composite column; the group is its `group`, else the provider."""
    provider = str(col["provider"])
    group = col.get("group")
    return provider, provider if group is None else str(group)


def provider_group_values(
    col: dict[str, Any],
    n: int,
    seed: int,
    derive_key: Any,
    registry: ProviderRegistry,
    locale: str,
    bundle_cache: BundleCache | None,
) -> list[Any]:
    """``n`` values of the composite field ``col`` names, from its group's bundle."""
    if bundle_cache is None:
        # Without the table's cache each member would draw its own bundle, and a fresh group
        # (an OS-entropy root per draw) would be silently incoherent.
        raise RuntimeError("a composite provider column needs its table's bundle cache")
    key = group_of(col)
    cached = bundle_cache.get(key)
    if cached is None:
        cached = guarded_values(
            col, lambda: _draw_bundle(col, key, n, seed, derive_key, registry, locale)
        )
        bundle_cache[key] = cached
    bundle = cached
    field = str(col["field"])
    return guarded_values(col, lambda: list(bundle[field]))


def _draw_bundle(
    col: dict[str, Any],
    key: tuple[str, str],
    n: int,
    seed: int,
    derive_key: Any,
    registry: ProviderRegistry,
    locale: str,
) -> dict[str, list[Any]]:
    import pandas as pd

    from decoy_engine.generation.composite import COMPOSITES
    from decoy_engine.providers_v2 import ProviderError, ProviderSpec

    provider, group = key
    caps = registry.get_capabilities(provider)
    # The plan check ran earlier; a registry override can change the row since.
    if locale not in caps.supported_locales:
        raise ProviderError(code=reasons.provider.UNSUPPORTED_LOCALE)
    # The group root carries what the members agree on and no `field`, so its fingerprint matches
    # no real column (a composite column without a field is refused at plan time). A fresh group
    # gets one OS-entropy root here, shared by every member within the run.
    group_cfg = {
        "name": f"<provider-group:{group}>",
        "type": "provider",
        "provider": provider,
        "locale": locale,
        "determinism": col.get("determinism", "stable"),
        TABLE_KEY: col.get(TABLE_KEY),
    }
    group_ctx = GenDeriveContext.for_column(
        derive_key=derive_key, column_config=group_cfg, fallback_seed=seed
    )
    namespace = f"gen-provider/{col.get(TABLE_KEY)}/{group}"
    generator = COMPOSITES[provider].factory(namespace, registry, {})
    # The row ordinal is the source value, as in the scalar identifier path.
    source = pd.Series(range(n), dtype="int64")

    def draw(spec: ProviderSpec) -> dict[str, list[Any]]:
        bundle = generator.generate_bundle(spec, n, source=source, deterministic=True)
        return {name: [as_text(v) for v in series] for name, series in bundle.items()}

    return keyed_draw(group_ctx, locale, namespace, draw)
