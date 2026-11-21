"""``statistical`` generate-column dispatch, split out of ``synthesize.py``.

Module-size decomposition (tests/sentry/test_module_size.py ALLOWLIST):
``synthesize.py``'s own docstring has flagged the `statistical`/`derived`/
`formula` per-type dispatch branches as the standing decomposition target
since DPS Scope B (2026-07-22); this module carries the `statistical`
branch out (with the per-table fidelity warn-gate), mirroring the existing `transforms/derived_aggregate.py` split
the same allowlist entry names as precedent.

Behavior is unchanged: this is a pure code move, not a rewrite.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any

import pyarrow as pa

from decoy_engine import reasons
from decoy_engine.generation.kinds import (
    cast_output_columns,
    conditional_tables,
    lookup_digests,
    output_types,
)
from decoy_engine.generation.pool import DetailValue, QualityWarning, emit_generation_warning
from decoy_engine.generation.statistical import (
    StatisticalSpec,
    conditional_fallback_counts,
    fallback_counts,
)
from decoy_engine.generators.derivation import GenDeriveContext

_log = logging.getLogger(__name__)


def statistical_generate(
    col: dict[str, Any],
    n: int,
    seed: int,
    derive_key: Any,
    generated: dict[str, list[Any]],
    table_name: str,
    statistical_specs: dict[tuple[str, str], StatisticalSpec],
) -> list[Any]:
    """WS3 statistical synthesis: sample from a distribution-snapshot/v1
    artifact (see generation/statistical for the methodology + privacy
    gate). ADDITIVE generator type -- the existing types stay
    parity-frozen to V1. `generated` carries the table's already-built
    columns so `condition_on` can read its conditioning sibling
    (declared-order sequential conditional sampling).

    DPS Scope B (guide section 4.8): the spec comes from the Plan's
    already-validated, already-pinned ``statistical_specs`` mapping, keyed
    by ``(table_name, column_name)`` -- this function never opens a
    snapshot path itself. The mapping is built once by ``generate_tables``
    from ``GenerationPlan.statistical_specs``, which `compile_plan` froze
    from the exact bytes it read at compile time (guide section 4.7),
    closing the TOCTOU window a raw ``load_spec(col)`` call would reopen.
    """
    from decoy_engine.generation.statistical import sample_column
    from decoy_engine.generation.statistical._spec import StatisticalSpecError

    col_name = str(col.get("name"))
    spec = statistical_specs.get((table_name, col_name))
    if spec is None:
        raise StatisticalSpecError(
            code=reasons.plan.STATISTICAL_SPEC_NOT_PINNED,
            message=(
                f"statistical column {col_name!r} in table {table_name!r} has no pinned "
                "spec in this Plan's GenerationPlan. This should be unreachable through "
                "compile_plan -- every type: statistical column that compiles "
                "successfully is pinned."
            ),
        )
    parent_values: list[Any] | None = None
    if spec.condition_on is not None:
        parent_values = generated.get(spec.condition_on)
        if parent_values is None:
            raise StatisticalSpecError(
                code=reasons.plan.STATISTICAL_CONDITION_COLUMN_UNAVAILABLE,
                message=(
                    f"statistical column {spec.column!r} conditions on "
                    f"{spec.condition_on!r}, which is not generated yet. Declare "
                    f"{spec.condition_on!r} BEFORE {spec.column!r} in generate_columns."
                ),
            )
    # Reuse the Plan's already-pinned digest (guide section 4.7/4.8, defect
    # F4) instead of letting the fingerprint step reopen snapshot_file.
    digest = f"sha256:{spec.snapshot_digest}" if spec.snapshot_digest else None
    col_seed = GenDeriveContext.for_column(
        derive_key=derive_key,
        column_config=col,
        fallback_seed=seed,
        content_digests={("statistical", "snapshot_file"): digest} if digest else None,
    ).base_int("np")
    return sample_column(spec, n, col_seed=col_seed, parent_values=parent_values)


def arrow_table(
    data: Mapping[str, list[Any]],
    *,
    table_name: str,
    statistical_specs: Mapping[tuple[str, str], StatisticalSpec],
    columns: Sequence[Mapping[str, Any]] | None = None,
    parent_types: Mapping[str, pa.DataType] | None = None,
    text_columns: Collection[str] = (),
) -> pa.Table:
    """The table for `data`, with each fitted statistical column typed by its spec.

    A column of `columns` that declares an `output_type` is cast to it here (the one whole-table
    cast site; `_streamed._table_batches` is the batch one) and typed by its compiled Arrow type.
    A column named in `parent_types` (an `inherit` copy) is built with its parent column's type.

    Inference over drawn values would give `null` to a fitted column whose rows are all None
    (a small table, a narrow window) and `int64` to the same column in a full run, so the type
    comes from the spec; an all-null or decimal copy would likewise infer another type than its
    parent's. Every other column keeps Arrow's inference. Runs after the generic
    `null_probability` post-pass, so a column nulled to the last row keeps its type too. A column
    of `text_columns` (a provider column, or a reference to one) is text for the same reason.
    """
    from decoy_engine.generation.statistical import cell_format_arrow_type

    declared = output_types(columns)
    data = cast_output_columns(dict(data), declared, table_name=table_name)
    arrays: dict[str, Any] = {}
    for name, values in data.items():
        spec = statistical_specs.get((table_name, name))
        if name in declared:
            arrays[name] = pa.array(values, type=declared[name].arrow_type)
        elif parent_types and name in parent_types:
            arrays[name] = pa.array(values, type=parent_types[name])
        elif name in text_columns:
            arrays[name] = pa.array(values, type=pa.string())
        elif spec is not None and spec.cell_format is not None:
            arrays[name] = pa.array(values, type=cell_format_arrow_type(spec))
        else:
            arrays[name] = values
    return pa.table(arrays)


def warn_on_table_fidelity(
    config: dict[str, Any],
    generate_columns: list[dict[str, Any]],
    data: dict[str, list[Any]],
    *,
    table_name: str,
    statistical_specs: dict[tuple[str, str], StatisticalSpec],
    snapshot_index_for_column: dict[tuple[str, str], int],
    snapshot_artifacts: list[dict[str, Any]],
    on_warning: Callable[[QualityWarning], None] | None,
) -> None:
    """Generation-time fidelity warn-gate for one finished table (deferred follow-up 5,
    2026-06-12): score statistical columns against their source snapshot and warn below
    global_settings.fidelity_warn_threshold. Warn-only; output bytes are untouched. Lazy import
    mirrors the `statistical` dispatch so non-statistical configs never pay it."""
    if not any(c.get("type") == "statistical" for c in generate_columns):
        return
    from decoy_engine.generation._fidelity_gate import (
        fidelity_warn_threshold,
        warn_on_low_fidelity,
    )

    warn_on_low_fidelity(
        generate_columns,
        data,
        table_name=table_name,
        threshold=fidelity_warn_threshold(config),
        statistical_specs=statistical_specs,
        snapshot_index_for_column=snapshot_index_for_column,
        snapshot_artifacts=snapshot_artifacts,
        on_warning=on_warning,
    )


def null_seed_digests(
    col: Mapping[str, Any],
    table_name: str,
    pinned: bool,
    statistical_specs: Mapping[tuple[str, str], StatisticalSpec] | None,
    reference_fanouts: Mapping[tuple[str, str], Any] | None,
    lookup_lists: Mapping[tuple[str, str], Any] | None,
) -> dict[tuple[str, str], str] | None:
    """The content digests the null mask's seed derivation takes instead of reopening a file.

    Pinned plans store `snapshot_file` as `sha256:<digest>`, not a path. Passing the digest keeps
    `for_column` from trying to open that string as a file. The ordinary path gets None and
    derives the null seed exactly as before.
    """
    key = (table_name, str(col.get("name")))
    kind = col.get("type")
    spec = (statistical_specs or {}).get(key)
    digests: dict[tuple[str, str], str] | None = None
    if pinned and kind == "statistical" and spec is not None and spec.snapshot_digest:
        digests = {("statistical", "snapshot_file"): f"sha256:{spec.snapshot_digest}"}
    if kind == "reference" and col.get("distribution") == "fitted":
        # The null mask derives its seed through `for_column` too; the pinned digest keeps
        # it from reopening `snapshot_file`. A missing spec already raised in `_reference`.
        fanout = (reference_fanouts or {}).get(key)
        digests = {("reference", "snapshot_file"): fanout.seed_digest} if fanout else None
    elif kind == "lookup":
        digests = lookup_digests(col, (lookup_lists or {}).get(key))
    return digests


def warn_on_unseen_parents(
    col: dict[str, Any],
    n: int,
    data: dict[str, list[Any]],
    *,
    table_name: str,
    statistical_specs: dict[tuple[str, str], StatisticalSpec],
    on_warning: Callable[[QualityWarning], None] | None,
) -> None:
    """After a conditional column is drawn, report the rows whose parent had no fitted combination
    (`statistical`) or no `by` entry (`categorical`) and drew from the column's overall mix. One
    record per column, only when such rows exist. Names and counts only; output bytes are
    untouched. Both providers count through `select_table`, the one parent keying."""
    if n <= 0:
        return
    column, condition_on = str(col.get("name")), col.get("condition_on")
    if col.get("type") == "categorical" and condition_on is not None:
        provider = "categorical"
        # The draw already refused a missing parent column, so the values are there.
        counts = fallback_counts(conditional_tables(col)[1], data[condition_on], n)
    elif col.get("type") == "statistical":
        provider = "statistical"
        spec = statistical_specs.get((table_name, column))
        if spec is None or spec.condition_on is None:
            return
        column, condition_on = spec.column, spec.condition_on
        counts = conditional_fallback_counts(spec, data.get(spec.condition_on) or [], n)
    else:
        return
    if counts.rows == 0:
        return
    detail: dict[str, DetailValue] = {
        "table": table_name,
        "column": column,
        "condition_on": condition_on,
        "rows": counts.rows,
        "rows_null_parent": counts.rows_null_parent,
        "rows_total": n,
        "parent_values": counts.parent_values,
        "parent_values_capped": counts.parent_values_capped,
    }
    line = (
        f"generation_condition_parent_unseen: table={table_name} column={column} "
        f"condition_on={condition_on} rows={counts.rows} "
        f"rows_null_parent={counts.rows_null_parent} rows_total={n} "
        f"parent_values={counts.parent_values} capped={counts.parent_values_capped}"
    )
    record = QualityWarning(
        code=reasons.warning.GENERATION_CONDITION_PARENT_UNSEEN,
        provider=provider,
        column=column,
        detail=detail,
    )
    emit_generation_warning(record, _log, line, on_warning)
