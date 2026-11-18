"""Stability tier of every public engine name (compatibility contract 3.6).

A name is frozen, experimental or documented internal. The tier belongs to an object, not to a
name: one object exported from two places has one tier. This module holds the rules; the census
in `tests/sentry/release/_census.py` applies them to every export and fails on a name with no
tier, an object with two, or a marker that disagrees with the registry.

Order of the rules for one export: an explicit `TIER_EXCEPTIONS` row; then identity (an object in
`EXPERIMENTAL_OBJECTS`, or an object a frozen package already exports); then the package rule.
A public subpackage that contract 3.4 does not name is documented internal.
"""

from __future__ import annotations

from typing import Final

FROZEN: Final = "frozen"
EXPERIMENTAL: Final = "experimental"
INTERNAL: Final = "internal"
TIERS: Final = (FROZEN, EXPERIMENTAL, INTERNAL)

# A class or function docstring starts with this; a constant's module docstring does.
EXPERIMENTAL_MARKER: Final = "Experimental:"

# Modules and packages whose exports are frozen (contract 3.4 names each). Any other public
# package defaults to INTERNAL, unless one of its objects is also exported by a frozen one.
PACKAGE_TIERS: Final[dict[str, str]] = {
    "decoy_engine": FROZEN,
    "decoy_engine.sdk": FROZEN,
    "decoy_engine.detection": FROZEN,
    "decoy_engine.plan.checks": FROZEN,
    "decoy_engine.profile": FROZEN,
    "decoy_engine.profiling": FROZEN,
}

# `(module, name, tier)`: a name that must differ from its rule. Empty at the freeze.
TIER_EXCEPTIONS: Final[tuple[tuple[str, str, str], ...]] = ()

# Experimental objects by identity: `(defining module, qualified name)`. Every export of the
# object, at the root, in `sdk` or in `providers`, takes the tier. `ConfigError` and
# `ConnectorError` are `errors` objects that `sdk` re-exports, so they are not listed.
EXPERIMENTAL_OBJECTS: Final[tuple[tuple[str, str], ...]] = (
    ("decoy_engine.sdk", "CheckResult"),
    ("decoy_engine.sdk", "ConnectorConfig"),
    ("decoy_engine.sdk", "FileMeta"),
    ("decoy_engine.sdk", "FileSink"),
    ("decoy_engine.sdk", "FileSource"),
    ("decoy_engine.sdk", "PermanentError"),
    ("decoy_engine.sdk", "TransientError"),
    ("decoy_engine.sdk", "WriteResult"),
    ("decoy_engine.internal.faker_setup", "atomic_swap_db_providers"),
    ("decoy_engine.internal.faker_setup", "load_custom_providers"),
    ("decoy_engine.internal.faker_setup", "register_faker_list_provider"),
    ("decoy_engine.internal.faker_setup", "register_faker_provider"),
    ("decoy_engine.internal.faker_setup", "unregister_faker_provider"),
    ("decoy_engine.providers_v2._faker_adapter", "register_faker_provider_v2"),
)

# Experimental constants: `(defining module, names)`. A constant has no docstring, so the
# module docstring carries the marker and names each one.
EXPERIMENTAL_CONSTANTS: Final[tuple[str, tuple[str, ...]]] = (
    "decoy_engine.sdk",
    (
        "CAP_DRY_RUN",
        "CAP_INTROSPECTION",
        "CAP_MULTIPART",
        "CAP_RESUMABLE",
        "CAP_SIGNED_URL",
        "CAP_STREAMING",
        "SDK_VERSION",
    ),
)

# A public package that needs an optional extra: the one dependency whose absence the census
# tolerates. Its declared names are then classified from source. Any other import error fails.
OPTIONAL_EXTRAS: Final[dict[str, str]] = {"decoy_engine.providers_v2.mimesis": "mimesis"}


def package_tier(module: str) -> str:
    """The tier a name exported by `module` gets when no other rule applies."""
    return PACKAGE_TIERS.get(module, INTERNAL)
