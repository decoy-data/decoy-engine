"""Owner-approved pre-GA corrections to released reasons: a closed list, not a general bypass.

Each entry names one released identity, one manifest field, the value the release shipped and the
value it may now hold. `reason_manifest_policy` waives that field for that identity only when the
released side holds exactly the old value and the live side exactly the new one, so any other change
to a released reason still fails. The next release recaptures the pin with the new value, so the
pin check stops needing the entry; the v1 manifest fixture keeps the old value and still does.
Standard library only, like the policy module that reads it. Recorded in
docs/compatibility-contract.md ("Pre-GA correction (connector usage outcomes, 2026-11-17)").
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType


def _connector_rules(outcome: str, retry: str) -> tuple[dict[str, str], ...]:
    return tuple(
        {"phase": phase, "severity": "error", "outcome": outcome, "retry": retry}
        for phase in ("resolve", "unknown")
    )


# The released connector codes a user repairs in the config or the database (CLI exit 1, not 3).
_CONNECTOR_USAGE_CODES = (
    "ambiguous_name",
    "column_not_found",
    "duplicate_relation",
    "extension_unavailable",
    "extension_untrusted_location",
    "relation_not_found",
    "unsupported_column_type",
    "value_not_representable",
)

# (namespace, code) -> (field, released value, corrected value)
PRE_GA_CORRECTIONS: Mapping[tuple[str, str], tuple[str, object, object]] = MappingProxyType(
    {
        ("connector", code): (
            "rules",
            _connector_rules("execution", "unknown"),
            _connector_rules("configuration", "configuration_repair"),
        )
        for code in _CONNECTOR_USAGE_CODES
    }
)
