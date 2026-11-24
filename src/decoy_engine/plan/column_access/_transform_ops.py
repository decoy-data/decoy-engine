"""What one transform op writes. The writer query and the `surface:transforms` declaration both
answer from this one classification, so they cannot classify an op differently."""

from __future__ import annotations

from collections.abc import Mapping

# The ops that move or drop rows and columns and write no cell. `derive` writes its target.
_NON_WRITING_OPS: frozenset[str] = frozenset({"filter", "sort", "limit", "dedupe", "drop_column"})


def transform_op_writes(op: object) -> frozenset[str] | None:
    """The columns `op` writes, or None when the op is malformed or not a known op. None makes
    the op an unknown writer for its own table."""
    if not isinstance(op, Mapping):
        return None
    kind = op.get("op")
    if not isinstance(kind, str):
        return None
    if kind in _NON_WRITING_OPS:
        return frozenset()
    if kind == "derive":
        column = op.get("column")
        return frozenset({column}) if isinstance(column, str) else None
    return None
