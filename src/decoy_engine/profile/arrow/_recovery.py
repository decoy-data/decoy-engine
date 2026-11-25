"""Column-local recovery of a bounded Parquet profile that pandas cannot convert whole.

A valid Parquet file can hold a `time64[ns]` value with a sub-microsecond part or a `date32`
outside Python's year range. Arrow reads it; `to_pandas` does not. The bounded profile tries the
whole sample first (`profile._source`); only when that conversion fails does it call here, and
only for the flat schemas `_eligible` admits. Each field is converted alone. A temporal field
that fails is profiled from Arrow (`arrow_column_profile`) once its physical values explain the
failure; every other field goes through the ordinary pandas walk, so its profile is the one the
whole-table path would have given it.
"""

from __future__ import annotations

import dataclasses
import importlib
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from decoy_engine._field_names import repeated_names
from decoy_engine.profile.arrow._walk_arrow import arrow_column_profile, holds_date32

if TYPE_CHECKING:
    import pandas as pd

    from decoy_engine.profile._types import TableProfile

# Typed as Any: the compute kernels are registered at runtime, so stubs miss them.
pc: Any = importlib.import_module("pyarrow.compute")

_DAY_NS = 86_400_000_000_000  # a civil day in nanoseconds; datetime.time holds microseconds
_EPOCH_ORDINAL = date(1970, 1, 1).toordinal()
_MIN_DAY = date.min.toordinal() - _EPOCH_ORDINAL  # days since 1970-01-01 Python can hold
_MAX_DAY = date.max.toordinal() - _EPOCH_ORDINAL


def _is_temporal(t: pa.DataType) -> bool:
    return holds_date32(t) or (pa.types.is_time64(t) and t.unit == "ns")


def _eligible(schema: pa.Schema) -> bool:
    """The closed recovery schema: unique physical names, no pandas metadata key (even an
    empty or damaged one), and only date32, time64[ns], plain UTF-8 text and integers, with at
    least one temporal field. Dictionary and extension types are out whatever their storage."""
    if b"pandas" in (schema.metadata or {}):
        return False
    if repeated_names(schema.names):
        return False
    types = [field.type for field in schema]
    if not all(_is_temporal(t) or pa.types.is_string(t) or pa.types.is_integer(t) for t in types):
        return False
    return any(_is_temporal(t) for t in types)


def _explains_failure(column: pa.ChunkedArray) -> bool:
    """Whether the physical values show why pandas refused this temporal column: a time of day
    with a sub-microsecond part (all valid times inside the civil day), or a date outside the
    years Python can hold. Nulls are ignored; an all-null column explains nothing."""
    if holds_date32(column.type):
        days = column.cast(pa.int32())
        bounds = pc.min_max(days).as_py()
        low, high = bounds["min"], bounds["max"]
        return low is not None and (low < _MIN_DAY or high > _MAX_DAY)
    nanos = column.cast(pa.int64())
    bounds = pc.min_max(nanos).as_py()
    low, high = bounds["min"], bounds["max"]
    if low is None or low < 0 or high >= _DAY_NS:
        return False
    residue = pc.subtract(nanos, pc.multiply(pc.divide(nanos, 1000), 1000))
    return bool(pc.any(pc.not_equal(residue, 0)).as_py())


def recover_temporal_profile(
    table: pa.Table,
    *,
    table_name: str,
    total_row_count: int,
    declared_pk_cols: frozenset[str],
    fk_specs: dict[str, tuple[str, str]],
    source_format: str | None,
    walk_frame: Callable[[pd.DataFrame], TableProfile],
) -> TableProfile | None:
    """The `TableProfile` of `table`, or `None` when recovery does not apply.

    `table` is the bounded sample whose whole conversion failed. `walk_frame` is the ordinary
    pandas walk of one converted field, with the bounded profile's own arguments. `None` means
    the schema is outside `_eligible`, a field failed to convert for a reason the physical
    values do not explain, or no field failed alone; the caller then reports the original
    failure. Nothing is published until every field has a profile."""
    from decoy_engine.profile._types import TableProfile, column_key_fields

    if not _eligible(table.schema):
        return None
    sampled = total_row_count > table.num_rows
    columns = []
    recovered = False
    for name in table.schema.names:
        projection = table.select([name])
        try:
            frame = projection.to_pandas()
        except (ValueError, OverflowError):
            column = projection.column(0)
            if not _is_temporal(column.type) or not _explains_failure(column):
                return None
            profile = arrow_column_profile(name, column, source_format=source_format)
            keys = column_key_fields(
                name,
                row_count=total_row_count,
                distinct_count=profile.distinct_count,
                sampled=sampled,
                declared_pk_cols=declared_pk_cols,
                fk_specs=fk_specs,
            )
            columns.append(
                dataclasses.replace(
                    profile, row_count=total_row_count, sampled=sampled, **keys._asdict()
                )
            )
            recovered = True
            continue
        columns.extend(walk_frame(frame).columns)
    if not recovered:
        return None
    return TableProfile(name=table_name, row_count=total_row_count, columns=tuple(columns))
