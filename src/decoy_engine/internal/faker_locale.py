"""Which locales a generate column runs in and which Faker opens for them.

One owner for the locale rule that validation, budgeting, per-row and pooled
generation and preflight all share. Split from ``faker_setup`` to keep that
module under its size cap; it depends on ``make_faker`` there, never the reverse.
"""

from __future__ import annotations

import locale as pylocale
from collections.abc import Callable
from typing import Any

from faker import Faker

from decoy_engine.internal.faker_setup import make_faker

# The locale a generate column uses when neither the column nor the run names one.
DEFAULT_GENERATE_LOCALE = "en_US"


def requested_locale(column_locale: Any, default_locale: Any = None) -> Any:
    """The locale a column asks for: its own, else the run default as given (never coerced to None)."""
    return column_locale or default_locale


def effective_locale(column_locale: Any, default_locale: Any = None) -> Any:
    """The locale a generate column runs in: its own, else the run default, else en_US."""
    return requested_locale(column_locale, default_locale) or DEFAULT_GENERATE_LOCALE


def locale_entries(locale: Any) -> tuple[str, ...]:
    """The locales Faker opens for ``locale``, in order, by Faker's resolved name (`it` is `it_IT`)."""
    entries = locale if isinstance(locale, list) else [locale]
    names = (str(e).replace("-", "_") if e else DEFAULT_GENERATE_LOCALE for e in entries)
    distinct = tuple(dict.fromkeys(names)) or (DEFAULT_GENERATE_LOCALE,)
    return tuple(pylocale.normalize(n).split(".")[0] for n in distinct)


def open_column_faker(
    column_locale: Any, default_locale: Any, seed: int, default_faker: Callable[[], Faker]
) -> tuple[Faker, int | None]:
    """The per-row Faker and its pre-seed: a column locale gives no pre-seed, else ``seed``."""
    requested = requested_locale(column_locale, default_locale)
    pre_seed = None if column_locale else seed
    return (make_faker(requested), pre_seed) if requested else (default_faker(), seed)


def faker_keys(locale: Any) -> tuple[str, ...]:
    """The keys Faker's own proxy keeps for ``locale``: ``-`` folded to ``_``, duplicates dropped.

    Unlike ``locale_entries`` this does not resolve names, so ``["it", "it_IT"]`` is two keys:
    Faker builds a multi-locale proxy for it even though both open the ``it_IT`` data.
    """
    entries = locale if isinstance(locale, list) else [locale]
    names = (str(e).replace("-", "_") if e else DEFAULT_GENERATE_LOCALE for e in entries)
    return tuple(dict.fromkeys(names)) or (DEFAULT_GENERATE_LOCALE,)


def is_single_factory(locale: Any) -> bool:
    """Whether Faker opens one factory (no multi-locale proxy) for ``locale``.

    Validation and generation both read this, so a column that validates against a single-locale
    Faker is never generated through a proxy that lacks its provider.
    """
    return len(faker_keys(locale)) == 1
