"""Plan-time checks for `type: provider` generate columns.

The shared provider registry is the only source of provider names and capabilities, so a new
masking provider is accepted here with no edit. Every refusal is the fixed text of its reason
plus the table, column and option names; a submitted provider or locale never reaches it.
"""

from __future__ import annotations

from typing import Any

from decoy_engine import reasons
from decoy_engine.internal.faker_setup import requested_locale

__all__ = ["check_provider_column", "registry_provider_names"]


def registry_provider_names() -> frozenset[str]:
    from decoy_engine.providers_v2 import get_default_registry

    return get_default_registry().known_providers()


def check_provider_column(
    table: str, col: dict[str, Any], *, default_locale: str | None = None
) -> None:
    """Refuse a provider column the run could not draw.

    ``default_locale`` is the locale a column without ``locale`` will run in, when the caller
    knows it; ``None`` leaves such a column to the run-time check
    (``check_faker_default_locale``).
    """
    from decoy_engine.generation.composite import COMPOSITE_BACKEND
    from decoy_engine.generation.kinds import draw_path
    from decoy_engine.plan.checks._generate_columns import _refusal
    from decoy_engine.providers_v2 import get_default_registry

    registry = get_default_registry()
    name = col["name"]
    provider = col.get("provider")
    if not isinstance(provider, str) or not registry.has(provider):
        raise _refusal(reasons.plan.GENERATE_PROVIDER_UNKNOWN, table, name, "provider")
    caps = registry.get_capabilities(provider)
    if provider == "composite_custom" or (
        caps.backend_type != COMPOSITE_BACKEND and draw_path(caps) is None
    ):
        raise _refusal(reasons.plan.GENERATE_PROVIDER_UNSUPPORTED, table, name, "provider")
    if col.get("field") is not None:
        raise _refusal(reasons.plan.GENERATE_PROVIDER_FIELD_UNEXPECTED, table, name, "field")
    if col.get("group") is not None:
        raise _refusal(reasons.plan.GENERATE_PROVIDER_FIELD_UNEXPECTED, table, name, "group")
    if caps.backend_type == COMPOSITE_BACKEND:
        raise _refusal(reasons.plan.GENERATE_PROVIDER_FIELD_REQUIRED, table, name, "field")
    locale = requested_locale(col.get("locale"), default_locale)
    if locale is not None and locale not in caps.supported_locales:
        raise _refusal(reasons.plan.GENERATE_PROVIDER_LOCALE_UNSUPPORTED, table, name, "locale")
