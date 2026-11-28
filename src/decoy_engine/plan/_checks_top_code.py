"""Plan-compile check for top_code columns (HC-3b).

Added as its own module to avoid growing plan/_checks.py past its size
ceiling (see the SP-10 comment in tests/sentry/test_module_size.py).

`TopCodeStrategyHandler._resolve_top_bound` (`execution/_strategies/
_top_code.py`) returns `None` -- and the handler then raises `StrategyError`
rather than run -- when `preset` names something not in the known preset
table, or when `cap`/`over_label` is missing, non-numeric, or not a non-empty
string. This module rejects the same shapes at compile time, before any row
is masked, so the operator sees the error at plan-compile rather than at
run. It additionally rejects a malformed `floor`/`under_label` pairing, a
`floor >= cap` range, and a `when`-gated top_code column. The handler
(`_resolve_bottom_bound`) also fails closed on a present-but-invalid floor, so
these are caught at compile for the operator's benefit rather than being the
only backstop -- a config that clearly intended a floor and got the shape wrong
should surface at plan-compile, not at run.

Reuses `_PRESETS` from the handler module as the single source of truth for
known preset names (no duplicated table to drift out of sync).

This module exports exactly one function: `check_top_code_config`.
"""

from __future__ import annotations

import math
from typing import Any

from decoy_engine import reasons
from decoy_engine._config_text import (
    ConfigPosition,
    Name,
    Problem,
    config_refusal,
    config_root_position,
)
from decoy_engine._nested_json import nested_children
from decoy_engine.contracts.bucketize_width import EXACT_INT_BOUND
from decoy_engine.contracts.label_text import is_utf8_text
from decoy_engine.execution._strategies._top_code import _PRESETS
from decoy_engine.plan._errors import PlanCompileError, refusal_error

KNOWN_PRESETS = tuple(sorted(_PRESETS))
_BOUND_TYPE_HINT = (
    "Set a numeric bound (a numeric-looking string does not count; the emitter must "
    "coerce it to a real number)."
)
_BOUND_FINITE_HINT = (
    "A NaN/inf bound never fires its tail comparison, so nothing is generalized and the "
    "column passes through unmasked; set a finite numeric bound."
)
_BOUND_RANGE_HINT = (
    "A bound at or beyond 2**53 cannot be compared exactly against a null-bearing column "
    "(Arrow int64+null widens to float64), so a true tail value can round to the bound and "
    "escape generalization, a leak. Use a bound with magnitude below 2**53."
)
_PRESET_HINT = (
    "An unresolved preset leaves the column unmasked at run; set a known preset or drop "
    "'preset' and set a numeric 'cap' + 'over_label' instead."
)
_OVER_LABEL_HINT = (
    "A numeric cap needs a non-empty 'over_label' that encodes as UTF-8, the aggregate "
    'label for values above cap (e.g. "90+").'
)
_UNDER_LABEL_HINT = (
    "A floor needs a non-empty 'under_label' that encodes as UTF-8, the aggregate label "
    "for values below floor."
)
_FLOOR_GE_CAP_HINT = (
    "floor must be strictly less than cap, or every value falls into one tail or the "
    "other with nothing left in range."
)


