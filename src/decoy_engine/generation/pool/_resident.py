"""Worst-case resident bytes of one pooled Faker pool, the one choke point for its reservation.

The preflight (`_streamed`) and the live ledger reservation (`_column_streams`) both call
`faker_pool_resident_bytes`. The model follows CPython's compact str layout (PEP 393: 1, 2 or 4
bytes per char, set by the widest char, plus a cached UTF-8 copy once Arrow converts it) and
Arrow's growable binary builder (buffers at most double while they grow).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# CPython str object header + list pointer (execution._mem_estimate_dtypes). The one definition;
# `_bounds` imports it from `pool`.
STR_OBJECT_OVERHEAD_BYTES = 57
_ARROW_OFFSET_BYTES = 4  # Arrow string offsets are int32
_POINTER_BYTES = 8
# Interpreter and Arrow builder minimums that do not scale with the pool (a 1-value Arrow string
# array still allocates whole 64-byte blocks).
_POOL_FIXED_BYTES = 80 * 1024
# Faker builds its locale providers (name, address and other word lists) when a worker first opens
# a locale, before the first value, and keeps them for the run. A fresh process measured 10.7 MB of
# Python allocations for `it_IT`, the heaviest of Faker's locales (the next is 1.5 MB), and under
# 1 MB for most. A run is charged once per distinct locale: 16 MiB for the first (the heaviest,
# rounded up) and 2 MiB for each further one (the second heaviest, rounded up), so any set of
# locales is covered whichever order they open in.
_PROVIDER_INIT_FIRST_BYTES = 16 * 1024 * 1024
_PROVIDER_INIT_NEXT_BYTES = 2 * 1024 * 1024
_DEFAULT_LOCALE = "en_US"
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


def pool_locales(requested_locale: Any) -> frozenset[str]:
    """The distinct locales a pooled column opens: one for a string, each entry of a list.

    An absent locale is Faker's default. `en-US` and `en_US` are one locale, as Faker reads them.
    """
    entries = requested_locale if isinstance(requested_locale, list) else [requested_locale]
    return frozenset(
        str(entry).replace("-", "_") if entry else _DEFAULT_LOCALE for entry in entries
    ) or frozenset({_DEFAULT_LOCALE})


def provider_init_bytes(locale_count: int) -> int:
    """Worst-case Python bytes to build the providers of `locale_count` distinct locales."""
    if locale_count <= 0:
        return 0
    return _PROVIDER_INIT_FIRST_BYTES + (locale_count - 1) * _PROVIDER_INIT_NEXT_BYTES


__all__ = [
    "STR_OBJECT_OVERHEAD_BYTES",
    "PoolResidentParts",
    "faker_pool_resident_bytes",
    "faker_pool_resident_parts",
    "pool_locales",
    "provider_init_bytes",
]
