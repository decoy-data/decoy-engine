"""The stored datetime bucket contract of a distribution snapshot (versions 1 and 2).

A v1 snapshot stores one bucket per calendar year, ``{year, count}``. A v2 snapshot stores a
contiguous year range, ``{start_year, end_year, count}``, so a short run of years can be folded
into one bucket that holds enough rows to release. This module is the only place that reads or
writes those entries: every consumer (spec loading, admission, the sampler, both fidelity scorers)
gets the normalized ``DatetimeBucket`` tuple from ``decode_datetime_buckets`` and never parses a
stored dict itself. A v1 entry normalizes to the one-year range ``(year, year, count)``.

The v2 writer model is one frozen strict Pydantic model and its stored reader is a ``TypeAdapter``
over that same model, so the field names and types are written once. The v1 read model exists only
to accept files written before v2; nothing writes it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

SCHEMA_VERSION_V1 = "distribution-snapshot/v1"
SCHEMA_VERSION_V2 = "distribution-snapshot/v2"
ACCEPTED_SCHEMA_VERSIONS = (SCHEMA_VERSION_V1, SCHEMA_VERSION_V2)

# The years a datetime bucket may name. `datetime(year + 1, 1, 1)` must be representable, so the top
# is 9998. A multi-year range outside it is refused at decode whatever its count.
MIN_YEAR = 1
MAX_SAMPLED_YEAR = 9998


@dataclass(frozen=True)
class DatetimeBucket:
    """A contiguous closed year range and the number of rows in it. One year when start == end."""

    start_year: int
    end_year: int
    count: int | float


class DatetimeBucketV2(BaseModel):
    """The stored v2 bucket. Strict: a bool, string or float is not a year or a count."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    start_year: int
    end_year: int
    count: int = Field(ge=0)


class _LegacyBucketV1(BaseModel):
    """The stored v1 bucket. Years are strict integers. A count may be a finite non-negative float
    because fixtures written before v2 carry them; no v1 writer produces one."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    year: int
    count: int | float = Field(ge=0, allow_inf_nan=False)


class _PinnedBucket(BaseModel):
    """A bucket inside a compiled plan's pinned spec. It carries the count as ``load_spec`` decoded
    it, so a v1 fractional count survives the pin; stored v2 files still use ``DatetimeBucketV2``."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    start_year: int
    end_year: int
    count: int | float = Field(ge=0, allow_inf_nan=False)


_V2_LIST = TypeAdapter(list[DatetimeBucketV2])
_V1_LIST = TypeAdapter(list[_LegacyBucketV1])
_PINNED_LIST = TypeAdapter(list[_PinnedBucket])


def encode_datetime_buckets(buckets: Sequence[DatetimeBucket]) -> list[dict[str, int]]:
    """The only v2 bucket writer. Validates through the stored model and the order rule."""
    rows = [
        DatetimeBucketV2(start_year=b.start_year, end_year=b.end_year, count=int(b.count))
        for b in buckets
    ]
    _check_order([DatetimeBucket(r.start_year, r.end_year, r.count) for r in rows])
    return [r.model_dump() for r in rows]


def decode_datetime_buckets(
    schema_version: Any, stats: Mapping[str, Any]
) -> tuple[DatetimeBucket, ...]:
    """The only parser of stored datetime buckets. Raises a fixed-text ``ValueError`` on a missing or
    unknown version, a malformed entry, a mixed v1/v2 list, or ranges that are inverted,
    overlapping or out of order. An absent or empty list decodes to an empty tuple."""
    if schema_version not in ACCEPTED_SCHEMA_VERSIONS:
        raise ValueError("the snapshot schema_version is missing or not supported")
    raw = stats.get("year_bins") or []
    if not isinstance(raw, list):
        raise ValueError("year_bins is not a list")
    failed = False
    try:
        if schema_version == SCHEMA_VERSION_V1:
            buckets = tuple(
                DatetimeBucket(b.year, b.year, b.count) for b in _V1_LIST.validate_python(raw)
            )
        else:
            buckets = tuple(
                DatetimeBucket(b.start_year, b.end_year, b.count)
                for b in _V2_LIST.validate_python(raw)
            )
    except ValidationError:
        failed = True
    if failed:
        # Raised outside the handler: Pydantic's own text quotes the input, which is snapshot content.
        raise ValueError("a year_bins entry has wrong fields or types")
    _check_order(buckets)
    return buckets


