"""Nested JSON cell foundation: the rule model every nested-column reader shares.

Bottom layer, like `_canonical`: `plan`, `secret_providers` and `execution` all read a nested
column's child, so the one reader lives below them.
"""

from __future__ import annotations

from decoy_engine._nested_json._rules import UNSET, NestedChild, effective_provider, nested_children

__all__ = ["UNSET", "NestedChild", "effective_provider", "nested_children"]
