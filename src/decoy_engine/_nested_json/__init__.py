"""Nested JSON cell foundation: the rule model every nested-column reader shares.

Bottom layer, like `_canonical`: `plan`, `secret_providers` and `execution` all read a nested
column's child, so the one reader lives below them.
"""

from __future__ import annotations

from decoy_engine._nested_json._paths import PathKeyBatch, path_key_batches, singular_path
from decoy_engine._nested_json._rules import (
    KEY_KIND,
    UNSET,
    NestedChild,
    PathRelation,
    bound_references,
    effective_provider,
    nested_children,
    path_relations,
    reference_ends,
    reference_key_kind,
)

__all__ = [
    "KEY_KIND",
    "UNSET",
    "NestedChild",
    "PathKeyBatch",
    "PathRelation",
    "bound_references",
    "effective_provider",
    "nested_children",
    "path_key_batches",
    "path_relations",
    "reference_ends",
    "reference_key_kind",
    "singular_path",
]
