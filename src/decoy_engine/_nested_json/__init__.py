"""Nested JSON cell foundation: the rule model every nested-column reader shares.

Bottom layer, like `_canonical`: `plan`, `secret_providers` and `execution` all read a nested
column's child, so the one reader lives below them.
"""

from __future__ import annotations

from decoy_engine._nested_json._paths import PathKeyBatch, path_key_batches, singular_path
from decoy_engine._nested_json._rules import (
    UNSET,
    NestedChild,
    PathRelation,
    effective_provider,
    nested_children,
    path_relations,
    reference_ends,
)

__all__ = [
    "UNSET",
    "NestedChild",
    "PathKeyBatch",
    "PathRelation",
    "effective_provider",
    "nested_children",
    "path_key_batches",
    "path_relations",
    "reference_ends",
    "singular_path",
]
