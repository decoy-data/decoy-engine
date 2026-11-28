"""Config refusal text: one builder for the text and `path` of every loader refusal.

A sub-package because the engine root is at its fan-out cap, and because `safe_output`'s
`__init__` imports pyarrow, which `quality.dp_provenance` must not. See `_refusal` for the rule
and its established pattern (Pydantic's location-plus-type error report).
"""

from __future__ import annotations

from decoy_engine._config_text._read import passthrough, read_config, yaml_error_text
from decoy_engine._config_text._refusal import (
    ConfigPosition,
    Expected,
    Kind,
    Member,
    Name,
    Problem,
    QuotedName,
    Refusal,
    at_generate_column,
    config_position,
    config_refusal,
    config_root_position,
    kind_of,
    register_config_root_keys,
)

__all__ = [
    "ConfigPosition",
    "Expected",
    "Kind",
    "Member",
    "Name",
    "Problem",
    "QuotedName",
    "Refusal",
    "at_generate_column",
    "config_position",
    "config_refusal",
    "config_root_position",
    "kind_of",
    "passthrough",
    "read_config",
    "register_config_root_keys",
    "yaml_error_text",
]