def _reject_unusable_bound(value: Any, *, code: str, at: ConfigPosition) -> int | float:
    """Raise PlanCompileError if `value` cannot serve as an EXACT top_code bound;
    otherwise RETURN it narrowed to `int | float`.

    Returning the validated number (rather than `None`) lets the caller bind
    `cap = _reject_unusable_bound(...)` with an honest `int | float` type instead
    of the `Any | None` a bare `pc.get("cap")` carries -- no cast, mypy-clean.

    Rejects, in order: bool/non-numeric; non-finite (NaN/inf, floats only so a
    huge Python int never raises OverflowError in `math.isfinite`); and
    magnitude >= 2**53 (past float64's exact-integer range, where the tail
    comparison silently rounds and a true tail value can escape generalization --
    a PHI leak Codex reproduced). `at` is the bound's position from the config root.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        type_refusal = config_refusal(at, Problem.WRONG_TYPE, got=value, hint=_BOUND_TYPE_HINT)
        raise refusal_error(code, type_refusal)
    if isinstance(value, float) and not math.isfinite(value):
        finite_refusal = config_refusal(at, Problem.NOT_ALLOWED, hint=_BOUND_FINITE_HINT)
        raise refusal_error(code, finite_refusal)
    if abs(value) >= EXACT_INT_BOUND:
        range_refusal = config_refusal(at, Problem.NOT_ALLOWED, hint=_BOUND_RANGE_HINT)
        raise refusal_error(code, range_refusal)
    # Every reject path above raised; the value is a finite in-range number.
    return value


def check_top_code_config(config: dict[str, Any]) -> None:
    """Reject top_code columns whose generalization bound cannot be resolved.

    A column is valid when either:

    1. `preset` is set and is a known preset name (`_PRESETS`); or
    2. `preset` is unset and `cap` is a numeric (`int`/`float`, not `bool`)
       and `over_label` is a non-empty string.

    When `floor` is additionally set (with or without a preset), it must be
    numeric (not `bool`) and paired with a non-empty `under_label`, and the
    effective `floor` must be strictly less than the effective `cap`. A
    `under_label` without a `floor` is rejected (incomplete pair).

    A `nested` column whose child is top_code is rejected outright (top_code is
    not supported as a nested child; see the guard's comment). A `when`-gated
    top_code column is likewise rejected: conditional top-coding skips bound
    validation on a zero match and cannot write its string label back into the
    column's lossless integer dtype (see the guard's comment). Every numeric
    bound (cap, floor) must also have magnitude below 2**53 so the tail
    comparison is exact on a null-bearing column (past that, float64 rounding can
    let a true tail value escape generalization -- a leak).

    Config-only (no profile, no source data): safe to run in both compile
    branches and in `run_config_only_checks`. Validation never mutates
    (per engine rule).

    Args:
        config: Raw pipeline config dict.

    Raises:
        PlanCompileError: the top bound is unresolvable (missing/non-numeric/
            non-finite/>=2**53 cap, or unknown/non-string preset), the bottom
            bound is malformed (bad floor incl. explicit None, floor without
            under_label or vice versa), floor >= cap, top_code is used as a
            nested child, or top_code is combined with `when`.
    """
    tables = config.get("tables", []) if isinstance(config.get("tables"), list) else []
    for table_entry in tables:
        if not isinstance(table_entry, dict):
            continue
        table_name = table_entry.get("name", "?")
        for col_entry in table_entry.get("columns", []) or []:
            if not isinstance(col_entry, dict):
                continue
            col_name = col_entry.get("name", "?")
            pc = col_entry.get("provider_config")
            if not isinstance(pc, dict):
                pc = {}
            where = f"{col_name!r} in table {table_name!r}"

            # Nested (Codex BLOCKER 2/3): a nested column carries its child
            # strategy under provider_config.strategy, so `strategy == "top_code"`
            # never matches it. A top_code nested child is rejected: (a) a per-row
            # format-error RowError is recorded at the FLATTENED-LEAF index, which
            # mis-maps to the wrong OUTER row -- quarantining a clean record while
            # the flagged raw value reaches main output; and (b) the bottom-bound
            # checks below never reach the child config. Fail closed until nested
            # RowError positioning is correct.
            nested_top_code = (
                [c for c in nested_children(pc) if c.strategy == "top_code"]
                if col_entry.get("strategy") == "nested"
                else []
            )
            if nested_top_code:
                raise PlanCompileError(
                    code=reasons.plan.TOP_CODE_UNSUPPORTED_IN_NESTED,
                    path=(
                        f"tables.{table_name}.columns.{col_name}."
                        f"{nested_top_code[0].config_path}.strategy"
                    ),
                    message=(
                        f"top_code column {where} sets a `nested` strategy with a "
                        "top_code child. top_code is not supported as a nested "
                        "child: a per-row format error is recorded at the "
                        "flattened-leaf position (mis-mapping to the wrong outer "
                        "row, so a flagged raw value can reach main output), and the "
                        "bottom-bound compile checks do not reach the child. Move "
                        "top_code to a top-level column."
                    ),
                )

            if col_entry.get("strategy") != "top_code":
                continue

            # `when` + top_code (Codex R3 HIGH x2): fail closed. Conditional
            # top-coding is unsound on two fronts and neither is worth the
            # machinery for a niche shape. (1) A zero-match `when` skips the
            # handler entirely, so a deserialized/direct Plan with a malformed
            # bound is never validated at run and the column passes through
            # unmasked -- the compile check here is the ONLY backstop, and a
            # gate that the handler can silently skip is not a backstop. (2) The
            # when-gate writes the aggregate label (a str) back into the gated
            # subset; a top_code column ingests as nullable Int64 (lossless FK-
            # safe ingest, so large in-range ints stay exact), and writing "90+"
            # into an Int64 slot raises `ValueError: invalid literal for int()`.
            # top-coding is a whole-column generalization; a partial one is not a
            # supported shape. Mirrors date_shift's `when`+group_by rejection.
            when_val = col_entry.get("when")
            if isinstance(when_val, str) and when_val.strip():
                raise PlanCompileError(
                    code=reasons.plan.TOP_CODE_WITH_WHEN_UNSUPPORTED,
                    path=f"tables.{table_name}.columns.{col_name}.when",
                    message=(
                        f"top_code column {where} combines `when` with top_code. "
                        "Conditional top-coding is not supported: a zero-match "
                        "`when` skips bound validation (unmasked passthrough), and "
                        "the aggregate label cannot be written back into the "
                        "column's lossless integer dtype. top-coding generalizes "
                        "the whole column; remove `when` from this column."
                    ),
                )

            preset = pc.get("preset")
            if preset is not None:
                # `preset` must be a hashable str before the membership test: a
                # list/dict preset would raise `TypeError: unhashable type`.
                if not isinstance(preset, str) or preset not in _PRESETS:
                    preset_refusal = config_refusal(
                        config_root_position(
                            "tables",
                            Name(table_name),
                            "columns",
                            Name(col_name),
                            "provider_config",
                            "preset",
                        ),
                        Problem.NOT_FOUND,
                        choices=KNOWN_PRESETS,
                        hint=_PRESET_HINT,
                    )
                    raise refusal_error(reasons.plan.TOP_CODE_BOUNDS_UNRESOLVABLE, preset_refusal)
                cap: int | float = _PRESETS[preset]["cap"]
            else:
                cap = _reject_unusable_bound(
                    pc.get("cap"),
                    code=reasons.plan.TOP_CODE_BOUNDS_UNRESOLVABLE,
                    at=config_root_position(
                        "tables",
                        Name(table_name),
                        "columns",
                        Name(col_name),
                        "provider_config",
                        "cap",
                    ),
                )
                over_label = pc.get("over_label")
                if not is_utf8_text(over_label) or not over_label:
                    over_refusal = config_refusal(
                        config_root_position(
                            "tables",
                            Name(table_name),
                            "columns",
                            Name(col_name),
                            "provider_config",
                            "over_label",
                        ),
                        Problem.MISSING,
                        hint=_OVER_LABEL_HINT,
                    )
                    raise refusal_error(reasons.plan.TOP_CODE_MISSING_OVER_LABEL, over_refusal)

            # Absence keyed on `"floor" not in pc`, NOT `floor is None`: an
            # explicit `floor: None` is a present-but-malformed bound (operator
            # typo / templating miss), so it must fail closed via
            # `_reject_unusable_bound(None, ...)` below rather than read as "no
            # bottom tail" and silently disable bottom-coding (Codex R3 HIGH --
            # `.get` cannot tell absent from explicit-None). Mirrors the handler.
            if "floor" not in pc:
                # under_label without floor (Codex MEDIUM 3): an incomplete
                # bottom-bound pair silently disables the bottom tail. If the
                # operator supplied under_label they intended a floor; reject
                # rather than silently ignore it.
                if pc.get("under_label") is not None:
                    raise PlanCompileError(
                        code=reasons.plan.TOP_CODE_UNDER_LABEL_WITHOUT_FLOOR,
                        path=(
                            f"tables.{table_name}.columns.{col_name}.provider_config.under_label"
                        ),
                        message=(
                            f"top_code column {where} sets 'under_label' but no "
                            "'floor'. The bottom tail is never generalized without a "
                            "floor; set 'floor' or remove 'under_label'."
                        ),
                    )
                continue
            floor = _reject_unusable_bound(
                pc.get("floor"),
                code=reasons.plan.TOP_CODE_INVALID_FLOOR,
                at=config_root_position(
                    "tables",
                    Name(table_name),
                    "columns",
                    Name(col_name),
                    "provider_config",
                    "floor",
                ),
            )
            under_label = pc.get("under_label")
            if not is_utf8_text(under_label) or not under_label:
                under_refusal = config_refusal(
                    config_root_position(
                        "tables",
                        Name(table_name),
                        "columns",
                        Name(col_name),
                        "provider_config",
                        "under_label",
                    ),
                    Problem.MISSING,
                    hint=_UNDER_LABEL_HINT,
                )
                raise refusal_error(reasons.plan.TOP_CODE_MISSING_UNDER_LABEL, under_refusal)
            if floor >= cap:
                order_refusal = config_refusal(
                    config_root_position(
                        "tables",
                        Name(table_name),
                        "columns",
                        Name(col_name),
                        "provider_config",
                        "floor",
                    ),
                    Problem.NOT_ALLOWED,
                    hint=_FLOOR_GE_CAP_HINT,
                )
                raise refusal_error(reasons.plan.TOP_CODE_FLOOR_GE_CAP, order_refusal)
