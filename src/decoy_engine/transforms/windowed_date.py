"""windowed_date column-level strategy (SP-10c / P5.S.windowed_date).

Generates a date within a bounded window relative to an anchor date column.
The output date for each row is:

    anchor_date + offset_days

where offset_days is drawn from [min_days, max_days] (inclusive) from a keyed per-row index.

Three distributions are supported:

  uniform  - each day in [min_days, max_days] is equally likely.
  early    - dates near the start of the window are more likely (geometric
             decay from min_days toward max_days).
  late     - dates near the end of the window are more likely (geometric
             decay from max_days toward min_days).

Pattern: derive()-per-column namespace + bounded date offset. Each draw is the pool
sampler's index kernel (`derive_index_batch`: HKDF-SHA256 + HMAC-SHA256, RFC 5869 + RFC
2104, first 8 bytes modulo the pool size) over the integer source `2 * row + k`, where `row`
is the global row number and `k` is the draw (0, or 1 for the second draw of `early` and
`late`). The column namespace keys it, so two windowed_date columns produce independent
per-row offsets. The whole column is one batch call.

Security design:
  The distribution set is a CLOSED enumeration (WINDOWED_DATE_DISTRIBUTIONS).
  Only the three listed names can construct a valid config. No eval() or
  exec() anywhere in this module.

Determinism:
  Same 8-byte seed + same namespace + same anchor column -> byte-identical
  output dates on every run, for any batch size, route or thread count. The offset
  depends only on (seed, namespace, global row number), so a partition reproduces it.

Validation timing:
  anchor + max_days + distribution + min <= max: config-parse time
  (WindowedDateConfig.from_dict).
  anchor column existence: plan-compile time (check_windowed_date_refs).
  Validation never mutates (per engine rule).
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
import pyarrow as pa

from decoy_engine import reasons
from decoy_engine.determinism import check_pool_size
from decoy_engine.determinism._derive import DeriveContext
from decoy_engine.errors import DecoyError
from decoy_engine.generation.pool import derive_validated_indices
from decoy_engine.plan._errors import PlanCompileError

# Closed enumeration of allowed distributions.
WINDOWED_DATE_DISTRIBUTIONS: frozenset[str] = frozenset({"uniform", "early", "late"})

# Output date format for string-typed anchor columns.
_DATE_FMT = "%Y-%m-%d"

# Supported date range, for the anchor and for the produced date. It is declared (not inherited
# from pandas' nanosecond bounds) so the accepted domain does not move with a pandas release, and
# it is narrower than those bounds so window arithmetic cannot silently wrap near the edge.
SUPPORTED_MIN = pd.Timestamp("1700-01-01")
SUPPORTED_MAX = pd.Timestamp("2200-12-31 23:59:59.999999999")

# The only string anchor grammar: a numeric ISO date or ISO datetime with NO timezone. Anything
# else is rejected BEFORE parsing, because `pd.Timestamp` also accepts "now"/"today" (wall clock),
# zone-bearing strings, and locale or partial forms, none of which are reproducible or
# route-independent.
_ISO_ANCHOR = re.compile(
    r"\A\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?)?\Z",
    re.ASCII,
)


class WindowedDateError(DecoyError, ValueError):
    """A non-null anchor cannot be windowed (grammar, NaT, out of range, or overflow).

    The message names the row position and the reason only, never the anchor value, so a
    failure cannot leak cell content into logs.
    """


class WindowedDateRowNumberError(WindowedDateError):
    """A global row number is outside the draw's domain; the message names no number."""

    code: str = reasons.runtime.WINDOWED_DATE_ROW_NUMBER_OUT_OF_RANGE


# The draw source is `2 * row + k`, so `2 * row + 1` must fit int64 and stay in the range where
# the index kernel's signed big-endian encoding is the same on the compiled and reference kernel.
_ROW_NUMBER_LIMIT = 2**62
# Offsets are held as int64. A window with a bound past this cannot be, and every offset in it is
# past the Timedelta range anyway (a window wider than 2**56 is refused by the pool-size check).
_INT64_SAFE_BOUND = 2**62


