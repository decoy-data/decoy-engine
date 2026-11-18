"""Cell format of a fitted column: the shape of its cells, checked on read and applied at sampling.

A snapshot column entry can carry a `cell_format` block that records how the source cells
were written, so generation can reproduce it. The fit half (`learn_cell_format`,
`add_cell_format`), the member descriptor `CELL_FORMAT_MEMBERS` and `scrub_cell_format` live in
`profiling/cell_format.py`, which the snapshot writer reaches without a back import from
`profiling` into `generation`; they are re-exported here so this module stays the one place the
reader and sampler look. This module holds the strict decoders (`decode_cell_format`,
`cell_format_from_dict`) and the apply side (`round_numeric`, `floor_datetime`,
`cell_format_arrow_type`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, NoReturn

from decoy_engine import reasons
from decoy_engine.profiling.cell_format import (
    CELL_FORMAT_MEMBERS,
    UNIT_MICROS,
)
from decoy_engine.profiling.cell_format import (
    MAX_DECIMAL_PLACES as MAX_DECIMAL_PLACES,
)
from decoy_engine.profiling.cell_format import (
    RESOLUTIONS as RESOLUTIONS,
)
from decoy_engine.profiling.cell_format import (
    add_cell_format as add_cell_format,
)
from decoy_engine.profiling.cell_format import (
    cell_format_member_ok as cell_format_member_ok,
)
from decoy_engine.profiling.cell_format import (
    learn_cell_format as learn_cell_format,
)
from decoy_engine.profiling.cell_format import (
    scrub_cell_format as scrub_cell_format,
)

if TYPE_CHECKING:
    import pyarrow as pa

    from decoy_engine.generation.statistical._spec import StatisticalSpec

# Whole floats beyond this lose integer spacing, so they stay floats instead of becoming int64.
_INT_SAFE: Final = 2**53

# ── read ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CellFormat:
    """What the sampler needs from a fitted `cell_format` block, validated.

    `null_count` and `row_count` come from the snapshot column entry (the rate is
    `null_count / row_count`); `apply_nulls` is False when the column sets `null_probability`,
    so one null mechanism acts on a column.
    """

    null_count: int
    row_count: int
    apply_nulls: bool
    decimal_places: int | None = None
    resolution: str | None = None
    blank_count: int = 0

    @property
    def non_null_cells(self) -> int:
        return self.row_count - self.null_count


def _invalid(column: object, member: str, why: str) -> NoReturn:
    # Lazy: `_spec` imports this module for `CellFormat`. The message names the member, never its value.
    from decoy_engine.generation.statistical._spec import StatisticalSpecError

    raise StatisticalSpecError(
        code=reasons.plan.STATISTICAL_CELL_FORMAT_INVALID,
        message=f"statistical column {column!r}: cell_format {member}: {why}.",
    )


def _check_counts(column: object, null_count: object, row_count: object) -> None:
    if type(null_count) is not int or type(row_count) is not int:
        _invalid(column, "null_count", "counts must be integers")
    if not 0 <= null_count <= row_count:
        _invalid(column, "null_count", "must lie between 0 and the row count")


def _check_members(column: object, kind: str, members: Mapping[str, object]) -> None:
    for member, value in members.items():
        if not cell_format_member_ok(kind, member, value):
            _invalid(
                column,
                str(member) if member in _ALL_MEMBERS else "block",
                "unsupported member or type",
            )


_ALL_MEMBERS: Final = frozenset(m for ms in CELL_FORMAT_MEMBERS.values() for m in ms)


def _check_blank_count(
    column: object, blank_count: int, non_null_count: int, first_edge: object, first_bin: object
) -> None:
    if blank_count > non_null_count:
        _invalid(column, "blank_count", "exceeds the non-null cells")
    if blank_count == 0:
        return
    if first_edge != 0 or not isinstance(first_bin, (int, float)) or blank_count > first_bin:
        _invalid(column, "blank_count", "does not fit the first length bin")


def decode_cell_format(
    column: object,
    kind: str,
    entry: Mapping[str, Any],
    *,
    snapshot: Mapping[str, Any],
    apply_nulls: bool,
) -> CellFormat | None:
    """The validated `CellFormat` of a snapshot column entry, or None when it has no block.

    Every refusal is `plan.statistical_cell_format_invalid` naming the column and the member.
    """
    if "cell_format" not in entry:
        return None
    block = entry["cell_format"]
    if type(block) is not dict:
        _invalid(column, "block", "must be an object")
    if snapshot.get("dp") is not None:
        _invalid(column, "block", "not allowed on a differentially private snapshot")
    _check_members(column, kind, block)
    null_count, non_null = entry.get("null_count"), entry.get("non_null_count")
    if type(null_count) is not int or type(non_null) is not int or null_count < 0 or non_null < 0:
        _invalid(column, "null_count", "counts must be non-negative integers")
    row_count = null_count + non_null
    if row_count != snapshot.get("row_count"):
        _invalid(column, "null_count", "counts disagree with the snapshot row count")
    blank_count = block.get("blank_count", 0)
    if kind == "freetext":
        stats = entry.get("stats") or {}
        edges = stats.get("length_bin_edges") or [None]
        counts = stats.get("length_bin_counts") or [None]
        _check_blank_count(column, blank_count, non_null, edges[0], counts[0])
    return CellFormat(
        null_count=null_count,
        row_count=row_count,
        apply_nulls=apply_nulls,
        decimal_places=block.get("decimal_places"),
        # A hand-written datetime block without a resolution means "no flooring".
        resolution=block.get("resolution", "microsecond" if kind == "datetime" else None),
        blank_count=blank_count,
    )


_FIELDS: Final = frozenset(CellFormat.__dataclass_fields__)


def cell_format_from_dict(column: object, kind: str, data: object) -> CellFormat | None:
    """Rebuild a `CellFormat` from its stored six-field form with the same rules as the snapshot reader."""
    if data is None:
        return None
    if not isinstance(data, Mapping) or set(data) != _FIELDS:
        _invalid(column, "block", "must be an object with exactly the stored members")
    _check_counts(column, data["null_count"], data["row_count"])
    if type(data["apply_nulls"]) is not bool:
        _invalid(column, "apply_nulls", "must be a boolean")
    places, resolution, blanks = data["decimal_places"], data["resolution"], data["blank_count"]
    stored = {"decimal_places": places, "resolution": resolution, "blank_count": blanks}
    for member, value in stored.items():
        allowed = member in CELL_FORMAT_MEMBERS.get(kind, {})
        unused = value is None if member != "blank_count" else value == 0
        if not (cell_format_member_ok(kind, member, value) if allowed else unused):
            _invalid(column, member, "unsupported member or type")
    if blanks > data["row_count"] - data["null_count"]:
        _invalid(column, "blank_count", "exceeds the non-null cells")
    return CellFormat(
        null_count=data["null_count"],
        row_count=data["row_count"],
        apply_nulls=data["apply_nulls"],
        decimal_places=places,
        resolution=resolution,
        blank_count=blanks,
    )


# ── apply ────────────────────────────────────────────────────────────────────


def round_numeric(x: float, places: int) -> float:
    """Round half to even (Python `round`), the same rule as pandas/numpy `round` at fit."""
    return round(x, places)


def _grid_inside(x: float, places: int, low: float, high: float) -> float:
    """`x` rounded to `places`, moved to the nearest grid point inside [low, high] when it fell outside."""
    r = round_numeric(x, places)
    scale = 10.0**places
    if r < low:
        r = round_numeric(math.ceil(low * scale) / scale, places)
    elif r > high:
        r = round_numeric(math.floor(high * scale) / scale, places)
    return min(max(r, low), high)


def format_numeric(x: float, fmt: CellFormat, low: float, high: float, *, as_int: bool) -> Any:
    """A drawn value in the source's decimal places, inside [low, high]; `int` when `as_int`."""
    places = fmt.decimal_places
    if places is None:
        return int(min(max(round(x), low), high)) if as_int else x
    r = _grid_inside(x, places, low, high)
    return int(r) if as_int else r


