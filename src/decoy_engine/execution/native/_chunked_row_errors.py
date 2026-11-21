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

from decoy_engine.execution._row_errors import RowErrorRecord
from decoy_engine.execution.native._date_shift_ext import FORMAT_ERROR_REASON
from decoy_engine.transforms.bucket_perturb import FORMAT_ERROR_REASON as BUCKET_FORMAT_ERROR_REASON


def format_error_records(
    table: str,
    positions_by_column: Mapping[str, tuple[int, ...]],
    bucket_columns: Collection[str] = (),
) -> tuple[RowErrorRecord, ...]:
    """One `format_error` record per chunk-local position, columns in oracle work order.

    A column in `bucket_columns` carries bucket_perturb's reason text, the rest date_shift's."""
    return tuple(
        RowErrorRecord(
            table=table,
            column=column,
            row_index=position,
            trigger="format_error",
            reason=BUCKET_FORMAT_ERROR_REASON if column in bucket_columns else FORMAT_ERROR_REASON,
        )
        for column in sorted(positions_by_column)
        for position in positions_by_column[column]
    )
