"""Cell reading, leaf collection and fault recording for the nested strategy.

The handler reads each cell with the one strict reader in its lexeme mode, so a number it does not
select is written back as it was read. A cell fault becomes one ``RowError`` plus one
``QualityWarning`` (the row error has no code field), both value-free: the reason text is fixed and
the warning detail holds the row position only.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from decoy_engine import reasons
from decoy_engine._canonical import (
    MASK_CELL_BYTES,
    MASK_MAX_DEPTH,
    strict_json_read,
)
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._row_errors import RowError
from decoy_engine.generation.pool._events import QualityWarning

__all__ = ["find_matches", "leaf_frame", "read_cell", "record_fault", "written_leaf"]

# fault -> (trigger, fixed reason). `not_json` keeps its original text.
_FAULTS: dict[str, tuple[str, str]] = {
    "not_json": ("format_error", "cell is not valid JSON under nested masking"),
    "duplicate_key": ("format_error", "cell repeats an object key under nested masking"),
    "oversized": ("format_error", "cell is larger than the nested byte limit"),
    "too_deep": ("format_error", "cell is deeper than the nested depth limit"),
    "out_of_range": ("mask_error", "a selected number is too long to read as an integer"),
    "child_non_finite": (
        "mask_error",
        "a nested child returned a value that is not a finite number",
    ),
}


def find_matches(expr: Any, parsed: Any, column: str) -> list[Any]:
    """The JSONPath matches in one parsed cell, the single place `find` is called.

    jsonpath-ng treats an array selector on a scalar as a one-item list, but it calls `len()` on a
    `JsonNumber` (a lossy number kept as read). That `TypeError` is the same fault as an array
    selector on a plain scalar, which the writeback check refuses with the unwritable-container
    code, so it gets that code here. An index on an object raises `KeyError`: same fault, same
    code. No match is returned, so nothing can be written back.
    """
    failed = False
    matches: list[Any] = []
    try:
        matches = expr.find(parsed)
    except (TypeError, KeyError):
        failed = True
    if failed:
        raise StrategyError(
            code=reasons.runtime.NESTED_TARGET_UNWRITABLE_CONTAINER,
            strategy="nested",
            message=(
                f"nested target cannot be applied to a number in column {column!r}: an array "
                "selector on a scalar. Failing closed to avoid leaking the source value."
            ),
        )
    return matches


def read_cell(cell: Any) -> Any:
    """The parsed cell. A string is read under the mask bounds; an object is used as it is.

    Raises ``StrictJsonError`` with a closed token and no cell text.
    """
    if not isinstance(cell, str):
        return cell
    return strict_json_read(
        cell,
        max_bytes=MASK_CELL_BYTES,
        max_depth=MASK_MAX_DEPTH,
        non_finite="keep",
        keep_lexemes=True,
        max_int_digits=None,
    )


def record_fault(
    ctx: Any, warnings: list[QualityWarning], column: str, pos: int, fault: str
) -> None:
    """Fail the row closed: one row error and one warning, neither holding any cell text."""
    trigger, reason = _FAULTS[fault]
    ctx.row_errors.append(RowError(column=column, row_index=pos, trigger=trigger, reason=reason))
    warnings.append(_warning(fault, column, pos))


def _warning(fault: str, column: str, pos: int) -> QualityWarning:
    """The warning beside the row error; each branch names its registry symbol."""
    detail = {"row_pos": str(pos)}
    if fault == "duplicate_key":
        return QualityWarning(
            code=reasons.warning.NESTED_CELL_DUPLICATE_KEY,
            provider="nested",
            column=column,
            detail=detail,
        )
    if fault == "oversized":
        return QualityWarning(
            code=reasons.warning.NESTED_CELL_OVERSIZED,
            provider="nested",
            column=column,
            detail=detail,
        )
    if fault == "too_deep":
        return QualityWarning(
            code=reasons.warning.NESTED_CELL_TOO_DEEP,
            provider="nested",
            column=column,
            detail=detail,
        )
    if fault == "out_of_range":
        return QualityWarning(
            code=reasons.warning.NESTED_CELL_NUMBER_OUT_OF_RANGE,
            provider="nested",
            column=column,
            detail=detail,
        )
    if fault == "child_non_finite":
        return QualityWarning(
            code=reasons.warning.NESTED_CHILD_NON_FINITE,
            provider="nested",
            column=column,
            detail=detail,
        )
    return QualityWarning(
        code=reasons.warning.NESTED_CELL_JSON_PARSE_ERROR,
        provider="nested",
        column=column,
        detail=detail,
    )


def leaf_frame(name: str, leaves: list[Any]) -> pd.DataFrame:
    """The one-column frame the child runs on.

    A list of integers with a null is built as ``object`` so ``[1, None, 3]`` stays integers and a
    null; pandas inference would turn it into ``1.0, NaN, 3.0``. Every other list is inferred.
    """
    present = [v for v in leaves if v is not None]
    ints_with_null = len(present) < len(leaves) and all(
        isinstance(v, int) and not isinstance(v, bool) for v in present
    )
    if ints_with_null:
        return pd.DataFrame({name: pd.Series(leaves, dtype=object)})
    return pd.DataFrame({name: leaves})


def written_leaf(value: Any) -> tuple[Any, bool]:
    """A child output as JSON-writable, and whether it is finite.

    A pandas null (``None``, ``NaN``, ``pd.NA``) becomes ``None``, written as JSON ``null``. An
    infinite float is not written: the second item is ``False`` and the caller fails the row.
    """
    if isinstance(value, float) and math.isinf(value):
        return value, False
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return None, True
    return value, True
