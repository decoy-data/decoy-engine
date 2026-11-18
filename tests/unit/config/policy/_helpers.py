"""Shared builders for the policy unit tests: raw configs and a stub level 4 source."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from decoy_engine.config.policy import (
    ColumnDecision,
    ExpansionInputs,
    PolicyConfig,
    expand_policy,
)

STRATEGIES = frozenset(
    {"hash", "redact", "passthrough", "faker", "fpe", "tokenize", "truncate", "date_shift"}
)


def raw_config(tables: list[dict[str, Any]], relationships: list[dict[str, Any]] | None = None):
    return {
        "version": 2,
        "tables": tables,
        "relationships": relationships if relationships is not None else [],
    }


def table(name: str, *columns: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "columns": list(columns)}


def col(name: str, **keys: Any) -> dict[str, Any]:
    return {"name": name, **keys}


def inputs(
    policy: dict[str, Any] | None = None,
    level4: dict[str, ColumnDecision] | None = None,
) -> ExpansionInputs:
    stub = level4 or {}
    return ExpansionInputs(
        policy=PolicyConfig.model_validate(policy or {}),
        strategies=STRATEGIES,
        classification_default=stub.get,
    )


def expand(raw: dict[str, Any], policy: dict[str, Any] | None = None, level4=None):
    return expand_policy(raw, inputs(policy, level4))


def refusal(raw: dict[str, Any], policy: dict[str, Any] | None = None, level4=None):
    """The `ValidationError` expansion raises."""
    try:
        expand(raw, policy, level4)
    except ValidationError as exc:
        return exc
    raise AssertionError("expansion did not refuse")


def codes(exc: ValidationError) -> list[str]:
    return [err["type"] for err in exc.errors()]
