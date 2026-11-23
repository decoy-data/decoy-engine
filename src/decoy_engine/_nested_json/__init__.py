"""Nested JSON cell foundation: the rule model every nested-column reader shares.

Bottom layer, like `_canonical`: `plan`, `secret_providers` and `execution` all read a nested
column's child, so the one reader lives below them.
"""

from __future__ import annotations

from decoy_engine._nested_json._rules import NestedChild, nested_children
from decoy_engine._nested_json._target import TargetPath, TargetRefusal, parse_target

__all__ = ["NestedChild", "TargetPath", "TargetRefusal", "nested_children", "parse_target"]
