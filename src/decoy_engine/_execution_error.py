"""`ExecutionError` and the lazy-source refusal, as a leaf.

`decoy_engine.execution._errors` re-exports both and stays the home every caller imports. The
class lives here so a lower layer (the lazy CSV source in `profile/`) can raise the refusal
without importing the execution package, which would load every execution module and cycle on
any future execution export that names a profile type.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NoReturn

from decoy_engine import reasons
from decoy_engine._error_base import DecoyError


class ExecutionError(DecoyError):
    """Execution-boundary / runner failure. Carries a machine-readable code."""

    def __init__(self, *, code: str, message: str = "", column: str | None = None) -> None:
        self.code = code
        self.message = message
        # Set by the source-read callbacks: the column a value-free error names.
        self.column = column
        super().__init__(f"[{code}] {message}" if message else f"[{code}]")


# Pickles, tracebacks and `__module__` consumers keep seeing the execution home, not this leaf.
ExecutionError.__module__ = "decoy_engine.execution._errors"


def lazy_source_changed(table: str, detail: str) -> ExecutionError:
    """The one constructor of the `lazy_source_changed` refusal, for every lazy source backend."""
    return ExecutionError(
        code=reasons.runtime.LAZY_SOURCE_CHANGED,
        message=f"the source of table {table!r} changed between routing and the read: {detail}.",
    )


def _unrepresentable_text(column: str | None, table: str | None, note: str = "") -> str:
    if column is None:
        where = f"a column of table {table!r}" if table is not None else "a column"
    else:
        where = f"table {table!r} column {column!r}" if table is not None else f"column {column!r}"
    return f"{where} holds a value pandas cannot represent.{note}"


# The `on_unrepresentable` callbacks of the source-read boundary (`arrow_to_frame`). Each names the
# table (when known) and the column, never a value, and raises `from None` so no pandas or Arrow
# text rides along. `column` is what the chunked diagnosis matches on.
def source_column_unrepresentable(table: str | None = None) -> Callable[[str | None], NoReturn]:
    """The callback for a read with no stricter code of its own (profile, fidelity, kernels)."""

    def raise_coded(column: str | None) -> NoReturn:
        raise ExecutionError(
            code=reasons.runtime.SOURCE_COLUMN_UNREPRESENTABLE,
            message=_unrepresentable_text(column, table),
            column=column,
        ) from None

    return raise_coded


def full_frame_unrepresentable(table: str | None, note: str) -> Callable[[str | None], NoReturn]:
    """The callback of the pandas execution routes, which convert every source column."""

    def raise_coded(column: str | None) -> NoReturn:
        raise ExecutionError(
            code=reasons.runtime.FULL_FRAME_VALUE_UNREPRESENTABLE,
            message=_unrepresentable_text(column, table, note),
            column=column,
        ) from None

    return raise_coded


def post_scan_not_inspectable(table: str) -> Callable[[str | None], NoReturn]:
    """The post-scan callback: the check fails closed on a column it cannot read."""

    def raise_coded(column: str | None) -> NoReturn:
        raise ExecutionError(
            code=reasons.runtime.POST_SCAN_COLUMN_NOT_INSPECTABLE,
            message=_unrepresentable_text(column, table),
            column=column,
        ) from None

    return raise_coded


def postmask_not_inspectable(column: str | None) -> NoReturn:
    """The post-mask callback; `column_facts` records the error on that column's tally."""
    raise ExecutionError(
        code=reasons.runtime.POSTMASK_COLUMN_NOT_INSPECTABLE,
        message=_unrepresentable_text(column, None),
        column=column,
    ) from None