def emits_int(spec: StatisticalSpec) -> bool:
    """True when a numeric column is written as Python `int` (Arrow int64)."""
    if is_integer_dtype(spec.dtype):
        return True
    fmt = spec.cell_format
    if fmt is None or fmt.decimal_places != 0:
        return False
    edges = spec.stats.get("bin_edges") or [0]
    return float(edges[0]) >= -_INT_SAFE and float(edges[-1]) <= _INT_SAFE


def is_integer_dtype(dtype: str) -> bool:
    return dtype.lstrip("uU").startswith("int") or dtype.startswith("Int")


_FLOOR_MICROS: Final = dict(UNIT_MICROS)
_ONE_MICRO: Final = timedelta(microseconds=1)


def floor_datetime(ts: datetime, resolution: str, low: datetime) -> datetime | date:
    """`ts` floored to the source resolution and kept at or above `low`; a `date` at day resolution."""
    size = _FLOOR_MICROS.get(resolution)
    if size is not None:
        micros = (ts - datetime(1970, 1, 1)) // _ONE_MICRO
        ts = datetime(1970, 1, 1) + (micros - micros % size) * _ONE_MICRO
        ts = max(ts, low)
    return ts.date() if resolution == "day" else ts


def cell_format_arrow_type(spec: StatisticalSpec) -> pa.DataType:
    """The Arrow type of a fitted column, from the spec so an all-None slice keeps it."""
    import pyarrow as pa

    kind = spec.kind
    if kind == "numeric":
        return pa.int64() if emits_int(spec) else pa.float64()
    if kind == "datetime":
        return (
            pa.date32()
            if spec.cell_format and spec.cell_format.resolution == "day"
            else pa.timestamp("us")
        )
    if kind == "categorical":
        from decoy_engine.generation.statistical._sample import _categorical_tables

        values, _ = _categorical_tables(spec)
        return pa.array(values).type if values else pa.null()
    if kind == "freetext":
        return pa.string()
    return pa.null()
