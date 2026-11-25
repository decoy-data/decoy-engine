"""Config refusal text: one builder for the text and `path` of every loader refusal.

A sub-package because the engine root is at its fan-out cap, and because `safe_output`'s
`__init__` imports pyarrow, which `quality.dp_provenance` must not. See `_refusal` for the rule
and its established pattern (Pydantic's location-plus-type error report).
"""

from __future__ import annotations

from decoy_engine._config_text._read import read_config
from decoy_engine._config_text._refusal import (
    ConfigPosition,
    Expected,
    Kind,
    Member,
    Name,
    Problem,
    Refusal,
    config_position,
    config_refusal,
    kind_of,
)

__all__ = [
    "ConfigPosition",
    "Expected",
    "Kind",
    "Member",
    "Name",
    "Problem",
    "Refusal",
    "config_position",
    "config_refusal",
    "kind_of",
    "read_config",
]
