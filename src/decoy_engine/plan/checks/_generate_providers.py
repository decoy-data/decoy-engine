"""Plan-time checks for `type: provider` generate columns.

The shared provider registry is the only source of provider names and capabilities, so a new
masking provider is accepted here with no edit. Every refusal is the fixed text of its reason
plus the table, column and option names; a submitted provider or locale never reaches it.
"""

from __future__ import annotations

from typing import Any

from decoy_engine import reasons

__all__ = ["check_provider_column", "check_provider_groups", "registry_provider_names"]


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
    from decoy_engine.generation.composite import COMPOSITES
    from decoy_engine.generation.kinds import draw_path
    from decoy_engine.plan.checks._generate_columns import _refusal
    from decoy_engine.providers_v2 import get_default_registry

    registry = get_default_registry()
    name = col["name"]
    provider = col.get("provider")
    if not isinstance(provider, str) or not registry.has(provider):
        raise _refusal(reasons.plan.GENERATE_PROVIDER_UNKNOWN, table, name, "provider")
    caps = registry.get_capabilities(provider)
    composite = COMPOSITES.get(provider)
    # A composite whose output columns the config declares has no field to name here.
    if (composite is not None and composite.variable_output) or (
        composite is None and draw_path(caps) is None
    ):
        raise _refusal(reasons.plan.GENERATE_PROVIDER_UNSUPPORTED, table, name, "provider")
    if composite is None:
        for key in ("field", "group"):
            if col.get(key) is not None:
                raise _refusal(reasons.plan.GENERATE_PROVIDER_FIELD_UNEXPECTED, table, name, key)
    elif col.get("field") is None:
        raise _refusal(reasons.plan.GENERATE_PROVIDER_FIELD_REQUIRED, table, name, "field")
    elif col["field"] not in composite.output_columns:
        raise _refusal(reasons.plan.GENERATE_PROVIDER_FIELD_UNKNOWN, table, name, "field")
    locale = col.get("locale") or default_locale
    if locale is not None and locale not in caps.supported_locales:
        raise _refusal(reasons.plan.GENERATE_PROVIDER_LOCALE_UNSUPPORTED, table, name, "locale")


def check_provider_groups(table: str, columns: list[dict[str, Any]]) -> None:
    """Refuse composite columns of one group that disagree, or that take one field twice.

    A group is the columns of one table with the same (provider, group). Members must declare
    the same `locale` (or all omit it, because compile cannot see the instance default) and the
    same `determinism`, so the group has one seed; each `field` appears once.
    """
    from decoy_engine.generation.kinds import group_of
    from decoy_engine.plan.checks._generate_columns import _refusal

    first: dict[tuple[str, str], dict[str, Any]] = {}
    taken: dict[tuple[str, str], set[str]] = {}
    for col in columns:
        if col.get("type") != "provider" or col.get("field") is None:
            continue
        key = (str(col["provider"]), group_of(col))
        head = first.setdefault(key, col)
        fields = taken.setdefault(key, set())
        if col.get("locale") != head.get("locale"):
            raise _refusal(
                reasons.plan.GENERATE_PROVIDER_GROUP_MISMATCH, table, col["name"], "locale"
            )
        if _determinism(col) != _determinism(head):
            raise _refusal(
                reasons.plan.GENERATE_PROVIDER_GROUP_MISMATCH, table, col["name"], "determinism"
            )
        if col["field"] in fields:
            raise _refusal(
                reasons.plan.GENERATE_PROVIDER_FIELD_DUPLICATE, table, col["name"], "field"
            )
        fields.add(col["field"])


def _determinism(col: dict[str, Any]) -> str:
    return str(col.get("determinism", "stable"))