@dataclass(frozen=True)
class WindowedDateConfig:
    """Configuration for a windowed_date column.

    Attributes:
        anchor:       Name of the anchor date column. Rows in the same table
                      must carry parseable date or datetime values in this
                      column.
        min_days:     Minimum offset from anchor in days (may be negative for
                      dates before the anchor; default 0).
        max_days:     Maximum offset from anchor in days (must be >= min_days).
        distribution: Sampling distribution over [min_days, max_days]. One of
                      "uniform", "early", or "late".
    """

    anchor: str
    min_days: int
    max_days: int
    distribution: str

    @classmethod
    def from_dict(cls, cfg: dict[str, Any]) -> WindowedDateConfig:
        """Parse and validate a windowed_date config dict.

        anchor, max_days, and distribution are validated at parse time.
        Anchor column existence is validated at plan-compile time via
        check_windowed_date_refs.

        Args:
            cfg: Config dict with required keys ``anchor`` and ``max_days``.

        Raises:
            PlanCompileError: ``anchor`` is missing or empty.
            PlanCompileError: ``max_days`` is missing.
            PlanCompileError: ``distribution`` is set but not in
                WINDOWED_DATE_DISTRIBUTIONS.
            PlanCompileError: ``min_days`` or ``max_days`` is more than 106751 days from zero.
            PlanCompileError: ``min_days`` > ``max_days``.
        """
        anchor = cfg.get("anchor")
        if not anchor:
            raise PlanCompileError(
                code=reasons.plan.WINDOWED_DATE_ANCHOR_MISSING,
                path="provider_config.anchor",
                message=(
                    "'anchor' is required for the windowed_date strategy. "
                    "Provide the name of the reference date column."
                ),
            )

        if "max_days" not in cfg or cfg.get("max_days") is None:
            raise PlanCompileError(
                code=reasons.plan.WINDOWED_DATE_MAX_DAYS_MISSING,
                path="provider_config.max_days",
                message=(
                    "'max_days' is required for the windowed_date strategy. "
                    "Provide the maximum offset in days from the anchor date."
                ),
            )

        min_days = int(cfg.get("min_days", 0))
        max_days = int(cfg["max_days"])

        for field, days in (("min_days", min_days), ("max_days", max_days)):
            if abs(days) > _MAX_TIMEDELTA_DAYS:
                raise PlanCompileError(
                    code=reasons.plan.WINDOWED_DATE_WINDOW_OUT_OF_RANGE,
                    path=f"provider_config.{field}",
                    message=f"'{field}' must be within {_MAX_TIMEDELTA_DAYS} days of the anchor.",
                )

        if min_days > max_days:
            raise PlanCompileError(
                code=reasons.plan.WINDOWED_DATE_MIN_EXCEEDS_MAX,
                path="provider_config.min_days",
                message=(f"'min_days' ({min_days}) must be <= 'max_days' ({max_days})."),
            )

        distribution = str(cfg.get("distribution", "uniform"))
        if distribution not in WINDOWED_DATE_DISTRIBUTIONS:
            raise PlanCompileError(
                code=reasons.plan.WINDOWED_DATE_DISTRIBUTION_INVALID,
                path="provider_config.distribution",
                message=(
                    f"'distribution' must be one of "
                    f"{sorted(WINDOWED_DATE_DISTRIBUTIONS)!r}; "
                    f"got {distribution!r}."
                ),
            )

        return cls(
            anchor=str(anchor),
            min_days=min_days,
            max_days=max_days,
            distribution=distribution,
        )


