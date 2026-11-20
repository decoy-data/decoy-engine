"""One locale fact per identifier: the declaration and the gate read the same constant.

An adapter's ``capability_matrix`` and its ``generate_random`` both read the module constant
that holds its supported locales, and ``require_locale`` enforces it. A declaration cannot then
promise a locale the generator refuses, or accept one the declaration omits.

``ENGINE_LOCALES`` is the set the engine accepts for a locale option. Faker's
``AVAILABLE_LOCALES`` already owns that set (``plan/checks/_generate_columns.py`` validates a
``locale`` against it), so identifiers whose output does not depend on locale reuse it.
"""

from __future__ import annotations

from collections.abc import Sequence

from faker.config import AVAILABLE_LOCALES

from decoy_engine import reasons
from decoy_engine.providers_v2._errors import ProviderError

__all__ = ["ENGINE_LOCALES", "require_locale"]

ENGINE_LOCALES: tuple[str, ...] = tuple(sorted(AVAILABLE_LOCALES))


def require_locale(label: str, locale: str, supported: Sequence[str]) -> None:
    """Refuse a locale the identifier does not declare. The text names the identifier only."""
    if locale not in supported:
        raise ProviderError(
            code=reasons.provider.UNSUPPORTED_LOCALE,
            message=f"{label} does not support the requested locale.",
        )
