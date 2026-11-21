"""date_shift strategy (engine-v2 S9): shift each date by a keyed offset.

Re-keyed onto S3 (S9 spec §4 row 5): the per-value offset in
``[min_days, max_days]`` is `min_days + (int.from_bytes(derive(mask_key,
namespace, _canonicalize_source(value))[:8], "big") % range_size)`. The mask
key is the admitted secret (at least 32 bytes); there is no key-free path. Same
source date -> same shift within a namespace; byte-stable across runs. The
format is required: plan compile refuses a column without
`provider_config.date_format`, and the handler refuses it too (a column whose own declared
parse format supplies the shape is the one exception). Nothing guesses it from the cells.
Null + parse-failed positions restore the original value.

Pattern: HKDF-SHA256 then HMAC-SHA256 keyed deterministic offset (HKDF RFC 5869; HMAC RFC 2104).

Sprint 2 honesty pack (2026-07-04, D7/D8, discovery 0.1): a non-null cell
that fails `pd.to_datetime` parsing used to silently keep the ORIGINAL
source value in the output -- the same per-value leak class as bucketize
(#13). `run` now records a `RowError` (trigger "format_error") for such
cells via `_row_errors.py`'s shared channel; it does NOT null or rewrite the
cell (trap T4). Source-null cells are unaffected (null passthrough is not a
leak); only a NON-null cell that fails to parse is a format error.

HC-3(a) (2026-07-17): optional `group_by` config names an ENTITY column
(e.g. `patient_id`). When set, the per-row digest input is the GROUP
column's value instead of the date value, so every row sharing a group
value gets the SAME offset and intra-entity intervals (e.g. admission ->
discharge length-of-stay) survive the shift. This is the standard
entity-anchored date-shift de-identification technique (cf. HIPAA Safe
Harbor date-shift guidance: shift consistently per patient, not per
event). `group_by` is None by default, and the digest input is then
byte-identical to the pre-HC-3(a) behavior (the date value itself).

Anchor source (Codex R1 P1 #1): the anchor value is read from a PRE-MASK
snapshot threaded through `ctx.group_anchor_snapshots[(table, group_by)]`,
NOT from the live frame. Reading `df[group_by]` directly was wrong: if the
group column masks before this node (node order is lexicographic) or is
when-gated so only some of an entity's rows are rewritten, two rows of one
patient would anchor on different values (one masked, one raw) and shift
apart -- exactly the interval the feature preserves. Each adapter copies the
column pre-mask; the same requirement (immutable source value + lossless
int-with-null typing) as an FK parent key, so the same `fk_columns_for_table`
/ snapshot machinery carries it. On every SUPPORTED path a date_shift+group_by
column masks the FULL table frame (`when`, FK-participation, and `nested` are
all compile-rejected for group_by), so the snapshot -- built from that same
pre-mask frame -- shares its index exactly. The handler REQUIRES that index
identity and fails closed on any mismatch, rather than silently reindexing an
unexpected (filtered/reordered) frame -- so an unaccounted-for route becomes a
loud fail-closed error, never a silent mis-anchor. FAIL CLOSED likewise if a
configured `group_by` has no snapshot, rather than falling back to the live
(mutable) frame.

Null group-by value policy: `_canonicalize_source` hard-errors on a raw
null (None) and on the float NaN sentinel pandas normally produces for a
missing object-dtype cell (see generation/pool/_canonicalize.py), so
feeding a null group value straight through would crash non-deterministically
depending on column dtype. Instead, a row whose group value is null falls
back to anchoring on ITS OWN date value (the no-`group_by` behavior for
that one row): deterministic, no crash, and every null-group row is *not*
forced to collide on one shared offset (each keeps its own date-derived
offset, same as an ungrouped column).
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from decoy_engine import reasons
from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.contracts.strategy_requirements import requirement_missing
from decoy_engine.determinism._derive import DeriveContext
from decoy_engine.execution._adapter import (
    StrategyContext,
    StrategyOption,
    option,
    provider_config_to_dict,
)
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._row_errors import RowError
from decoy_engine.generation.pool._canonicalize import _canonicalize_source
from decoy_engine.generation.pool._events import QualityWarning
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.transforms.date_preserve import preserve_set_from_config
from decoy_engine.transforms.date_shift import shift_window


def _native_shape(column: str, ctx: StrategyContext) -> ColumnShape | None:
    """The date or zoned-timestamp shape the plan lists for this top-level column, else None.

    It keys on where the column sits in the plan (the table and column in
    ``ctx.native_date_columns``, and not running as a nested child), never on the data, so a typed
    column holding date objects and a text column are told apart by the plan alone. Such a column
    keeps its source type on the way out; a declared date column keeps its legacy text output.
    """
    if ctx.nested_outer_column:
        return None
    return ctx.native_date_columns.get((ctx.current_table, column))


def _is_declared(column: str, ctx: StrategyContext) -> bool:
    return not ctx.nested_outer_column and (ctx.current_table, column) in ctx.declared_date_columns


def _required_format(
    cfg: Mapping[str, Any], column: str, ctx: StrategyContext, shape: ColumnShape | None
) -> str | None:
    """The column's `date_format`, or None when the plan proves it a date and nothing needs parsing.

    Plan compile refuses a missing format before any read, so this is the backstop for a caller
    that reaches the handler without compile. A native date or zoned timestamp never uses a
    `date_format`, even one set by hand: the strategy reads the typed value and writes the same
    type back. A declared date column takes its shape from its declared parse format. It does not
    detect a format from the cells.
    """
    if shape is not None:
        return None
    fmt = cfg.get("date_format")
    if not requirement_missing(fmt):
        return str(fmt)
    if _is_declared(column, ctx):
        return None
    raise StrategyError(
        code=reasons.runtime.DATE_SHIFT_REQUIRES_DATE_FORMAT,
        strategy="date_shift",
        message=(
            f"column {ctx.nested_outer_column or column!r} uses date_shift but has no "
            "provider_config.date_format."
        ),
    )


class DateShiftStrategyHandler:
    """Shift dates by a deterministic per-value offset within a bounded range.

    Optional `group_by` (HC-3a): anchor the offset to a sibling entity
    column instead of the date value itself, so every date belonging to
    the same entity shifts by one consistent offset. See module docstring.
    """

    name: str = "date_shift"
    namespace_required: bool = True
    join_safe: bool = False
    wizard_options: tuple[StrategyOption, ...] = (
        option("min_days", "int", -30),
        option("max_days", "int", 30),
        option("date_format", "str", "%Y-%m-%d", required=True),
    )
    offer_in_wizard: bool = True

    def run(
        self,
        df: pd.DataFrame,
        column: str,
        plan: ColumnSeed,
        ctx: StrategyContext,
    ) -> tuple[pd.DataFrame, list[QualityWarning]]:
        if plan.namespace is None:
            raise StrategyError(
                code=reasons.runtime.DATE_SHIFT_REQUIRES_NAMESPACE,
                strategy="date_shift",
                message=f"column {column!r} uses date_shift but has no namespace.",
            )
        cfg = provider_config_to_dict(plan.provider_config)
        min_days, max_days = shift_window(cfg)
        range_size = max_days - min_days + 1
        shape = _native_shape(column, ctx)
        try:
            preserve = preserve_set_from_config(cfg, shape=shape)
        except ValueError as exc:
            raise StrategyError(
                code=reasons.runtime.DATE_SHIFT_INVALID_CONFIG,
                strategy="date_shift",
                message=f"date_shift column {column!r}: {exc}",
            ) from exc
        if preserve is not None and cfg.get("group_by"):
            raise StrategyError(
                code=reasons.runtime.DATE_PRESERVE_VALUES_WITH_GROUP_BY_UNSUPPORTED,
                strategy="date_shift",
                message=(
                    f"date_shift column {column!r} sets both preserve_values and group_by. "
                    "The entity anchor must row-align with the frame being shifted, which "
                    "excluding sentinel rows breaks. Remove one of the two."
                ),
            )

        col = df[column]
        source_dtype = col.dtype
        if pd.api.types.is_extension_array_dtype(col.dtype):
            col = col.astype(object)
        fmt = _required_format(cfg, column, ctx, shape)

        # HC-3(a): group_by anchors the digest input to a sibling entity
        # column read from the PRE-MASK snapshot in ctx, not the live frame
        # (see module docstring "Anchor source"). Existence + a non-empty
        # string ref are plan-compile checks (check_date_shift_group_by_refs).
        group_by = cfg.get("group_by")
        anchor_col: pd.Series | None = None
        if group_by:
            snapshot = ctx.group_anchor_snapshots.get((ctx.current_table, group_by))
            if snapshot is None:
                raise StrategyError(
                    code=reasons.runtime.DATE_SHIFT_GROUP_ANCHOR_SNAPSHOT_MISSING,
                    strategy="date_shift",
                    message=(
                        f"column {column!r} uses date_shift group_by {group_by!r} "
                        "but no pre-mask anchor snapshot was provided for it; the "
                        "run cannot anchor the shift deterministically. This is an "
                        "adapter wiring error, not a config error."
                    ),
                )
            # The snapshot must line up ROW-FOR-ROW with the frame this handler
            # sees. On every SUPPORTED path a date_shift+group_by column gets the
            # full table frame -- a `when` gate, an FK-participating column, and a
            # nested child are ALL compile-rejected for group_by -- so the snapshot,
            # built from that same pre-mask frame, has an identical index. Require
            # that identity and FAIL CLOSED otherwise instead of silently
            # reindexing: a future/unknown route that handed a filtered or
            # reordered frame (a fresh RangeIndex) would otherwise mis-anchor
            # UNDETECTABLY -- the exact wrong-output class this snapshot exists to
            # prevent (Dennis R2 LOW-1). This backstops any execution route not yet
            # accounted for at the handler, turning a silent-wrong-output into a
            # loud fail-closed raise.
            if not snapshot.index.equals(col.index):
                raise StrategyError(
                    code=reasons.runtime.DATE_SHIFT_GROUP_ANCHOR_SNAPSHOT_MISALIGNED,
                    strategy="date_shift",
                    message=(
                        f"column {column!r} date_shift group_by {group_by!r}: the "
                        "pre-mask anchor snapshot does not row-align with the frame "
                        "being masked (indexes differ). Anchoring would be wrong, so "
                        "the run fails closed. This indicates an execution route not "
                        "yet supported for group_by, not a config error."
                    ),
                )
            anchor_col = snapshot
            if pd.api.types.is_extension_array_dtype(anchor_col.dtype):
                anchor_col = anchor_col.astype(object)

        # group_by is not native, but admission declines it, so the seam books the row and
        # returns None (reporting the honest python_scalar backend) rather than being gated out.
        seq = getattr(ctx, "seq_native", None)
        # Admission declines a non-string source (`date_shift_source_not_string`), but a typed column
        # must not even reach the seam: it has no format for the kernel and would be booked native.
        if seq is not None and shape is None:
            native_out = seq.date_shift_column(
                ctx,
                df,
                column,
                namespace=plan.namespace,
                mask_key=ctx.mask_key,
                min_days=min_days,
                max_days=max_days,
                date_format=fmt,
                preserve=preserve,
            )
            if native_out is not None:
                df[column] = native_out
                return df, []

        preserved = preserve.mask(col) if preserve is not None else None
        if preserve is None or preserved is None or not preserved.any():
            out, error_rows = _shift_rows(
                col, fmt, anchor_col, ctx, plan.namespace, min_days, range_size, shape
            )
        else:
            # Sentinel rows never reach parsing, derivation or the whole-column strftime: the
            # operator runs on the remainder alone and the sentinel text is scattered back.
            rest = np.flatnonzero(~preserved)
            cells: list[Any] = [None] * len(col)
            error_rows = np.empty(0, dtype=np.intp)
            if rest.size:
                sub_out, sub_errors = _shift_rows(
                    col.iloc[rest], fmt, None, ctx, plan.namespace, min_days, range_size, shape
                )
                for position, value in zip(rest, sub_out, strict=True):
                    cells[position] = value
                error_rows = rest[sub_errors]
            for position, text in zip(
                np.flatnonzero(preserved), preserve.render(col, preserved), strict=True
            ):
                cells[position] = text
            out = cells
            ctx.record_date_preserved(column, int(preserved.sum()))
        for i in error_rows:
            ctx.row_errors.append(
                RowError(
                    column=column,
                    row_index=int(i),
                    trigger="format_error",
                    reason="value is not a parseable date under date_shift",
                )
            )
        if shape is ColumnShape.TIMESTAMP_TZ and isinstance(source_dtype, pd.DatetimeTZDtype):
            # Keep the source unit and zone: a list of timestamps would be inferred as ns.
            df[column] = pd.Series(out, index=col.index, dtype=source_dtype)
        else:
            df[column] = out
        return df, []


def _offsets(
    values: list[Any],
    usable_idx: np.ndarray[Any, Any],
    anchor_col: pd.Series | None,
    ctx: StrategyContext,
    namespace: str,
    min_days: int,
    range_size: int,
) -> list[int]:
    """The keyed day offset of every row (0 for a row not in ``usable_idx``).

    The digest input is each usable row's own value, or its group anchor when ``group_by`` is set.
    """
    # Canonical anchor bytes for usable rows only, in row order, so the
    # batched derivation sees the same sources the old per-row loop did.
    sources: list[bytes] = []
    for i in usable_idx:
        value = values[i]
        if anchor_col is not None:
            group_value = anchor_col.iloc[i]
            if pd.isna(group_value):
                # Null group value: self-anchor on this row's own date
                # value instead (see module docstring's null policy).
                anchor = value
            else:
                # Normalize a numpy scalar (e.g. `numpy.bool_`/`numpy.int64`
                # from a null-free numpy-backed chunk) to its Python
                # equivalent, so the canonical digest input is identical
                # whether the anchor column materialized as a numpy dtype or
                # a Python-scalar object/extension dtype. Without this the
                # SAME anchor value hashes differently across a chunk
                # boundary -- null-free numpy chunk vs nullable full frame
                # (`numpy.bool_(True)` -> b"True" vs `True` -> b"\x01") --
                # breaking the deterministic parity guarantee (Codex R3 P1).
                # Python scalars have no `.item()` and pass
                # through unchanged.
                anchor = group_value.item() if hasattr(group_value, "item") else group_value
        else:
            anchor = value
        sources.append(_canonicalize_source(anchor))

    # One keyed context per column: the HKDF key and the HMAC prefix are
    # constant across rows, so only the per-row finish remains.
    shifts = [0] * len(values)
    if sources:
        digests = DeriveContext.for_column(ctx.mask_key, namespace).derive_sources(
            namespace, sources
        )
        for i, d in zip(usable_idx, digests, strict=True):
            shifts[i] = min_days + (int.from_bytes(d[:8], "big") % range_size)
    return shifts


def _shift_zoned(parsed: pd.Series, shifts: list[int]) -> pd.Series:
    """Move each zoned timestamp by whole calendar days in its own zone, keeping the wall clock.

    Same rule as PostgreSQL ``timestamptz + interval '1 day'`` and Java ``ZonedDateTime.plusDays``:
    add the days to the local time, then re-attach the zone. A fixed 24 hour step would move the
    time of day across a DST change. A local time that does not exist moves forward; one that
    occurs twice keeps the source row's DST flag.
    """
    tz = parsed.dt.tz
    local = parsed.dt.tz_localize(None) + pd.to_timedelta(shifts, unit="D")
    out = local.dt.tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward")
    twice = out.isna() & local.notna()
    if twice.any():
        flags = [bool(parsed.iloc[i].dst()) for i in np.flatnonzero(twice.to_numpy())]
        fixed = local[twice].dt.tz_localize(
            tz, ambiguous=np.array(flags), nonexistent="shift_forward"
        )
        out = out.where(~twice, fixed)
    return out


def _shift_dates(
    col: pd.Series,
    anchor_col: pd.Series | None,
    ctx: StrategyContext,
    namespace: str,
    min_days: int,
    range_size: int,
) -> tuple[list[Any], np.ndarray[Any, Any]]:
    """The typed-date path: ``datetime.date`` plus a timedelta, with no pandas nanosecond bounds.

    A date near 0001 or 9999 shifts like any other. A cell that is not a date, or whose shifted
    date leaves the supported years, is a row error and keeps its source value.
    """
    cells = list(col)
    source_null = col.isna().to_numpy()
    values: list[Any] = [None] * len(cells)
    usable = np.zeros(len(cells), dtype=bool)
    for i, cell in enumerate(cells):
        if source_null[i]:
            continue
        if isinstance(cell, datetime.datetime):
            cell = cell.date()  # a naive timestamp has no digest; its calendar date does
        if isinstance(cell, datetime.date):
            values[i] = cell
            usable[i] = True
    usable_idx = np.flatnonzero(usable)
    shifts = _offsets(values, usable_idx, anchor_col, ctx, namespace, min_days, range_size)
    failed = ~usable & ~source_null
    for i in usable_idx:
        try:
            cells[i] = values[i] + datetime.timedelta(days=shifts[i])
        except OverflowError:
            failed[i] = True
    return cells, np.flatnonzero(failed)


def _shift_rows(
    col: pd.Series,
    fmt: str | None,
    anchor_col: pd.Series | None,
    ctx: StrategyContext,
    namespace: str,
    min_days: int,
    range_size: int,
    shape: ColumnShape | None = None,
) -> tuple[list[Any], np.ndarray[Any, Any]]:
    """Shift every parseable date of ``col``; return ``(cells, format_error_positions)``.

    Positions are within ``col``, so a caller that passed a subset rebases them. A column whose
    plan ``shape`` is native writes dates back as dates (a zoned timestamp as a timestamp), never
    as text.
    """
    if shape is ColumnShape.DATE:
        return _shift_dates(col, anchor_col, ctx, namespace, min_days, range_size)
    parsed = pd.to_datetime(col, format=fmt, errors="coerce")
    zoned = isinstance(parsed.dtype, pd.DatetimeTZDtype)
    unusable = parsed.isna().to_numpy()  # null source OR unparseable date
    source_null = col.isna().to_numpy()

    # `list(col)` (not `col.iloc[i]`) keeps the iteration scalars the old
    # loop used, e.g. a Python int rather than numpy.int64 for numeric dtypes.
    values = list(col)
    shifts = _offsets(
        values, np.flatnonzero(~unusable), anchor_col, ctx, namespace, min_days, range_size
    )

    if zoned:
        shifted = _shift_zoned(parsed, shifts)
    else:
        shifted = parsed + pd.to_timedelta(shifts, unit="D")
    if shape is ColumnShape.TIMESTAMP_TZ:
        formatted = shifted
    else:
        formatted = shifted.dt.strftime(fmt) if fmt else shifted.astype(str)

    # Sprint 2 honesty pack (D7): split `unusable` into source-null (keep
    # original, no error -- unchanged behavior) vs non-null-unparseable
    # (a per-row format error; the original value is still LEFT in the
    # frame per trap T4, the pipeline-level rule guarantees it never
    # reaches the main output).
    #
    # Assemble as a Python list: pandas infers the column dtype from the
    # exact scalar objects, so unusable cells must be the very objects
    # `col.iloc[i]` returns (a boxed or np.where'd source changes the
    # dtype of all-null float32/float16, None, NaT and NA-only columns).
    out = formatted.to_numpy(dtype=object).tolist()
    for i in np.flatnonzero(unusable):
        out[i] = col.iloc[i]
    return out, np.flatnonzero(unusable & ~source_null)
