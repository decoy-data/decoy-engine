"""Worst-case resident bytes of one pooled Faker pool and of a run's Faker providers.

The preflight (`_streamed`) and the live ledger reservation (`_column_streams`) both call
`faker_pool_resident_bytes`. The model follows CPython's compact str layout (PEP 393: 1, 2 or 4
bytes per char, set by the widest char, plus a cached UTF-8 copy once Arrow converts it) and
Arrow's growable binary builder (buffers at most double while they grow).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from decoy_engine.config import generate_columns_of
from decoy_engine.internal.faker_setup import (
    DEFAULT_GENERATE_LOCALE,
    effective_locale,
    locale_entries,
)

# CPython str object header + list pointer (execution._mem_estimate_dtypes). The one definition;
# `_bounds` imports it from `pool`.
STR_OBJECT_OVERHEAD_BYTES = 57
_ARROW_OFFSET_BYTES = 4  # Arrow string offsets are int32
_POINTER_BYTES = 8
# Interpreter and Arrow builder minimums that do not scale with the pool (a 1-value Arrow string
# array still allocates whole 64-byte blocks).
_POOL_FIXED_BYTES = 80 * 1024
_MIB = 1024 * 1024
# Faker builds a locale's providers (name, address and other word lists) when anything first opens
# it, and keeps them for the run. Each locale has a retained bound (bytes kept once open) and a
# transient bound (its peak above that while its modules compile). Measured cold, with no cached
# bytecode, under tracemalloc for every locale Faker ships; each bound is the measure plus at least
# 25%, rounded up to a MiB. `test_provider_init_bound` re-measures every locale against this table.
_PROVIDER_INIT_BOUNDS: Mapping[str, tuple[int, int]] = MappingProxyType(
    {"it_IT": (12 * _MIB, 64 * _MIB), "de_AT": (2 * _MIB, 16 * _MIB)}
)
_PROVIDER_INIT_OTHER_BOUND = (2 * _MIB, 8 * _MIB)
# One more Faker instance of a locale already open (measured under 0.35 MB at peak).
_PROVIDER_INSTANCE_BYTES = 512 * 1024
# A str holding any non-ASCII char: the larger compact header and terminator, plus the
# terminator and allocator header of its cached UTF-8 copy, beyond STR_OBJECT_OVERHEAD_BYTES.
_STR_WIDE_EXTRA_BYTES = 48
# A value of `payload` UTF-8 bytes has at most `payload` chars, so its storage is at most
# 4 * payload (one astral char in ASCII text widens every char), and its UTF-8 copy adds `payload`.
_STR_STORAGE_PER_UTF8_BYTE = 4 + 1


@dataclass(frozen=True)
class PoolResidentParts:
    """The worst-case bytes of one pooled Faker pool, by the form that holds them.

    - `object_form`: the str objects (header, widest storage, cached UTF-8 copy) and the numpy
      object array's slot for each;
    - `arrow_peak`: the Arrow form while its builder grows (data, offset and validity buffers at
      most doubled); the finished array is those buffers;
    - `lists`: the build list and the `tolist()` list the conversion reads, alive together;
    - `fixed`: interpreter and Arrow builder minimums that do not scale with the pool.

    Faker's locale provider tables are not here: they are shared by every pool of a locale, so
    `provider_init_bytes` charges them once per run.
    """

    object_form: int
    arrow_peak: int
    lists: int
    fixed: int


def faker_pool_resident_parts(pool_size: int, payload: int) -> PoolResidentParts:
    """Each part of `faker_pool_resident_bytes`, so a test can hold each one against a measure."""
    per_str = (
        STR_OBJECT_OVERHEAD_BYTES + _STR_WIDE_EXTRA_BYTES + _STR_STORAGE_PER_UTF8_BYTE * payload
    )
    arrow_form = pool_size * (payload + _ARROW_OFFSET_BYTES) + pool_size // 8 + 1
    return PoolResidentParts(
        object_form=pool_size * per_str,
        arrow_peak=2 * arrow_form,
        lists=2 * pool_size * _POINTER_BYTES,
        fixed=_POOL_FIXED_BYTES,
    )


def faker_pool_resident_bytes(pool_size: int, payload: int) -> int:
    """Worst-case resident bytes of a pool of `pool_size` values of at most `payload` UTF-8 bytes.

    The pool is held in two forms (the frozen numpy object array and the Arrow array `pool_take`
    gathers from) and the conversion between them holds two lists. Each part is an upper bound,
    so they are summed with no slack, never taken as a maximum. The locale providers are charged
    separately, once per run, by `provider_init_bytes`.
    """
    parts = faker_pool_resident_parts(pool_size, payload)
    return parts.object_form + parts.arrow_peak + parts.lists + parts.fixed


def provider_init_bound(locale: str) -> tuple[int, int]:
    """The (retained, transient) bytes bound of opening ``locale`` cold."""
    return _PROVIDER_INIT_BOUNDS.get(locale, _PROVIDER_INIT_OTHER_BOUND)


def provider_init_bytes(locales: Collection[str], instances: int) -> int:
    """Worst-case Python bytes to open ``locales`` in any order, as ``instances`` Faker instances.

    Opening a locale after others peaks at most at their retained bytes plus its own solo peak,
    so the bound is every retained bound plus the largest transient one.
    """
    if not locales:
        return 0
    bounds = [provider_init_bound(locale) for locale in locales]
    retained = sum(r for r, _ in bounds)
    return retained + max(t for _, t in bounds) + max(instances, 0) * _PROVIDER_INSTANCE_BYTES


def _opens_faker(col: Mapping[str, Any]) -> bool:
    if col.get("type") == "faker":
        return True
    if col.get("type") != "provider":
        return False
    from decoy_engine.providers_v2 import get_default_registry

    try:
        caps = get_default_registry().get_capabilities(str(col.get("provider")))
    except Exception:
        return False  # an unknown provider is refused by the plan check that runs next
    return caps.backend_type == "faker"


def run_faker_footprint(
    config: Mapping[str, Any], instance_default_locale: str | None
) -> tuple[frozenset[str], int]:
    """Every locale any step of a run opens, and how many Faker instances, before any opens.

    Faker columns (pooled or per-row), Faker-backed provider columns and in-run validation open
    each column's locale; admission, bounds and the per-row path also open the default Faker.
    A malformed config yields nothing here: the plan check that follows refuses it by its code.
    """
    found: set[str] = set()
    instances = 0
    try:
        for table in config.get("tables") or []:
            for col in generate_columns_of(table):
                if _opens_faker(col):
                    entries = locale_entries(
                        effective_locale(col.get("locale"), instance_default_locale)
                    )
                    found |= set(entries)
                    instances += len(entries)
    except (AttributeError, TypeError, ValueError):
        return frozenset(), 0
    if not found:
        return frozenset(), 0
    return frozenset({*found, DEFAULT_GENERATE_LOCALE}), instances + 1


__all__ = [
    "STR_OBJECT_OVERHEAD_BYTES",
    "PoolResidentParts",
    "faker_pool_resident_bytes",
    "faker_pool_resident_parts",
    "provider_init_bound",
    "provider_init_bytes",
    "run_faker_footprint",
]
