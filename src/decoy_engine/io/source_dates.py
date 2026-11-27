"""The checked source read (DATE-RANGE-SENTINEL S5, section 4.4b).

Two refusals, both by name, before pandas or Python can see a value. A column that holds dates in
a type this read does not know (a list, struct, map, union, run-end-encoded, extension or nested
dictionary column) is refused by its type alone, whether the dates are inside the calendar or
not. A plain date or timestamp column, and a top-level dictionary of one, is read: a cell outside
calendar years 1 to 9999 is refused, and a dictionary entry no row uses is taken out.

`check_source_dates` is the one operation. Every reader, loader and entry that hands Arrow data on
to pandas, a strategy or a native kernel calls it (or `checked_batches`, `checked_loader`,
`check_resident_sources`, which wrap it) and carries on with what it returns.

This module is held to a closed vocabulary (tests/unit/io/test_source_dates_vocabulary.py): it
calls only the listed `pyarrow.compute` functions and never walks a container's storage, so a
layout it does not know is refused by type, not misread.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any, Protocol, TypeVar, overload

import pyarrow as pa
import pyarrow.compute as pc

from decoy_engine._arrow_types import (
    CALENDAR_FIRST_DAY_NUMBER,
    CALENDAR_LAST_DAY_NUMBER,
    is_date_leaf,
    type_kind,
    type_nodes,
)
from decoy_engine.io.bounded_reader import (
    SourceDateTypeUnsupportedError,
    SourceDateUnrepresentableError,
)

_pc: Any = pc  # pc.* funcs are dynamically generated; stubs miss them.
_Batch = TypeVar("_Batch", pa.Table, pa.RecordBatch)

_FIRST_DAY = CALENDAR_FIRST_DAY_NUMBER
_LAST_DAY = CALENDAR_LAST_DAY_NUMBER
_SECONDS_PER_DAY = 86_400
_TICKS_PER_SECOND = {"s": 1, "ms": 1_000, "us": 1_000_000, "ns": 1_000_000_000}
# Larger than any zone offset in the tz database, so a row this far inside the calendar edge
# needs no local conversion and a row this far outside it is out of the calendar in any zone.
_ZONE_MARGIN_DAYS = 2
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def _calendar_ticks(unit_ticks_per_day: int) -> tuple[int | None, int | None]:
    """Inclusive physical bounds of years 1 to 9999 in one unit, `None` where the unit's own
    storage range cannot pass that edge (so no comparison scalar is built for it)."""
    low = _FIRST_DAY * unit_ticks_per_day
    high = (_LAST_DAY + 1) * unit_ticks_per_day - 1
    return (low if low > _INT64_MIN else None, high if high < _INT64_MAX else None)


def _count_outside(ints: Any, low: int | None, high: int | None) -> Any:
    """Row mask of cells below `low` or above `high`; a `None` bound is not tested."""
    mask = None
    for bound, test in ((low, _pc.less), (high, _pc.greater)):
        if bound is not None:
            hit = test(ints, pa.scalar(bound, ints.type))
            mask = hit if mask is None else _pc.or_(mask, hit)
    return mask


def _holds_dates(arrow_type: pa.DataType) -> bool:
    """Whether a value of this type can contain a date or timestamp, at any depth."""
    return any(is_date_leaf(node) for node in type_nodes(arrow_type))


def _is_read(arrow_type: pa.DataType) -> bool:
    """A plain date or timestamp, or a top-level dictionary of one: the only shapes read."""
    if pa.types.is_dictionary(arrow_type):
        return is_date_leaf(arrow_type.value_type)
    return is_date_leaf(arrow_type)


def check_source_schema(schema: pa.Schema, *, table: str) -> None:
    """Refuse a schema that holds dates in a type this read does not read, naming the table, the
    column and the kind of the column's outermost type.

    It reads the type only, so it refuses whether the dates are inside the calendar or not, and
    for zero rows alike. No handler is open at the raise, so the error has no cause or context."""
    for name, arrow_type in zip(schema.names, schema.types, strict=True):
        if _holds_dates(arrow_type) and not _is_read(arrow_type):
            raise SourceDateTypeUnsupportedError(
                table=table, column=name, kind=type_kind(arrow_type)
            )


def _outside_mask(values: Any) -> Any:
    """Per-cell mask of the cells of a plain date or timestamp array outside calendar years 1 to
    9999 (a null cell is null in the mask, which sums and keeps as not outside), or `None` when no cell can be. A zoned cell is outside
    when its instant is, or its local calendar date is: the mask is the UTC test OR the same test
    over `local_timestamp` of the same cells, so the two line up cell for cell. The local wall
    clock wraps near the int64 extremes, but such a cell is already outside by the UTC test."""
    arrow_type = values.type
    zone = False
    if pa.types.is_date32(arrow_type):
        ticks_per_day, ints = 1, values.cast(pa.int32())
    elif pa.types.is_date64(arrow_type):
        ticks_per_day, ints = _SECONDS_PER_DAY * 1_000, values.cast(pa.int64())
    else:
        ticks_per_day = _TICKS_PER_SECOND[arrow_type.unit] * _SECONDS_PER_DAY
        ints, zone = values.cast(pa.int64()), arrow_type.tz is not None
    low, high = _calendar_ticks(ticks_per_day)
    extrema = _pc.min_max(ints).as_py() if (low is not None or high is not None) else None
    if not extrema or extrema["min"] is None:
        return None
    margin = _ZONE_MARGIN_DAYS * ticks_per_day if zone else 0
    if not (
        (low is not None and extrema["min"] < low + margin)
        or (high is not None and extrema["max"] > high - margin)
    ):
        return None
    utc_outside = _count_outside(ints, low, high)
    if not zone:
        return utc_outside
    local = _count_outside(_pc.local_timestamp(values).cast(pa.int64()), low, high)
    if local is None or utc_outside is None:
        return local if utc_outside is None else utc_outside
    return _pc.or_(utc_outside, local)


def _sum(mask: Any) -> int:
    return 0 if mask is None else int(_pc.sum(mask).as_py() or 0)


def _offending_rows(column: Any) -> int:
    """How many cells of one column are outside calendar years 1 to 9999. A dictionary column
    counts the rows that reference a bad entry, so an entry no row uses does not refuse the job;
    `_without_unused_bad_entries` removes it before pandas can convert the dictionary.

    Returns 0 for a type that holds no date. A type that holds a date and is neither a plain date
    leaf nor a top-level dictionary of one never reaches here (`check_source_schema` refuses it):
    if it does, a gate failed, and this raises instead of counting a container."""
    arrow_type = column.type
    if not _holds_dates(arrow_type):
        return 0
    if not _is_read(arrow_type):
        raise RuntimeError("source date count reached a type the schema gate must refuse")
    if pa.types.is_dictionary(arrow_type):
        return _offending_rows(column.cast(arrow_type.value_type))
    return _sum(_outside_mask(column))


def _repaired_dictionary(chunk: Any) -> Any:
    """One dictionary chunk with its out-of-calendar entries removed, the rest kept in order.

    The caller has counted the rows first, so a bad entry here is unused. A null entry is kept
    (`fill_null` on the keep mask). The remap is the running count of kept entries, in int64
    whatever the index type, gathered at the original indices and only then cast back."""
    entries = chunk.dictionary
    mask = _outside_mask(entries)
    if mask is None or not _sum(mask):
        return chunk
    keep = _pc.fill_null(_pc.invert(mask), True)
    remap = _pc.subtract(_pc.cumulative_sum(keep.cast(pa.int64())), pa.scalar(1, pa.int64()))
    indices = _pc.take(remap, chunk.indices).cast(chunk.type.index_type)
    return pa.DictionaryArray.from_arrays(indices, entries.filter(keep), ordered=chunk.type.ordered)


def _without_unused_bad_entries(column: Any) -> Any:
    """A dictionary-of-dates column with the out-of-calendar entries no row references taken out.

    Pandas converts a whole dictionary, so one unused bad entry would raise a value-bearing error
    for a column the job may read. The values rows reference, their order, the entry order, the
    index type and the ordered flag stay; a column with no bad entry comes back as it is."""
    arrow_type = column.type
    if not (pa.types.is_dictionary(arrow_type) and is_date_leaf(arrow_type.value_type)):
        return column
    chunks = column.chunks if isinstance(column, pa.ChunkedArray) else [column]
    repaired = [_repaired_dictionary(chunk) for chunk in chunks]
    if all(new is old for new, old in zip(repaired, chunks, strict=True)):
        return column
    return (
        pa.chunked_array(repaired, arrow_type)
        if isinstance(column, pa.ChunkedArray)
        else repaired[0]
    )


def check_source_dates(data: _Batch, *, table: str) -> _Batch:
    """Refuse a source batch or table holding a date column this read cannot read, or a date or
    timestamp outside calendar years 1 to 9999, and return the data to use from here on.

    Arrow stores dates as integers that reach years far past 9999, which pandas and Python cannot
    hold; this check sees the integers first, so a refusal never quotes a value. Only the table
    and column names, and the kind of an unsupported type, leave this function; the count of
    offending cells is on the exception object. Every caller must carry on with the returned
    data: it differs from the input only by dropping an unused out-of-calendar dictionary entry
    that pandas would otherwise try to convert.
    """
    check_source_schema(data.schema, table=table)
    columns = [data.column(i) for i in range(data.num_columns)]
    for name, column in zip(data.schema.names, columns, strict=True):
        count = _offending_rows(column)
        if count:
            # No handler is open here, so the error has no cause or context.
            raise SourceDateUnrepresentableError(table=table, column=name, count=count)
    cleaned = [_without_unused_bad_entries(column) for column in columns]
    if all(new is old for new, old in zip(cleaned, columns, strict=True)):
        return data
    if isinstance(data, pa.Table):
        return pa.Table.from_arrays(cleaned, schema=data.schema)
    return pa.RecordBatch.from_arrays(cleaned, schema=data.schema)


def checked_batches(
    batches: Iterable[_Batch], *, table: str, schema: pa.Schema | None = None
) -> Iterator[_Batch]:
    """Yield each batch (or table) only after `check_source_dates` passed it.

    A schema known ahead of iteration is gated here, synchronously, before the iterator is
    returned, so an unsupported column refuses at open, before any batch is requested."""
    if schema is not None:
        check_source_schema(schema, table=table)
    return _checked_each(batches, table)


def _checked_each(batches: Iterable[_Batch], table: str) -> Iterator[_Batch]:
    for batch in batches:
        yield check_source_dates(batch, table=table)


class _NamedSource(Protocol):
    """A lazy source: a frozen dataclass with a `table` field, which a refusal names."""

    table: str


def _bound(source: Any, name: str) -> Any:
    """A lazy source rebound to the `sources` mapping key, so a refusal names the table the
    caller gave. A frozen dataclass copy keeps its subclass; any other object passes through."""
    if (
        dataclasses.is_dataclass(source)
        and not isinstance(source, type)
        and any(field.name == "table" for field in dataclasses.fields(source))
    ):
        return dataclasses.replace(source, table=name)
    return source


@overload
def check_resident_sources(sources: Mapping[str, Any]) -> dict[str, Any]: ...


@overload
def check_resident_sources(sources: None) -> None: ...


def check_resident_sources(sources: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Check every resident table of a run's `sources` at its entry, before any transform,
    profile or route sees it, and return the sources to run on. A lazy source is rebound to its
    mapping key and checked batch by batch as it is read."""
    if sources is None:
        return None
    return {
        name: (
            check_source_dates(sources[name], table=name)
            if isinstance(sources[name], pa.Table)
            else _bound(sources[name], name)
        )
        for name in sources
    }


@overload
def checked_loader(loader: Callable[[str], pa.Table]) -> Callable[[str], pa.Table]: ...


@overload
def checked_loader(loader: None) -> None: ...


def checked_loader(loader: Callable[[str], pa.Table] | None) -> Callable[[str], pa.Table] | None:
    """A `source_loader` whose every returned table passes `check_source_dates`."""
    if loader is None:
        return None

    def load(name: str) -> pa.Table:
        return check_source_dates(loader(name), table=name)

    return load


__all__ = [
    "check_resident_sources",
    "check_source_dates",
    "check_source_schema",
    "checked_batches",
    "checked_loader",
]
