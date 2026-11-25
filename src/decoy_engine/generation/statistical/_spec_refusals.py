"""The refusals `load_spec` raises for a snapshot column: withheld values and the DP carrier.

Split from `_spec` for size. Each function only builds the `Refusal`; `load_spec` raises it with
the registered code, so this module does not depend on the spec's error class.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from decoy_engine import reasons
from decoy_engine._config_text import (
    ConfigPosition,
    Name,
    Problem,
    QuotedName,
    Refusal,
    config_position,
    config_refusal,
)
from decoy_engine.profiling import (
    POLICY_RAW,
    REDACTED_COLUMNS_KEY,
    REDACTED_POLICIES,
    VALUE_POLICY_KEY,
)


def _snapshot_declares_flag(
    snap: Mapping[str, Any], col_entry: Mapping[str, Any], source_column: str
) -> bool:
    """Does a recognizable DP artifact declare this column a `flag` release --
    in EITHER of the two places it records a carrier? The `columns` block entry
    (`col_entry`) and the authoritative `dp.column_schema` entry must agree for a
    genuine release, but the unverified-refusal below must fire if the column is
    a flag by EITHER, so zeroing only the columns-block carrier (which
    `verify_dp_snapshots` never gets to catch, because an undeclared-DP pipeline
    early-returns) cannot slip a bool column onto the legacy `str()` path. Reading
    the carrier to REFUSE is always safe; the non-inference rule forbids only
    reading it to GRANT an exemption."""
    if col_entry.get("carrier") == "flag":
        return True
    dp_block = snap.get("dp")
    schema = dp_block.get("column_schema") if isinstance(dp_block, Mapping) else None
    entry = schema.get(source_column) if isinstance(schema, Mapping) else None
    return isinstance(entry, Mapping) and entry.get("carrier") == "flag"


def withheld_values_refusal(
    name: Any,
    snap: Mapping[str, Any],
    *,
    source_column: str,
    kind: Any,
    dp_verified: bool,
    condition_on: Any,
    holds_numeric_shape: bool = False,
) -> Refusal | None:
    """The refusal for a column that would sample categories a redacted fit snapshot withheld.

    Only the marker is read, and only to refuse: `value_policy: "raw"` removes this refusal
    and grants nothing, so the `allow_real_categories` opt-in still applies after it. A
    snapshot with neither marker key is a legacy file and keeps its old behavior; the
    placeholder string a profile uses for withheld text is never a signal, because a raw or
    legacy snapshot can hold it as a real category. Numeric and datetime columns read
    coarse bins and years that carry no cell value, so they reach it only through a restored
    `quantile_grid` or `exact_values` block (`holds_numeric_shape`).
    """
    if VALUE_POLICY_KEY not in snap and REDACTED_COLUMNS_KEY not in snap:
        return None
    samples_values = (
        (kind == "categorical" and not dp_verified)
        or condition_on is not None
        or holds_numeric_shape
    )
    if not samples_values:
        return None
    policy = snap.get(VALUE_POLICY_KEY)
    listed = snap.get(REDACTED_COLUMNS_KEY)
    well_formed = (
        isinstance(policy, str) and (policy in REDACTED_POLICIES or policy == POLICY_RAW)
    ) and (isinstance(listed, (list, tuple)) and all(isinstance(c, str) for c in listed))
    if well_formed and policy == POLICY_RAW:
        return None
    withheld_column = source_column
    if well_formed:
        named = (source_column,) if condition_on is None else (source_column, condition_on)
        hit = [c for c in named if c in (listed or ())]
        if not hit:
            return None
        withheld_column = hit[0]
    at_column = config_position("statistical", Name(name))
    # The output column and the one whose values were withheld, each once: they differ when the
    # output column is renamed or the withheld side is the `condition_on` column.
    shown = [name] if withheld_column == name else [name, withheld_column]
    if kind == "numeric" and condition_on is None:
        return config_refusal(
            at_column,
            Problem.NOT_ALLOWED,
            names=tuple(QuotedName(n) for n in shown),
            hint=(
                "The snapshot withheld the real values this column needs, so there "
                "are no values to sample. Use a faker or pattern generator for this "
                "column, or re-fit with `--include-values` (the snapshot then holds "
                "the number shape)"
            ),
        )
    return config_refusal(
        at_column,
        Problem.NOT_ALLOWED,
        names=tuple(QuotedName(n) for n in shown),
        hint=(
            "The snapshot withheld the real values this column needs (a sensitive "
            "column, one with too few rows to release values, or a value-policy "
            "marker that is missing or malformed), so there are no values to sample. "
            "Use a faker or pattern generator for this column, or re-fit with "
            "`--include-values` and set `allow_real_categories: true` (the snapshot "
            "then holds real values)"
        ),
    )


def dp_carrier_refusal(
    snap: Mapping[str, Any],
    col_entry: Mapping[str, Any],
    source_column: str,
    at_source: ConfigPosition,
    *,
    dp_verified: bool,
) -> tuple[str | None, tuple[str, Refusal] | None]:
    """`(carrier, None)` for a usable column, or `(None, (code, refusal))` for one to refuse.

    The DP-v3 carrier is mandatory and strictly validated only for a column the compiler verified
    as a genuine DP release (`dp_verified` is the compiler's verdict, never inferred from the
    snapshot's own `carrier` key). An ordinary `distribution-snapshot/v1` column keeps
    `carrier=None`, the legacy sampling path, even with a stray `carrier` key.

    A recognizable DP artifact (it carries a `dp` block) whose column is a `flag` release but was
    not verified (the pipeline declares no `global_settings.dp`) is refused: the flag decoder
    would not engage and the sampler would emit 'true'/'false' strings against a `bool` dtype.
    The flag is read from either carrier location, so a split declaration cannot bypass this.
    Reading the carrier to refuse is safe; the non-inference rule forbids only reading it to grant.
    """
    if dp_verified:
        carrier = col_entry.get("carrier")
        if carrier in ("number", "flag", "text"):
            return carrier, None
        return None, (
            reasons.plan.STATISTICAL_DP_CARRIER_INVALID,
            config_refusal(
                at_source,
                Problem.MISMATCH,
                hint=(
                    "The source column is a verified DP release but records a "
                    "carrier that is not one of 'number', 'flag' or 'text'"
                ),
            ),
        )
    if isinstance(snap.get("dp"), Mapping) and _snapshot_declares_flag(
        snap, col_entry, source_column
    ):
        return None, (
            reasons.plan.STATISTICAL_FLAG_REQUIRES_DP_DECLARATION,
            config_refusal(
                at_source,
                Problem.NOT_ALLOWED,
                hint=(
                    "The source column is a DP `flag` (bool-domain) release (the snapshot "
                    "carries a `dp` block), but this pipeline does not declare "
                    "`global_settings.dp`, so the release is not verified and the flag "
                    "decoder does not engage: the sampler would emit 'true'/'false' "
                    "strings against the artifact's `bool` dtype. Declare "
                    "`global_settings.dp` so this column is verified and generated as bool"
                ),
            ),
        )
    return None, None
