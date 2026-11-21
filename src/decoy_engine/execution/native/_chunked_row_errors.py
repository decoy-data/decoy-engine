"""Row errors for the native chunked route.

The oracle chunked leg drains each handler's `RowError`s into table-attributed
`RowErrorRecord`s in work-list order (`_runner.order_work`: topological, with a sorted
tie-break) and fails closed on the first chunk that has any. The native chunk loop visits
columns in source-schema order, so its collected errors are re-sorted here into the
oracle's order. A native-admitted table has no FK edges (`fk_relationship_not_native_route`)
and only scalar nodes, so the work-list order is the sorted column name.

`row_index` is relative to the chunk. The oracle chunked leg never adds the chunk's global
offset (`_row_errors.drain_row_errors`), so adding it here would make the legs disagree.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from decoy_engine.execution._row_errors import RowErrorRecord, drain_row_errors
from decoy_engine.execution.native._date_shift_ext import (
    BUCKET_PERTURB_OPERATOR_ID,
    DATE_SHIFT_OPERATOR_ID,
    format_error_row_errors,
)


def format_error_records(
    table: str,
    positions_by_column: Mapping[str, tuple[int, ...]],
    bucket_columns: Collection[str] = (),
) -> tuple[RowErrorRecord, ...]:
    """One `format_error` record per chunk-local position, columns in oracle work order.

    A column in `bucket_columns` carries bucket_perturb's reason text, the rest date_shift's."""
    return tuple(
        record
        for column in sorted(positions_by_column)
        for record in drain_row_errors(
            format_error_row_errors(
                column,
                positions_by_column[column],
                BUCKET_PERTURB_OPERATOR_ID if column in bucket_columns else DATE_SHIFT_OPERATOR_ID,
            ),
            table=table,
        )
    )
