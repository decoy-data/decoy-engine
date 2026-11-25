"""bucketize strategy (engine-v2 S9): round numeric values into fixed-width bins.

No backend, no determinism keying (deterministic by construction: same value ->
same bucket). Logic carried from V1 `transforms/bucketize.py`: floor(value/width)
* width, formatted per `format` (lower / range / midpoint); width from
`provider_config["width"]` or a `preset` shortcut; non-numeric / NaN fall through
to the original value (per-VALUE fallback, unrelated to the per-COLUMN config
fallback removed below).

Sprint 13 / coercion-13 S3 (2026-07-03, GATE-1 Q4 sibling of the truncate
fail-closed fix): `_resolve_width` returning `None` used to make `run`
`return df, []` (silent passthrough of the whole column unmasked) on an
unresolved `preset` (including the Studio picker's `"(custom)"` sentinel
reaching the engine unresolved) or a non-numeric/non-positive `width`. It now
raises `StrategyError`. `check_bucketize_config` (plan/_checks_bucketize.py)
rejects the same shapes at compile time; this is the defense-in-depth
backstop. That fix closed the per-COLUMN config-level passthrough.

Sprint 2 honesty pack (2026-07-04, D7/D8): the sibling per-VALUE leak
(referenced in the module docstring above and tracked since #13) is closed
here. A non-null cell that fails `pd.to_numeric` coercion used to keep the
ORIGINAL source value in the output -- silent per-row leak, same class as
the config-level one. `run` now records a `RowError` (trigger
"format_error") on `ctx.row_errors` for such cells via `_row_errors.py`'s
shared channel; it does NOT null or rewrite the cell (trap T4) -- the
pipeline-level rule in `execution/_pipeline.py` (D8) guarantees a row with a
recorded error never reaches the main output (it exits via the quarantine
file, which carries originals by design, or the job fails and nothing is
written). Source-null cells are unaffected (null passthrough is not a leak).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pandas as pd
import pyarrow as pa

from decoy_engine import reasons
from decoy_engine.contracts.bucketize_width import resolve_bucketize_width
from decoy_engine.contracts.format_error_reasons import format_error_reason
from decoy_engine.execution._adapter import (
    StrategyContext,
    StrategyOption,
    option,
    provider_config_to_dict,
    require_shape_declared,
)
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._row_errors import RowError
from decoy_engine.generation.pool._events import QualityWarning
from decoy_engine.kernel import integer_width_exit_mask
from decoy_engine.plan._types import ColumnSeed

_FORMATS = frozenset({"lower", "range", "midpoint"})
_NOT_NUMERIC = "value is not numeric under bucketize"


def _out_of_range_mask(nums: pd.Series) -> npt.NDArray[np.bool_]:
    """B2/B3 positions of ``nums`` for an integer width, through the one kernel rule.

    The comparison view is float64 with every missing value as NaN, which the rule never selects.
    """
    view = nums.to_numpy(dtype="float64", na_value=np.nan)
    return np.asarray(integer_width_exit_mask(pa.array(view)).to_numpy(zero_copy_only=False))


def _render_labels(
    nums: pd.Series, width: int | float, fmt: str, *, declared_integer_output: bool
) -> pd.Series:
    """The bucket label of every number in ``nums``, keeping its dtype's missing values.

    Integer width: ``lower`` is an Int64 column (the declared-integer output renders it once
    later). Float width: float labels. Missing positions come back as the dtype's missing marker
    or its string form; the caller restores the source cell there.
    """
    lower_f = np.floor(nums / width) * width
    is_int_width = isinstance(width, int) and not isinstance(width, bool)
    if is_int_width:
        lower = lower_f.astype("Int64")
        upper_excl = lower + int(width)
    else:
        lower = lower_f
        upper_excl = lower + width

    if fmt == "lower":
        formatted = lower.astype(str)
    elif fmt == "range":
        upper = upper_excl - 1 if is_int_width else upper_excl
        formatted = lower.astype(str) + "-" + upper.astype(str)
    else:  # midpoint
        mid = lower_f + width / 2
        if is_int_width and int(width) % 2 == 0:
            mid = mid.astype("Int64")
        formatted = mid.astype(str)

    if declared_integer_output and fmt == "lower" and is_int_width:
        return lower  # F06: stays an integer; the declared formatter renders it once
    return formatted


class BucketizeStrategyHandler:
    """Round numeric values into fixed-width buckets."""

    name: str = "bucketize"
    namespace_required: bool = False
    join_safe: bool = False
    wizard_options: tuple[StrategyOption, ...] = (
        option("width", "int", 10, required=True),
        option("format", "str", "range", choices=tuple(sorted(_FORMATS))),
    )
    offer_in_wizard: bool = True

    def run(
        self,
        df: pd.DataFrame,
        column: str,
        plan: ColumnSeed,
        ctx: StrategyContext,
    ) -> tuple[pd.DataFrame, list[QualityWarning]]:
        cfg = provider_config_to_dict(plan.provider_config)
        require_shape_declared("bucketize", column, ctx)
        width = resolve_bucketize_width(cfg)
        if width is None:
            # Invalid config: fail closed (Sprint 13 GATE-1 Q4). A masking
            # strategy must never silently pass the source column through.
            raise StrategyError(
                code=reasons.runtime.BUCKETIZE_WIDTH_UNRESOLVABLE,
                strategy="bucketize",
                message=(
                    f"column {column!r} uses bucketize but neither a known "
                    "preset nor a resolvable numeric width is configured."
                ),
            )
        fmt = str(cfg.get("format", "lower")).lower()
        if fmt not in _FORMATS:
            fmt = "lower"

        col = df[column]
        nums = pd.to_numeric(col, errors="coerce")
        is_int_width = isinstance(width, int) and not isinstance(width, bool)
        uncoercible = (col.notna() & nums.isna()).to_numpy()  # D7, before any masking
        out_of_range = _out_of_range_mask(nums) if is_int_width else np.zeros(len(nums), dtype=bool)

        if out_of_range.any():
            # B2/B3: mask on a separate series so the label arithmetic and the Int64 cast
            # never see a value they cannot represent; `nums` itself stays untouched.
            labelled = nums.where(~out_of_range)
        elif not is_int_width and pd.api.types.is_integer_dtype(nums.dtype):
            # B4: every integer dtype divides as float64, round-to-nearest (int64[pyarrow]
            # would otherwise divide in Arrow, raise on a large value and quote it).
            labelled = pd.Series(nums.to_numpy(dtype="float64", na_value=np.nan), index=nums.index)
        else:
            labelled = nums
        formatted = _render_labels(
            labelled,
            width,
            fmt,
            declared_integer_output=bool(cfg.get("declared_integer_output")),
        )

        # Sprint 2 honesty pack (D7): a non-null cell that fails numeric coercion is a per-row
        # format error, NOT a silent keep-original; null source cells are not errors. D7 and the
        # B2/B3 range exits are disjoint (an uncoercible cell has no number to be out of range).
        # One record per bad cell, in row order.
        range_reason = format_error_reason("bucketize")
        for i in np.flatnonzero(uncoercible | out_of_range):
            ctx.row_errors.append(
                RowError(
                    column=column,
                    row_index=int(i),
                    trigger="format_error",
                    reason=range_reason if out_of_range[i] else _NOT_NUMERIC,
                )
            )
        # Missing and uncoercible cells keep the source value; a range exit is null (the
        # pipeline drops or quarantines the row, and the bad number is never retained).
        keep_label = nums.notna().to_numpy() | out_of_range
        result = formatted.where(keep_label, col)
        df[column] = result.mask(out_of_range) if out_of_range.any() else result
        return df, []
