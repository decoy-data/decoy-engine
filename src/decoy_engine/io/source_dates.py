"""The checked source read: Arrow dates outside calendar years 1 to 9999 are refused by table,
column and count before pandas or Python can see a value (DATE-RANGE-SENTINEL S5).

`check_source_dates` is the one operation. Every reader, loader and entry that hands Arrow data on
to pandas, a strategy or a native kernel calls it (or `checked_batches`, `checked_loader`,
`check_resident_sources`, which wrap it) and carries on with what it returns.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any, TypeVar, overload

import pyarrow as pa
import pyarrow.compute as pc

from decoy_engine._arrow_types import CALENDAR_FIRST_DAY_NUMBER, CALENDAR_LAST_DAY_NUMBER
from decoy_engine.io.bounded_reader import SourceDateUnrepresentableError

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


def _is_temporal(arrow_type: pa.DataType) -> bool:
    return (
        pa.types.is_date32(arrow_type)
        or pa.types.is_date64(arrow_type)
        or pa.types.is_timestamp(arrow_type)
    )


def _holds_dates(arrow_type: pa.DataType) -> bool:
    """Whether a value of this type can contain a date or timestamp, at any depth."""
    if _is_temporal(arrow_type):
        return True
    if pa.types.is_dictionary(arrow_type):
        return _holds_dates(arrow_type.value_type)
    if pa.types.is_map(arrow_type):
        return _holds_dates(arrow_type.key_type) or _holds_dates(arrow_type.item_type)
    if (
        pa.types.is_list(arrow_type)
        or pa.types.is_large_list(arrow_type)
        or pa.types.is_fixed_size_list(arrow_type)
    ):
        return _holds_dates(arrow_type.value_type)
    if pa.types.is_struct(arrow_type):
        return any(_holds_dates(arrow_type.field(i).type) for i in range(arrow_type.num_fields))
    return False


def _children(column: Any) -> list[Any]:
    """The value columns nested inside a list, map or struct column, with a null parent's
    children left out, so a cell no row exposes is not counted."""
    arrow_type = column.type
    if pa.types.is_map(arrow_type):
        chunks = column.chunks if isinstance(column, pa.ChunkedArray) else [column]
        return [
            pa.chunked_array([c.keys for c in chunks], arrow_type.key_type),
            pa.chunked_array([c.items for c in chunks], arrow_type.item_type),
        ]
    if pa.types.is_struct(arrow_type):
        return list(column.flatten())
    return [_pc.list_flatten(column)]


def _offending_rows(column: Any) -> int:
    """How many cells of one column are outside calendar years 1 to 9999, 0 when the type
    cannot hold such a cell. A dictionary column counts the rows that reference a bad entry, so
    an entry no row uses does not refuse the job; `_without_unused_bad_entries` removes it before
    pandas can convert the dictionary. Dates nested in a list, map or struct are counted too."""
    arrow_type = column.type
    if not _holds_dates(arrow_type):
        return 0
    if pa.types.is_dictionary(arrow_type):
        return _offending_rows(column.cast(arrow_type.value_type))
    if not _is_temporal(arrow_type):
        return sum(_offending_rows(child) for child in _children(column))
    zone = False
    if pa.types.is_date32(arrow_type):
        ticks_per_day, ints = 1, column.cast(pa.int32())
    elif pa.types.is_date64(arrow_type):
        ticks_per_day, ints = _SECONDS_PER_DAY * 1_000, column.cast(pa.int64())
    else:
        ticks_per_day = _TICKS_PER_SECOND[arrow_type.unit] * _SECONDS_PER_DAY
        ints, zone = column.cast(pa.int64()), arrow_type.tz is not None
    low, high = _calendar_ticks(ticks_per_day)
    extrema = _pc.min_max(ints).as_py() if (low is not None or high is not None) else None
    if not extrema or extrema["min"] is None:
        return 0
    margin = _ZONE_MARGIN_DAYS * ticks_per_day if zone else 0
    if not (
        (low is not None and extrema["min"] < low + margin)
        or (high is not None and extrema["max"] > high - margin)
    ):
        return 0
    utc_outside = _count_outside(ints, low, high)
    if not zone:
        return _sum(utc_outside)
    # A zoned cell must fit the calendar as an instant and as a local date. The cells inside the
    # instant range but within the margin of an edge need the local wall-clock conversion.
    band = _count_outside(
        ints, None if low is None else low + margin, None if high is None else high - margin
    )
    inside_instant = _pc.invert(pc.fill_null(utc_outside, False))
    near_edge = _pc.and_(pc.fill_null(band, False), inside_instant)
    local = _pc.local_timestamp(column.filter(near_edge)).cast(pa.int64())
    return _sum(utc_outside) + _sum(_count_outside(local, low, high))


def _sum(mask: Any) -> int:
    return 0 if mask is None else int(_pc.sum(mask).as_py() or 0)


def _without_unused_bad_entries(column: Any) -> Any:
    """A dictionary-of-dates column with the out-of-calendar entries no row references taken out.

    Pandas converts a whole dictionary, so one unused bad entry would raise a value-bearing error
    for a column the job may read. The values rows reference, the index type and the schema stay
    the same; a column with no bad entry comes back as it is."""
    arrow_type = column.type
    if not (pa.types.is_dictionary(arrow_type) and _is_temporal(arrow_type.value_type)):
        return column
    chunks = column.chunks if isinstance(column, pa.ChunkedArray) else [column]
    if not any(_offending_rows(chunk.dictionary) for chunk in chunks):
        return column
    rebuilt = []
    for chunk in chunks:
        compact = chunk.cast(arrow_type.value_type).dictionary_encode()
        rebuilt.append(
            pa.DictionaryArray.from_arrays(
                compact.indices.cast(arrow_type.index_type),
                compact.dictionary,
                ordered=arrow_type.ordered,
            )
        )
    return (
        pa.chunked_array(rebuilt, arrow_type) if isinstance(column, pa.ChunkedArray) else rebuilt[0]
    )


def check_source_dates(data: _Batch, *, table: str) -> _Batch:
    """Refuse a source batch or table holding a date or timestamp outside calendar years 1 to 9999,
    and return the data to use from here on.

    Arrow stores dates as integers that reach years far past 9999, which pandas and Python cannot
    hold; this check sees the integers first, so the refusal never quotes a value. Only the
    column name and the count of offending cells leave this function. Every caller must carry on
    with the returned data: it differs from the input only by dropping an unused out-of-calendar
    dictionary entry that pandas would otherwise try to convert.
    """
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


def checked_batches(batches: Iterable[_Batch], *, table: str) -> Iterator[_Batch]:
    """Yield each batch (or table) only after `check_source_dates` passed it."""
    for batch in batches:
        yield check_source_dates(batch, table=table)


@overload
def check_resident_sources(sources: Mapping[str, Any]) -> dict[str, Any]: ...


@overload
def check_resident_sources(sources: None) -> None: ...


def check_resident_sources(sources: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Check every resident table of a run's `sources` at its entry, before any transform,
    profile or route sees it, and return the sources to run on. A lazy source is checked batch by
    batch as it is read."""
    if sources is None:
        return None
    return {
        name: check_source_dates(source, table=name) if isinstance(source, pa.Table) else source
        for name, source in sources.items()
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
    "checked_batches",
    "checked_loader",
]