def validate_window_config(cfg: dict[str, Any]) -> None:
    """Run the parse-time window checks on a mask column's `provider_config` at plan compile.

    Skipped when the anchor or a day bound is absent or not an integer: those shapes are refused
    elsewhere, with their own codes, and this must not change which error a config raises.
    """

    def _is_int(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    if cfg.get("anchor") and _is_int(cfg.get("max_days")) and _is_int(cfg.get("min_days", 0)):
        WindowedDateConfig.from_dict(cfg)


def _draw_offsets(
    rows: Sequence[int], config: WindowedDateConfig, seed: bytes, namespace: str
) -> npt.NDArray[np.int64]:
    """One offset in [min_days, max_days] per global row number, in one batch.

    uniform: `min_days` plus the index drawn for source `2 * row`.
    early:   the smaller of the offsets for sources `2 * row` and `2 * row + 1` (the minimum of
             two uniform draws makes the start of the window likelier).
    late:    the larger of the two.

    The source is part of the draw, not of the namespace, and `(row, k) -> 2 * row + k` is
    injective, so no two draws share a source. A zero-width window draws nothing. An empty
    batch builds no key context, so an all-null column needs no usable seed or namespace.
    """
    try:
        count = len(rows)
        if count == 0:
            return np.empty(0, dtype=np.int64)
        if min(rows) < 0 or max(rows) >= _ROW_NUMBER_LIMIT:
            raise WindowedDateRowNumberError(
                "windowed_date global row number is outside 0 to 2**62 - 1"
            )
        lo, hi = config.min_days, config.max_days
        # Same seed and namespace refusals as `derive`, with the same text.
        DeriveContext.for_column(seed, namespace)
        span = hi - lo
        fits_int64 = lo >= -_INT64_SAFE_BOUND and hi < _INT64_SAFE_BOUND
        if span == 0 and fits_int64:
            return np.full(count, lo, dtype=np.int64)
        pool_size = span + 1
        check_pool_size(pool_size)
        if not fits_int64:
            # Past int64 every offset is past the Timedelta range, so the shift step refuses it
            # exactly as it refuses any other offset that large.
            return np.full(
                count,
                _MAX_TIMEDELTA_DAYS + 1 if lo > 0 else -_MAX_TIMEDELTA_DAYS - 1,
                dtype=np.int64,
            )
        sources = np.asarray(rows, dtype=np.int64) * 2
        draws: list[npt.NDArray[np.int64]] = []
        for k in range(1 if config.distribution == "uniform" else 2):
            checked = derive_validated_indices(
                pa.array(sources + k, type=pa.int64()),
                mask_key=seed,
                namespace=namespace,
                pool_size=pool_size,
            )
            draws.append(lo + checked.astype(np.int64))
        if len(draws) == 1:
            return draws[0]
        pick = np.minimum if config.distribution == "early" else np.maximum
        return pick(draws[0], draws[1])
    except BaseException:
        del seed
        raise


def _is_null_cell(raw: Any) -> bool:
    """True only for an actual null cell. A string such as "" or "NaT" is NOT null."""
    if raw is None or raw is pd.NaT or raw is pd.NA:
        return True
    return isinstance(raw, float) and raw != raw  # NaN is the only self-unequal float


def _parse_anchor(raw: Any, position: int) -> pd.Timestamp:
    """Validate one non-null anchor against the supported grammar and range, then parse it."""
    ts: pd.Timestamp
    failed = False
    if isinstance(raw, str):
        if _ISO_ANCHOR.match(raw) is None:
            raise WindowedDateError(
                f"windowed_date anchor at row {position} is not an ISO date or datetime "
                "without a timezone"
            )
        # The pandas error text embeds the raw cell (e.g. "day is out of range for month:
        # 2024-02-30"). Raise outside the except block so neither __cause__ nor __context__
        # carries it into a formatted traceback.
        try:
            ts = pd.Timestamp(raw)
        except (ValueError, OverflowError):
            failed = True
        if failed:
            raise WindowedDateError(
                f"windowed_date anchor at row {position} is not a valid calendar date"
            ) from None
    elif isinstance(raw, (pd.Timestamp, _dt.datetime, _dt.date)):
        # Typed date32 / timestamp anchors (and datetime64 mask-side columns) arrive as these.
        if getattr(raw, "tzinfo", None) is not None:
            raise WindowedDateError(f"windowed_date anchor at row {position} carries a timezone")
        # Same leak as above: the pandas bounds error quotes the cell value.
        try:
            ts = pd.Timestamp(raw)
        except (ValueError, OverflowError):
            failed = True
        if failed:
            raise WindowedDateError(
                f"windowed_date anchor at row {position} is outside the supported range"
            ) from None
    else:
        raise WindowedDateError(
            f"windowed_date anchor at row {position} has unsupported type {type(raw).__name__}"
        )
    if ts is pd.NaT or pd.isna(ts):
        raise WindowedDateError(f"windowed_date anchor at row {position} parses to NaT")
    if not (SUPPORTED_MIN <= ts <= SUPPORTED_MAX):
        raise WindowedDateError(
            f"windowed_date anchor at row {position} is outside the supported range"
        )
    return ts


def _shift_and_format(anchor: pd.Timestamp, offset: int, position: int) -> str:
    # The pandas/strftime error text can quote the anchor or shifted date, so the cause is
    # dropped (raised outside the except block: no __cause__, no __context__).
    try:
        out = anchor + pd.Timedelta(offset, unit="D")
        if SUPPORTED_MIN <= out <= SUPPORTED_MAX:
            return str(out.strftime(_DATE_FMT))
    except (OverflowError, ValueError):
        pass
    raise WindowedDateError(
        f"windowed_date result at row {position} is outside the supported range"
    ) from None


# Largest |offset| in days that `pd.Timedelta` represents (ns int64). The per-row reference path
# raises past it even when the shifted date is in range, so the batched path must hand such a
# batch to the reference path instead of computing a result.
_MAX_TIMEDELTA_DAYS = 106_751
_MIN_DAY = int(SUPPORTED_MIN.to_datetime64().astype("datetime64[D]").astype(np.int64))
_MAX_DAY = int(SUPPORTED_MAX.to_datetime64().astype("datetime64[D]").astype(np.int64))


def _vector_parse(cells: list[Any], kind: type) -> npt.NDArray[np.datetime64] | None:
    """Parse one batch of non-null anchors of a single exact type, or None for any anomaly.

    Draws nothing. None sends the whole batch to the per-row reference loop, which owns every
    error message.
    """
    if kind is str:
        if not all(_ISO_ANCHOR.fullmatch(c) for c in cells):
            return None
        parsed = pd.to_datetime(cells, format="ISO8601")
    elif kind is _dt.date:
        parsed = pd.to_datetime(cells)
    elif kind in (_dt.datetime, pd.Timestamp):
        if any(c.tzinfo is not None for c in cells):
            return None
        parsed = pd.to_datetime(cells)
    else:
        return None
    values = parsed.to_numpy()
    if values.dtype != np.dtype("datetime64[ns]") or bool(np.isnat(values).any()):
        return None
    return values


def _prepare_batch(
    anchor_series: pd.Series,
    row_offset: int,
    positions: Sequence[int] | None,
) -> tuple[npt.NDArray[np.datetime64], npt.NDArray[np.intp], list[int]] | None:
    """Parsed non-null anchors, their batch indexes and global row numbers, or None.

    None means "use the reference loop": a mixed or unadmitted cell type, a subclass, a tz-aware
    value, a grammar miss, a `positions` length mismatch, or any pandas surprise.
    """
    n = len(anchor_series)
    if positions is not None and len(positions) != n:
        return None
    if str(anchor_series.dtype) == "datetime64[ns]":
        raw = anchor_series.to_numpy()
        keep = np.flatnonzero(~np.isnat(raw))
        values: npt.NDArray[np.datetime64] | None = raw[keep]
    else:
        cells = list(anchor_series)
        keep = np.fromiter((k for k, c in enumerate(cells) if not _is_null_cell(c)), dtype=np.intp)
        kept = [cells[k] for k in keep]
        kinds = {type(c) for c in kept}
        if len(kinds) > 1:
            return None
        values = (
            _vector_parse(kept, next(iter(kinds))) if kinds else np.empty(0, dtype="datetime64[ns]")
        )
    # One range check for every input class: an out-of-range anchor must raise as the per-row loop
    # does, not shift back into range.
    if values is None or (
        values.size
        and (
            values.min() < SUPPORTED_MIN.to_datetime64()
            or values.max() > SUPPORTED_MAX.to_datetime64()
        )
    ):
        return None
    if positions is None:
        rows = [row_offset + int(k) for k in keep]
    else:
        rows = [int(positions[k]) for k in keep]
    return values, keep, rows


def _shift_and_format_batch(
    values: npt.NDArray[np.datetime64],
    offsets: npt.NDArray[np.int64],
    keep: npt.NDArray[np.intp],
    size: int,
) -> list[str | None] | None:
    """Shift whole days and format, or None when the reference loop must decide.

    The output keeps only the date, so adding whole days to the day number is the same as the
    reference timestamp add. The checks run in integer days first: NumPy datetime arithmetic
    wraps silently past its range, and the reference raises for an offset past the Timedelta
    range even when the shifted date would be in range.
    """
    if offsets.size and int(np.abs(offsets).max()) > _MAX_TIMEDELTA_DAYS:
        return None
    days = values.astype("datetime64[D]").astype(np.int64) + offsets
    if days.size and (int(days.min()) < _MIN_DAY or int(days.max()) > _MAX_DAY):
        return None
    formatted = np.datetime_as_string(days.astype("datetime64[D]"), unit="D")
    out = np.full(size, None, dtype=object)
    out[keep] = formatted
    result: list[str | None] = out.tolist()
    return result


def apply_windowed_date(
    config: WindowedDateConfig,
    df: pd.DataFrame,
    seed: bytes,
    namespace: str,
    row_offset: int = 0,
    positions: Sequence[int] | None = None,
) -> list[str | None]:
    """Generate one date per row within the configured window around the anchor.

    Pattern: the pool sampler's keyed index kernel for the per-row offsets (see
    `_draw_offsets`); pandas Timestamp + Timedelta for date arithmetic.

    Args:
        config:     Parsed WindowedDateConfig.
        df:         DataFrame containing the anchor date column.
        seed:       8-byte job seed (or 32-byte mask key) that keys the offset draws.
        namespace:  Per-column namespace string (e.g. "windowed_date/<col>") that keys the
                    draws, so two windowed_date columns in the same job produce
                    independent offsets.
        row_offset: Durable global row number of `df`'s row 0 (Phase 4 slice
                    1 / DGRN). Default 0 keeps every full-frame / non-chunked
                    call byte-unchanged: `row_index` for local row `j` is
                    `row_offset + j`, which equals the plain `j` full-frame
                    enumeration produces when `row_offset == 0`. A chunked
                    caller passes the chunk's own durable offset so `i`
                    tracks the row's true position in the whole, unchunked
                    source instead of restarting at 0 each chunk.

    Returns:
        List of ISO-format date strings (``YYYY-MM-DD``) aligned to df rows. A genuine null
        anchor cell yields ``None`` and consumes no draw.

    Raises:
        WindowedDateRowNumberError: a global row number is below 0 or at or above 2**62.
        WindowedDateError: a non-null anchor fails the accepted grammar, parses to NaT (including
            ``""`` and ``"NaT"``), lies outside ``SUPPORTED_MIN``..``SUPPORTED_MAX``, or the
            window arithmetic or formatting overflows. Fail-closed: no row is clamped.
    """
    try:
        anchor_series = df[config.anchor]
        # Batched path: the offset draw, the parse, the shift and the format run once per batch.
        # Any anomaly or Exception discards this work and reruns the batch through the per-row
        # loop below, which raises the first error in row order.
        batched: list[str | None] | None
        try:
            prepared = _prepare_batch(anchor_series, row_offset, positions)
            if prepared is None:
                batched = None
            else:
                values, keep, rows = prepared
                offsets = _draw_offsets(rows, config, seed, namespace)
                batched = _shift_and_format_batch(values, offsets, keep, len(anchor_series))
        except Exception:
            batched = None
        if batched is not None:
            return batched
        result: list[str | None] = []

        # C8-iii-d: `positions` gives each row its full-table row number under a `when:` gate, so a
        # selected row seeds the same as in an ungated run. Without it, rows are contiguous from
        # `row_offset`, byte-identical to the previous `enumerate(..., start=row_offset)`.
        row_numbers: Sequence[int] = (
            positions
            if positions is not None
            else range(row_offset, row_offset + len(anchor_series))
        )
        nonnull_rows = [
            int(i)
            for i, raw in zip(row_numbers, anchor_series, strict=True)
            if not _is_null_cell(raw)
        ]
        # One draw for the whole batch keeps this path near the batched one. If it fails (a bad
        # row number, seed or window), draw per row below so the first error is raised in row order.
        try:
            bulk: list[int] | None = _draw_offsets(nonnull_rows, config, seed, namespace).tolist()
        except Exception:
            bulk = None
        cursor = 0
        for i, raw_anchor in zip(row_numbers, anchor_series, strict=True):
            if _is_null_cell(raw_anchor):
                result.append(None)
                continue
            anchor_ts = _parse_anchor(raw_anchor, int(i))
            if bulk is not None:
                offset = bulk[cursor]
                cursor += 1
            else:
                offset = int(_draw_offsets([int(i)], config, seed, namespace)[0])
            result.append(_shift_and_format(anchor_ts, offset, int(i)))

        return result
    except BaseException:
        del seed
        raise
