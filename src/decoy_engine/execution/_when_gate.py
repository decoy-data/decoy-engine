"""MG-3 / M3 (2026-05-31): pre-strategy `when:` predicate gate.

Two thin wrappers that evaluate `ColumnSeed.when` against the
column's frame and dispatch the underlying strategy ONLY to the rows
where the predicate is True. Rows where the predicate is False
passthrough untouched.

`run_with_when_gate` is used by the pandas execution adapter.

Security posture (reuses the Dennis C1 patch on `_transforms.py`):
the eval call pins `engine="numexpr"` AND clamps both `local_dict`
and `global_dict` to empty. That blocks `@var`-style scope walks
that would otherwise reach module-top imports (e.g.
`@pd.compat.os.system(...)`). The numexpr backend never falls back
to Python eval, so an undefined name raises
`UndefinedVariableError` instead of executing.

Composition note: `when:` runs BEFORE the strategy. If the underlying
strategy is itself wrapping behavior (e.g. `nested` in MG-3 / M2),
`when:` filters the rows FIRST and then `nested` walks the surviving
rows' JSON. The order is locked in the runner gate (here) and the
combined cell in `tests/integration/test_when_plus_nested.py` pins
that contract.
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from decoy_engine import reasons
from decoy_engine.errors import ValidationError
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._exact_int_sources import gated_context, selected_positions
from decoy_engine.execution._gated_string_guard import (
    reject_gated_string_on_numeric,
    widen_numeric_target_for_strings,
)
from decoy_engine.execution._row_errors import RowError
from decoy_engine.expressions._when_parser import (
    Scalar,
    parse_when,
    parse_when_cached,
    when_column_refs,
    when_literals_by_ref,
)

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from decoy_engine.execution._adapter import (
        StrategyContext,
        StrategyHandler,
    )
    from decoy_engine.generation.pool._events import QualityWarning
    from decoy_engine.plan._types import ColumnSeed


def _remap_gated_row_errors(
    ctx: StrategyContext,
    err_start: int,
    full_positions: Sequence[int],
) -> None:
    """Rewrite subset-relative RowError indices to full-table positions.

    BLOCKER B1 (dennis review 2026-07-04): the `when:` gate hands the
    handler a SUBSET frame (`df.loc[mask]` / `frame.filter(mask)`), so the
    handler records ``RowError.row_index`` positional in that subset. The
    pipeline + quarantine machinery (`_pipeline.py` D8, `quarantine.py` D9)
    consume ``row_index`` as a FULL-TABLE position. Left unremapped, a gated
    format/mask error quarantines/deletes the WRONG row and ships the raw
    source value of the real bad row -- exactly the silent leak this sprint
    exists to kill.

    Only the errors appended during THIS handler call (indices
    ``err_start..``) are remapped; ``RowError`` is frozen, so each entry is
    replaced in place with a copy carrying the full-table index. Preserving
    the sink's identity is required (the adapter drains it by reference,
    trap T6). ``full_positions[k]`` is the full-table row position of the
    k-th gated (mask-True) row, in mask order.
    """
    for j in range(err_start, len(ctx.row_errors)):
        e = ctx.row_errors[j]
        ctx.row_errors[j] = RowError(
            column=e.column,
            row_index=int(full_positions[e.row_index]),
            trigger=e.trigger,
            reason=e.reason,
        )


def _require_closed_grammar(expression: object, strategy: str, column: str | None) -> None:
    """Backstop for callers that reach the evaluator without a compiled Plan.

    `parse_when` is the one definition of an acceptable predicate. Compile and plan-level
    validation reject first; this catches a hand-built `ColumnSeed` or a direct helper call.
    """
    try:
        if isinstance(expression, str):
            parse_when_cached(expression)
        else:
            parse_when(expression)  # type: ignore[arg-type]
        return
    except ValidationError:
        pass
    # Raised outside the handler so `__context__` stays empty.
    raise StrategyError(
        code=reasons.runtime.WHEN_OUTSIDE_CLOSED_GRAMMAR,
        strategy=strategy,
        message=f"when expression on column {column!r} is outside the closed grammar",
    )


# The integers a float64 holds exactly. A value or integer literal outside it is compared as a
# Python int, so no route rounds it.
_EXACT_FLOAT_INT = 2**53


def _exact_column(col: pd.Series, literals: Sequence[Scalar]) -> pd.Series:
    """One referenced column as the evaluator reads it.

    An integer column (a NumPy integer or a pandas nullable `Int`/`UInt`) is compared as Python
    integers when a value, an integer literal or any float literal could not be handled exactly
    as float64; a blank is `NaN`, never `pd.NA`. Otherwise a nullable integer column becomes
    float64 with `NaN`, which is exact in range. Every other column is returned as is.
    """
    if not pd.api.types.is_integer_dtype(col.dtype):
        return col
    wide = any(
        isinstance(x, float) or (isinstance(x, int) and abs(x) > _EXACT_FLOAT_INT)
        for x in literals
        if not isinstance(x, bool)
    )
    if not wide and len(col):
        low, high = col.min(), col.max()  # blanks are skipped; all blank gives `pd.NA`
        # Python ints: NumPy would compare a uint64 with a negative bound through float64.
        wide = low is not pd.NA and (int(low) < -_EXACT_FLOAT_INT or int(high) > _EXACT_FLOAT_INT)
    if wide:
        values = col.to_numpy(dtype=object, na_value=np.nan)
        return pd.Series(values, index=col.index, name=col.name, dtype=object)
    if isinstance(col.dtype, np.dtype):
        return col
    return pd.Series(col.to_numpy(dtype=np.float64, na_value=np.nan), index=col.index)


def when_eval_frame(
    frame: pd.DataFrame, refs: Sequence[str], literals: Mapping[str, Sequence[Scalar]]
) -> pd.DataFrame:
    """The frame a predicate is evaluated on, built after ingestion on every route.

    One rule for every ingestion dtype: a blank is `NaN` (so `!=`, `not in` and a `not` around a
    comparison select it, and nothing else does), and integers compare exactly. Only the columns
    the predicate reads are copied.
    """
    data: dict[str, pd.Series] = {}
    for name in refs:
        if name not in frame.columns:
            continue
        col = frame[name]
        if not isinstance(col, pd.Series):  # duplicate column labels: let pandas report them
            return frame
        data[name] = _exact_column(col, literals.get(name, ()))
    return pd.DataFrame(data, index=frame.index)


def _eval_predicate(
    pdf: pd.DataFrame,
    expression: str,
    strategy: str,
    *,
    column: str | None = None,
) -> pd.Series[bool]:
    """Shared numexpr-pinned, scope-clamped predicate eval.

    Returns the boolean mask Series. Raises `StrategyError` with one
    of four typed codes on failure:
      - `when_outside_closed_grammar` if the expression is not in the
        closed `when` grammar (checked before pandas sees it, so the
        scope clamps below are a second line of defense, not the first)
      - `numexpr_required` if numexpr is not installed
      - `when_expression_error` if the expression raises
      - `when_expression_not_boolean` if the result is not a bool
        Series.

    The strategy name is threaded through so the runner can attribute
    the failure when it bubbles up. No message or exception chain carries
    the expression: a predicate can embed literal data values.
    """
    _require_closed_grammar(expression, strategy, column)
    failed = False
    try:
        # Audit L1 (2026-06-12): same fallback surfacing as
        # execution/_transforms._eval_clamped -- pandas silently drops
        # to the python engine on extension-array dtypes with only an
        # unmonitored RuntimeWarning.
        with warnings.catch_warnings(record=True) as _caught:
            warnings.simplefilter("always", RuntimeWarning)
            ast = parse_when_cached(expression)
            frame = when_eval_frame(pdf, when_column_refs(ast), when_literals_by_ref(ast))
            # numexpr has no object arithmetic: exact integers use pandas' own Python engine,
            # under the same empty scopes and the same closed grammar.
            exact = any(
                frame[c].dtype == object and pd.api.types.is_integer_dtype(pdf[c].dtype)
                for c in frame.columns
                if c in pdf.columns and isinstance(frame[c], pd.Series)
            )
            mask = frame.eval(
                expression,
                engine="python" if exact else "numexpr",
                local_dict={},
                global_dict={},
            )
        for _w in _caught:
            if issubclass(_w.category, RuntimeWarning):
                _log.warning(
                    # Never the expression: a predicate can embed literal data values.
                    "when predicate on column %r (strategy %s): numexpr fell back to the "
                    "python engine (%s)",
                    column,
                    strategy,
                    _w.message,
                )
    except ImportError as exc:
        raise StrategyError(
            code=reasons.runtime.NUMEXPR_REQUIRED,
            strategy=strategy,
            message=("when: requires numexpr; install with: pip install numexpr"),
        ) from exc
    except Exception as exc:
        # pandas' own errors quote the predicate (a bad datetime literal, an undefined name).
        # Only the class name is kept, at debug level, to tell failures apart; the error itself
        # is raised below, outside the handler, so it carries no cause and no context.
        _log.debug(
            "when predicate on column %r (strategy %s): evaluation failed (%s)",
            column,
            strategy,
            type(exc).__name__,
        )
        failed = True
    if failed:
        raise StrategyError(
            code=reasons.runtime.WHEN_EXPRESSION_ERROR,
            strategy=strategy,
            message=(
                f"when expression on column {column!r} failed to evaluate; "
                "check column names + comparison syntax"
            ),
        )

    # QA-3 F4 (2026-05-31): accept pandas nullable BooleanDtype too.
    # The pre-fix check `mask.dtype != bool` rejected `pd.BooleanDtype()`
    # which arises naturally from Arrow-backed columns and from any
    # boolean expression over a column with NaN. `is_bool_dtype` covers
    # both numpy bool and pandas nullable BooleanDtype.
    if not isinstance(mask, pd.Series) or not pd.api.types.is_bool_dtype(mask.dtype):
        raise StrategyError(
            code=reasons.runtime.WHEN_EXPRESSION_NOT_BOOLEAN,
            strategy=strategy,
            message=(
                f"when expression on column {column!r} did not produce a "
                f"boolean Series (got {type(mask).__name__}"
                + (f", dtype={mask.dtype}" if isinstance(mask, pd.Series) else "")
                + ")"
            ),
        )
    return mask


def run_with_when_gate(
    handler: StrategyHandler,
    df: pd.DataFrame,
    column: str,
    plan: ColumnSeed,
    ctx: StrategyContext,
) -> tuple[pd.DataFrame, list[QualityWarning]]:
    """Invoke `handler.run(...)` directly when `plan.when` is None.

    When `plan.when` is set, evaluate the predicate on `df`, run the
    handler on the matching subset, and stitch the result back into
    `df` at those row positions. Rows that do not match are left
    untouched.

    Raises `StrategyError` (code one of: ``numexpr_required``,
    ``when_expression_error``, ``when_expression_not_boolean``) when
    the predicate cannot be evaluated or does not return a boolean
    Series. Bad-expression failure is fatal: the operator should see
    the typed error and fix the plan rather than silently
    passing-through a misconfigured gate.
    """
    if plan.when is None:
        return handler.run(df, column, plan, ctx)

    # Codex P2 FAIL-CLOSED VALIDATION BYPASSED BY A ZERO-MATCH `when` GATE
    # remediation: a handler's own fail-closed preflight (e.g. CodeSetHandler
    # loading/validating its corpus) normally runs inside `handler.run()`,
    # which the `not mask.any()` short-circuit below never reaches. That let
    # a column referencing a missing/invalid corpus succeed silently
    # whenever its `when:` predicate happened to match zero rows. A handler
    # that needs config/data validated regardless of match count exposes an
    # optional `preflight(plan, ctx) -> None` method; call it unconditionally
    # here, BEFORE the short-circuit, so it always runs while the handler's
    # own `run()` (reached only on a non-empty match) still does the real
    # per-row work and evidence stamping unchanged.
    preflight = getattr(handler, "preflight", None)
    if preflight is not None:
        preflight(plan, ctx)

    mask = _eval_predicate(df, plan.when, plan.strategy, column=column)

    if not mask.any():
        return df, []

    positions = selected_positions(mask)
    sub_df = df.loc[mask].copy()
    err_start = len(ctx.row_errors)
    sub_df, warnings = handler.run(sub_df, column, plan, gated_context(ctx, column, positions))
    # B1: remap subset-relative row-error indices to full-table positions
    # BEFORE they leave the gate (see _remap_gated_row_errors). The k-th
    # mask-True row's full-table position is positions[k], and the handler
    # records positions 0..len(sub_df)-1 into the subset in the same order
    # (our row-error producers preserve row order).
    if len(ctx.row_errors) > err_start:
        # `.tolist()` (only on the rare error path) gives a plain Sequence.
        _remap_gated_row_errors(ctx, err_start, positions.tolist())
    # Stitch every column the handler WROTE back into the full frame for the
    # selected rows, not just the dispatch `column`. A multi-column handler
    # (joint_mask writes its whole `columns` config in one pass) declares them
    # via `gated_output_columns`; a single-column handler leaves `out_cols` as
    # just the dispatch column, byte-identical to the prior single-column write.
    # Copying only the dispatch column left the handler's OTHER outputs at their
    # source value for the gated rows (a silent partial mask).
    for out_col in _gated_output_columns(handler, plan, column):
        if out_col not in sub_df.columns:
            continue
        if out_col in df.columns:  # a handler may create a new column (e.g. group_key)
            reject_gated_string_on_numeric(
                df[out_col],
                sub_df[out_col],
                mask,
                table=getattr(ctx, "current_table", ""),  # test doubles may omit it
                column=out_col,
                strategy=plan.strategy,
            )
            widen_numeric_target_for_strings(df, out_col, sub_df[out_col])
        # Index-aligned: sub_df carries the gated rows' source index labels, so
        # each retained row writes back to its own row in the full frame.
        df.loc[mask, out_col] = sub_df[out_col]
    return df, warnings


def _gated_output_columns(
    handler: StrategyHandler, plan: ColumnSeed, column: str
) -> tuple[str, ...]:
    """The columns `run_with_when_gate` must stitch back for the gated rows.

    The dispatch `column` plus any extra outputs a multi-column handler declares
    through an optional `gated_output_columns(plan) -> tuple[str, ...]` method
    (duck-typed like `preflight`). A handler without that method writes only its
    dispatch column, so the result is `(column,)` -- the pre-fix behavior. The
    dispatch column leads and duplicates are dropped while order is preserved, so
    the single-column path stays byte-identical.
    """
    hook = getattr(handler, "gated_output_columns", None)
    declared = tuple(hook(plan)) if hook is not None else ()
    out: list[str] = []
    for col in (column, *declared):
        if col not in out:
            out.append(col)
    return tuple(out)