def _decode_pinned(stored: Sequence[Any]) -> tuple[DatetimeBucket, ...]:
    failed = False
    try:
        buckets = tuple(
            DatetimeBucket(b.start_year, b.end_year, b.count)
            for b in _PINNED_LIST.validate_python(list(stored))
        )
    except ValidationError:
        failed = True
    if failed:
        raise ValueError("a year_bins entry has wrong fields or types")
    _check_order(buckets)
    return buckets


def _check_order(buckets: Sequence[DatetimeBucket]) -> None:
    previous_end: int | None = None
    for b in buckets:
        if b.start_year > b.end_year:
            raise ValueError("a year_bins range ends before it starts")
        if b.start_year != b.end_year and not (
            b.start_year >= MIN_YEAR and b.end_year <= MAX_SAMPLED_YEAR
        ):
            raise ValueError("a year_bins range is outside the supported years")
        if previous_end is not None and b.start_year <= previous_end:
            raise ValueError("year_bins ranges overlap or are out of order")
        previous_end = b.end_year


def decoded_or_none(
    schema_version: Any, stats: Mapping[str, Any]
) -> tuple[DatetimeBucket, ...] | None:
    """``decode_datetime_buckets`` for callers that map a refusal to their own non-comparable or
    degenerate result instead of raising."""
    try:
        return decode_datetime_buckets(schema_version, stats)
    except ValueError:
        return None


def pinned_buckets(
    kind: str, stats: Mapping[str, Any], stored: Any
) -> tuple[DatetimeBucket, ...] | None:
    """Buckets for a pinned spec. A pin written with the field stores v2 entries; an older pin has
    only the v1 `year_bins` in its stats. ``None`` for a non-datetime kind or an unreadable list."""
    if stored is not None:
        try:
            return _decode_pinned(stored)
        except ValueError:
            return None
    return decoded_or_none(SCHEMA_VERSION_V1, stats) if kind == "datetime" else None


def year_weights(buckets: Sequence[DatetimeBucket]) -> dict[int, float]:
    """Expected rows per calendar year. A range's count is split across its years in proportion to
    the seconds each year holds, which is how the sampler spreads a draw inside the range. A
    one-year bucket returns its count unchanged."""
    out: dict[int, float] = {}
    for b in buckets:
        if b.start_year == b.end_year:
            out[b.start_year] = float(b.count)
            continue
        seconds = {
            y: (datetime(y + 1, 1, 1) - datetime(y, 1, 1)).total_seconds()
            for y in range(b.start_year, b.end_year + 1)
        }
        total = math.fsum(seconds.values())
        for y, s in seconds.items():
            out[y] = float(b.count) * s / total
    return out


def names_unsupported_year(stats: Mapping[str, Any]) -> bool:
    """True when a raw ``year_bins`` entry names an integer year outside the supported range. Lets a
    caller tell "refused for an out-of-range year" from "malformed" after ``decoded_or_none``
    returned ``None``; it reads no value into any message."""
    raw = stats.get("year_bins")
    if not isinstance(raw, list):
        return False
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        for key in ("year", "start_year", "end_year"):
            y = entry.get(key)
            if (
                isinstance(y, int)
                and not isinstance(y, bool)
                and not MIN_YEAR <= y <= MAX_SAMPLED_YEAR
            ):
                return True
    return False


def with_year_weights(document: Mapping[str, Any]) -> dict[str, Any]:
    """The document's ``columns`` with each datetime column's stats gaining ``year_weights``
    (``{year: expected rows}``) read through this decoder, or ``None`` when the buckets do not
    decode. The scorers read that key and never ``year_bins``."""
    version = document.get("schema_version")
    out: dict[str, Any] = {}
    for name, col in (document.get("columns") or {}).items():
        if not (isinstance(col, Mapping) and col.get("kind") == "datetime"):
            out[name] = col
            continue
        stats = dict(col.get("stats") or {})
        buckets = decoded_or_none(version, stats)
        stats["year_weights"] = None if buckets is None else year_weights(buckets)
        out[name] = {**col, "stats": stats}
    return out
