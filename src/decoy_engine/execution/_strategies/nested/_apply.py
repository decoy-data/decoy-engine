"""Running the child of one nested rule, and the checks that guard writing its output back.

Split from the handler for its size cap. Pure value handling on cells the handler already read
and matched: no physical read or write.

Overlap between rules is decided on structured path tuples (field names and list indexes), never
on path text, so `$.a` is not a prefix of `$.ab` and a key that holds a dot does not collide with
a nested path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jsonpath_ng

from decoy_engine import reasons
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._row_errors import RowError
from decoy_engine.generation.pool._events import QualityWarning

__all__ = [
    "LEAF_COLUMN",
    "RuleOutput",
    "match_path",
    "refuse_corrupting_write",
    "refuse_rule_overlap",
    "remap_row_errors",
]

LEAF_COLUMN = "_nested_leaves"


def match_path(match: Any) -> tuple[Any, ...]:
    """The structured path of a jsonpath-ng match: field names and list indexes, root first."""
    return _segments(match.full_path)


def _segments(node: Any) -> tuple[Any, ...]:
    if isinstance(node, jsonpath_ng.Child):
        return _segments(node.left) + _segments(node.right)
    if isinstance(node, jsonpath_ng.Fields):
        return (node.fields[0] if len(node.fields) == 1 else tuple(node.fields),)
    if isinstance(node, jsonpath_ng.Index):
        return (node.indices[0] if len(node.indices) == 1 else tuple(node.indices),)
    if isinstance(node, (jsonpath_ng.Root, jsonpath_ng.This)):
        return ()
    return (str(node),)


def _related(a: tuple[Any, ...], b: tuple[Any, ...]) -> bool:
    """Equal, or one is an ancestor of the other."""
    shorter = min(len(a), len(b))
    return a[:shorter] == b[:shorter]


def refuse_rule_overlap(column: str, per_rule: list[tuple[int, list[tuple[Any, ...]]]]) -> None:
    """Fail the column closed when two rules reach the same position or an ancestor and descendant.

    `per_rule` holds `(rule index, match paths)` for the rules that matched one cell. Called
    before any write, so a refused cell is never half masked. The text names the column and the
    rule indexes only.
    """
    clash: tuple[int, int] | None = None
    for i, (first, first_paths) in enumerate(per_rule):
        for second, second_paths in per_rule[i + 1 :]:
            if clash is None and any(_related(a, b) for a in first_paths for b in second_paths):
                clash = (first, second)
    if clash is not None:
        raise StrategyError(
            code=reasons.runtime.NESTED_RULES_OVERLAP,
            strategy="nested",
            message=(
                f"rules {clash[0]} and {clash[1]} of nested column {column!r} select the same "
                "position or an ancestor and its descendant. Failing closed so one rule cannot "
                "overwrite the other."
            ),
        )


def _writeback_would_corrupt(full_path: Any, root: Any) -> bool:
    """True if `full_path.update(root, value)` would misplace the write.

    jsonpath-ng coerces an array selector (`[*]`, `[i]`, a slice) applied to a dict into a
    synthetic singleton list, so the match's `full_path` ends in an `Index` even though the real
    parent container is the dict. `.update()` then writes an integer key onto the dict instead of
    replacing the object, leaving the original value in place (a cleartext leak). The signature is
    a segment-vs-parent-type mismatch: an `Index` whose parent is not a list, or a `Fields` whose
    parent is not a dict. Reliable writes and root/`this` targets (handled by capturing the
    update return) are not flagged.
    """
    if isinstance(full_path, jsonpath_ng.Child):
        parent_path, last = full_path.left, full_path.right
        found = parent_path.find(root)
        if not found:
            return True  # parent unresolvable -> cannot verify the write, fail closed
        parent_val = found[0].value
    else:
        last = full_path
        parent_val = root
    if isinstance(last, jsonpath_ng.Index):
        return not isinstance(parent_val, list)
    if isinstance(last, jsonpath_ng.Fields):
        return not isinstance(parent_val, dict)
    return False


def refuse_corrupting_write(match: Any, root: Any, column: str) -> None:
    """Fail closed when the write for `match` would not replace the matched value (a leak)."""
    if _writeback_would_corrupt(match.full_path, root):
        raise StrategyError(
            code=reasons.runtime.NESTED_TARGET_UNWRITABLE_CONTAINER,
            strategy="nested",
            message=(
                f"nested target resolved to a match whose masked value "
                f"cannot be written back reliably for column {column!r} "
                f"(an array/index selector applied to a JSON object; "
                f"jsonpath-ng coerces it and the write would not replace "
                f"the object). Failing closed to avoid leaking the source "
                f"value. Use an object-appropriate target (e.g. `$.*` or a "
                f"field path) instead of an array selector on an object."
            ),
        )


@dataclass(frozen=True)
class RuleOutput:
    """What one rule's child produced: a value per collected leaf, and the cells it broke."""

    values: list[Any]
    non_finite_positions: set[int]
    warnings: list[QualityWarning]


def remap_row_errors(
    errors: list[RowError], first: int, leaf_outer_pos: list[int], column: str
) -> None:
    """Move the child's row errors from leaf positions to the real (outer row, outer column).

    Left unmapped, quarantine would drop the wrong outer row and leak the real one.
    """
    child_errs = errors[first:]
    if not child_errs:
        return
    del errors[first:]
    for e in child_errs:
        if not 0 <= e.row_index < len(leaf_outer_pos):
            # An unattributable error in a leak-prevention path fails the job rather than guess
            # an outer row and risk quarantining the wrong one.
            raise StrategyError(
                code=reasons.runtime.NESTED_CHILD_ROW_ERROR_UNMAPPABLE,
                strategy="nested",
                message=(
                    f"nested child recorded a RowError at leaf position "
                    f"{e.row_index}, outside the collected-leaf range "
                    f"[0, {len(leaf_outer_pos)}) for column {column!r}; it "
                    "cannot be mapped to an outer row. Failing closed."
                ),
            )
        errors.append(
            RowError(
                column=column,
                row_index=leaf_outer_pos[e.row_index],
                trigger=e.trigger,
                reason=e.reason,
            )
        )
