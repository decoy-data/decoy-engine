"""nested strategy (engine-v2 MG-3 / M2, 2026-05-31): JSONPath-targeted
masking.

Wraps a child strategy. For each cell:
  1. Parse the cell as JSON (object or array).
  2. Use jsonpath-ng to locate one or more leaf values at `target`.
  3. Collect the leaf values into a temporary Series.
  4. Run the child strategy against that Series (single batch call).
  5. Write the masked values back into the parsed JSON at the same
     paths.
  6. Re-serialize the cell.

Single-pass collection + batch delegation preserves the child
strategy's vectorized behavior. Fail-closed behavior (TEST-3): a
JSON-malformed cell records a `RowError(format_error)` (plus an
advisory QualityWarning) so it is quarantined or fails the job rather
than passing its cleartext through; a child strategy's own RowErrors
are remapped from the flattened-leaf position back to the outer row;
and a target that matches nothing across the whole column raises
`nested_target_matched_nothing` (a wholly-unmatched target is a
misconfiguration, not a silent passthrough). A genuine sparse path
(SOME cells match, some do not) stays valid: unmatched cells are left
as-is. Under a `when:` gate the all-zero-match check applies to the
GATED SUBSET, so gating to a partition whose rows never carry the
target raises (fail-closed by design); if that partition legitimately
lacks the field, target a path that matches or narrow the gate.

Round-trip note (QA-3 F8, 2026-05-31): the cell is parsed via
`strict_json_read` and re-serialized via `strict_json_write`. Whitespace
and escapes are canonicalized, so the masked cell is not byte-for-byte
identical to the input even when the target leaf is unchanged. A number
is the exception: it is written as it was read (`1.10`, `1e400`, a long
decimal). Operators relying on byte-stable input
should mask upstream of any JSON normalization.

Config (`provider_config`):
    target          str             JSONPath expression locating the
                                    leaves to mask. Required.
    strategy        str             Child strategy name (must be a key
                                    of SCALAR_HANDLERS and NOT
                                    "nested"). Required.
    strategy_config dict            Provider config for the child
                                    strategy. Optional, defaults to
                                    empty.
    rules           list            Instead of target/strategy: several
                                    rules, each with target, strategy,
                                    strategy_config and an optional
                                    namespace (default: the column's).
                                    Matches of every rule are collected
                                    before any write; two rules that
                                    reach the same position or an
                                    ancestor and its descendant fail the
                                    column closed.

Established methodology citation: jsonpath-ng is the maintained
Python implementation of the JSONPath specification (RFC 9535 draft
+ Stefan Goessner's reference syntax). MIT-licensed; matches our
posture for numexpr / polars (we don't reinvent parsers).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jsonpath_ng
import pandas as pd

from decoy_engine import reasons
from decoy_engine._canonical import StrictJsonError, strict_json_plain, strict_json_write
from decoy_engine._nested_json import NestedChild, effective_provider, nested_children
from decoy_engine.execution._adapter import StrategyContext, StrategyOption, provider_config_to_dict
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._strategies.nested._apply import (
    LEAF_COLUMN,
    RuleOutput,
    match_path,
    refuse_corrupting_write,
    refuse_rule_overlap,
    remap_row_errors,
)
from decoy_engine.execution._strategies.nested._leaves import (
    find_matches,
    leaf_frame,
    read_cell,
    record_fault,
    written_leaf,
)
from decoy_engine.execution._technique_class import technique_class_for
from decoy_engine.generation.pool._events import QualityWarning
from decoy_engine.plan._types import ColumnSeed


def _child_ner_version(plan: ColumnSeed, strategy: str, config: Any) -> str | None:
    """The NER model version the outer seed pinned for this child's model, for its drift guard."""
    if strategy not in ("text_redact", "text_mask") or not isinstance(config, dict):
        return None
    from decoy_engine.detection.ner import pinned_ner_version, resolve_column_ner

    return pinned_ner_version(plan.ner_model_version, resolve_column_ner(config.get("ner"))[0])


def run_rule_child(
    handler: Any,
    seed: ColumnSeed,
    column: str,
    ctx: StrategyContext,
    leaf_values: list[Any],
    leaf_outer_pos: list[int],
    rule_index: int | None,
) -> RuleOutput:
    """Run one rule's child over its collected leaves in one batch.

    The child sees the synthetic `_nested_leaves` column, so the real outer column and the rule's
    rule index are stamped on `ctx` for the call and restored after (the prior values are
    saved: nested dispatch can itself run inside another node). Row errors the child records at a
    leaf position are remapped to the outer row, or the job fails when one cannot be placed.
    """
    temp_df = leaf_frame(LEAF_COLUMN, leaf_values)
    prior_outer_column = getattr(ctx, "nested_outer_column", "")
    prior_rule_index = getattr(ctx, "nested_rule_index", None)
    object.__setattr__(ctx, "nested_outer_column", column)
    object.__setattr__(ctx, "nested_rule_index", rule_index)
    # A positional child keys on its leaf ordinal, not the outer row, so the outer gate's
    # positions must not reach it.
    prior_gate_positions = getattr(ctx, "gate_positions", None)
    object.__setattr__(ctx, "gate_positions", None)
    # `getattr`: a minimal ctx double has no `row_errors`; a real context always does.
    ctx_row_errors = getattr(ctx, "row_errors", None)
    n_err_before = len(ctx_row_errors) if ctx_row_errors is not None else 0
    try:
        temp_df, child_warnings = handler.run(temp_df, LEAF_COLUMN, seed, ctx)
    finally:
        object.__setattr__(ctx, "nested_outer_column", prior_outer_column)
        object.__setattr__(ctx, "nested_rule_index", prior_rule_index)
        object.__setattr__(ctx, "gate_positions", prior_gate_positions)
    if ctx_row_errors is not None:
        remap_row_errors(ctx_row_errors, n_err_before, leaf_outer_pos, column)
    values: list[Any] = []
    non_finite: set[int] = set()
    for leaf_pos, out in zip(leaf_outer_pos, temp_df[LEAF_COLUMN].tolist(), strict=True):
        out, finite = written_leaf(out)
        values.append(out)
        if not finite:
            non_finite.add(leaf_pos)
    return RuleOutput(values, non_finite, list(child_warnings))


@dataclass(frozen=True)
class _Rule:
    """One rule ready to run: its child, resolved handler and seed, and parsed target."""

    child: NestedChild
    target: str
    handler: Any
    seed: ColumnSeed
    expr: Any
    rule_index: int | None


class NestedStrategyHandler:
    """JSONPath-targeted child-strategy wrapper."""

    name: str = "nested"
    namespace_required: bool = True
    join_safe: bool = False
    wizard_options: tuple[StrategyOption, ...] = ()
    offer_in_wizard: bool = False

    def _resolve_child(
        self, plan: ColumnSeed, column: str | None = None, child: NestedChild | None = None
    ) -> tuple[Any, ColumnSeed]:
        """Resolve the child strategy handler + a synthetic child `ColumnSeed`.

        Shared by `run()` (real masking dispatch) and `preflight()` (corpus-
        only validation forward), so the two entry points can never drift on
        error codes or on which handler/seed a given `provider_config`
        resolves to. Codex round-5 P2 NESTED CODE_SET CHILD NOT PREFLIGHTED
        UNDER A ZERO-MATCH WHEN-GATE remediation: this is exactly the
        resolution `run()` did inline before this fix (parse
        `provider_config` -> child strategy name + config, reject
        nested-of-nested, look up `SCALAR_HANDLERS`, classify the child's
        `technique_class`); extracting it lets `preflight()` reuse it
        byte-for-byte instead of re-deriving a second copy that could
        silently diverge.

        `column` is optional and cosmetic only (folded into error messages
        when known): `run()` passes the real column so its error text stays
        byte-identical to the pre-extraction inline checks; `preflight()` is
        called by `run_with_when_gate` as `preflight(plan, ctx)` -- no
        column argument exists at that call site -- so it omits the suffix.

        Does not validate `target` (that stays `run()`-only -- JSONPath
        targeting is about locating leaves in the frame, not about which
        child strategy handles them, and preflighting it is out of this
        fix's scope).
        """
        # Lazy import keeps the SCALAR_HANDLERS init cycle clean (the
        # nested strategy reads from SCALAR_HANDLERS, and the
        # SCALAR_HANDLERS dict imports nested strategy at module load).
        from decoy_engine.execution._strategies import SCALAR_HANDLERS

        child = child or self._children(plan)[0]
        child_strategy_name = child.strategy
        child_strategy_config = child.strategy_config or {}
        column_suffix = f" (column={column!r})" if column is not None else ""

        if not isinstance(child_strategy_name, str) or not child_strategy_name:
            raise StrategyError(
                code=reasons.runtime.NESTED_STRATEGY_UNSET,
                strategy="nested",
                message=(
                    "nested child strategy is required and must be a non-empty "
                    f"string{column_suffix}."
                ),
            )

        if child_strategy_name == "nested":
            raise StrategyError(
                code=reasons.runtime.NESTED_RECURSIVE_NESTED_REJECTED,
                strategy="nested",
                message=f"nested cannot wrap itself recursively{column_suffix}.",
            )

        child_handler = SCALAR_HANDLERS.get(child_strategy_name)
        if child_handler is None:
            raise StrategyError(
                code=reasons.runtime.NESTED_CHILD_STRATEGY_UNKNOWN,
                strategy="nested",
                message=(
                    f"nested child strategy {child_strategy_name!r} is not a "
                    f"registered SCALAR_HANDLERS key{column_suffix}. "
                    "A typo here silently dropped PII pre-fix."
                ),
            )

        # Build a synthetic child seed inheriting parent fields but
        # carrying the child strategy + config.
        child_provider_config: tuple[tuple[str, Any], ...]
        if isinstance(child_strategy_config, dict):
            # A rule's `provider` is the seed's provider, not a setting the child passes on.
            kept = {
                k: v
                for k, v in child_strategy_config.items()
                if not (child.index is not None and k == "provider")
            }
            child_provider_config = tuple(sorted(kept.items()))
        else:
            child_provider_config = ()
        # QA-3 F7 (2026-05-31): resolve the CHILD's technique class. The
        # parent's `technique_class` is None for nested (intentionally;
        # see _technique_class.py), so inheriting it would always leave
        # the child seed unclassified. The child should report the
        # class of the strategy it actually runs (e.g. redact ->
        # anonymisation).
        child_seed = ColumnSeed(
            # A rule may name its own namespace; absent means the column's.
            namespace=child.namespace
            if child.index is not None and child.namespace
            else plan.namespace,
            strategy=child_strategy_name,
            provider=effective_provider(child, plan.provider),
            backend_type=plan.backend_type,
            backend_version=plan.backend_version,
            cardinality_mode=plan.cardinality_mode,
            deterministic=plan.deterministic,
            provider_config=child_provider_config,
            coherent_with=plan.coherent_with,
            technique_class=technique_class_for(child_strategy_name),
            when=None,
            ner_model_version=_child_ner_version(plan, child_strategy_name, child_strategy_config),
        )
        return child_handler, child_seed

    def preflight(self, plan: ColumnSeed, ctx: StrategyContext) -> None:
        """Forward preflight validation to the child strategy.

        Codex round-5 P2 NESTED CODE_SET CHILD NOT PREFLIGHTED UNDER A
        ZERO-MATCH WHEN-GATE remediation: `execution._when_gate.run_with_
        when_gate` calls `getattr(handler, "preflight", None)`
        unconditionally, before its zero-match short-circuit -- but that
        only helps when `handler` itself defines `preflight`.
        `CodeSetHandler` does; `NestedStrategyHandler` (the outer handler
        for a `nested(code_set)` column) did not, so the CHILD
        `CodeSetHandler.preflight` was never reached, and a
        `nested(code_set)` column referencing a missing/invalid corpus
        succeeded silently whenever its `when:` gate matched zero rows --
        the exact fail-closed hole `CodeSetHandler.preflight` closes for a
        bare (non-nested) `code_set` column, one level deeper.

        Resolves the child via `_resolve_child` (same helper `run()` uses)
        and forwards to the child handler's own optional `preflight` hook
        if it defines one. Deliberately does NOT run masking and does NOT
        touch `ctx.code_set_corpora` -- evidence stamping (NIT-1: only on
        `masked_any`) stays exclusively `run()`'s job, same contract as
        `CodeSetHandler.preflight`.
        """
        for child in self._children(plan):
            child_handler, child_seed = self._resolve_child(plan, child=child)
            child_preflight = getattr(child_handler, "preflight", None)
            if child_preflight is not None:
                child_preflight(child_seed, ctx)

    @staticmethod
    def _children(plan: ColumnSeed) -> tuple[NestedChild, ...]:
        children = nested_children(provider_config_to_dict(plan.provider_config))
        if not children:
            raise StrategyError(
                code=reasons.runtime.NESTED_TARGET_UNSET,
                strategy="nested",
                message="nested has no rule to run: `rules` must be a non-empty list.",
            )
        return children

    def _prepare_rules(self, plan: ColumnSeed, column: str, ctx: StrategyContext) -> list[_Rule]:
        """Validate and resolve every rule before any cell is read, in config order.

        QA-3 F12 (security): a config error raises `StrategyError` so the runner fails the job;
        returning the frame unchanged would pass PII through on a typoed target or child name.
        """
        rules: list[_Rule] = []
        for child in self._children(plan):
            target = child.target
            if not isinstance(target, str) or not target:
                raise StrategyError(
                    code=reasons.runtime.NESTED_TARGET_UNSET,
                    strategy="nested",
                    message=(
                        f"nested target is required and must be a non-empty string "
                        f"(column={column!r}). Pre-fix this returned the column "
                        "unchanged with a QualityWarning; misconfigured targets "
                        "silently passed PII through."
                    ),
                )
            # Child resolution (name check, nested-of-nested rejection, SCALAR_HANDLERS lookup,
            # technique class) is shared with `preflight()` so the two cannot drift.
            handler, seed = self._resolve_child(plan, column, child)
            # A bucket_perturb child must reject an unwritable date_format even for an empty,
            # all-null or zero-match column, which return before the child runs.
            if seed.strategy == "bucket_perturb":
                handler.preflight(seed, ctx)
            expr = None
            try:
                expr = jsonpath_ng.parse(target)
            except Exception:
                pass  # refused below, outside the handler, so no parser text rides along
            if expr is None:
                raise StrategyError(
                    code=reasons.runtime.NESTED_JSONPATH_PARSE_ERROR,
                    strategy="nested",
                    message=(
                        f"a nested target is not a valid JSONPath expression (column={column!r})."
                    ),
                )
            # Two rules never share a draw; the single form keeps the outer column identity.
            rules.append(_Rule(child, target, handler, seed, expr, child.index))
        return rules

    def run(
        self,
        df: pd.DataFrame,
        column: str,
        plan: ColumnSeed,
        ctx: StrategyContext,
    ) -> tuple[pd.DataFrame, list[QualityWarning]]:
        rules = self._prepare_rules(plan, column, ctx)

        col = df[column]
        if pd.api.types.is_extension_array_dtype(col.dtype):
            col = col.astype(object)
        else:
            col = col.copy()

        # QA-3 F2: positional enumeration, not an index-keyed dict, so duplicate index labels
        # cannot return a Series for one cell or drop a row's state.
        col_values = col.to_list()

        warnings: list[QualityWarning] = []
        # Per rule: the collected leaves and the outer row position each came from, so a
        # child-produced RowError (recorded at the flattened-leaf position) is remapped to the
        # real outer row (TEST-3 P1-1).
        leaves: list[list[Any]] = [[] for _ in rules]
        leaf_outer_pos: list[list[int]] = [[] for _ in rules]
        # True once a non-null cell parses as valid JSON: separates an all-null or all-malformed
        # column (nothing to match) from a valid column where a target matched NOTHING, which is
        # a misconfiguration that must fail closed (TEST-3 P1-2).
        saw_parseable = False
        rule_fault = [False] * len(rules)
        # Per position: the parsed cell and, per matching rule, its matches (rule order).
        per_position_state: dict[int, tuple[Any, list[tuple[int, list]]]] = {}

        for pos, cell in enumerate(col_values):
            if pd.isna(cell):
                continue
            try:
                parsed = read_cell(cell)
            except StrictJsonError as exc:
                # A faulty cell cannot be masked: a RowError (never the cell text, trap T3) so
                # the row is quarantined or the job fails, never emitted with cleartext intact.
                record_fault(ctx, warnings, column, pos, exc.token)
                continue
            saw_parseable = True
            # Every rule matches on the parsed tree before any write.
            found: list[tuple[int, list, list[Any]]] = []
            faulted = False
            for ri, rule in enumerate(rules):
                matches = find_matches(rule.expr, parsed, column)
                if not matches:
                    continue
                # QA-3 F14 (security): within one rule, an outer container's write can erase a
                # nested child's, so matches go deepest-first and an ambiguous path is flagged.
                ordered_matches = _order_matches_deepest_first(matches)
                if _has_prefix_overlap(ordered_matches):
                    warnings.append(
                        QualityWarning(
                            code=reasons.warning.NESTED_JSONPATH_PATH_OVERLAP,
                            provider="nested",
                            column=column,
                            detail={
                                "row_pos": str(pos),
                                "target": rule.target,
                                "match_count": str(len(ordered_matches)),
                            },
                        )
                    )
                if faulted:
                    # An earlier rule already failed this row. The rule still matched, so it is
                    # not a zero-match misconfiguration.
                    rule_fault[ri] = True
                    continue
                try:
                    cell_leaves = [strict_json_plain(m.value) for m in ordered_matches]
                except StrictJsonError as exc:
                    record_fault(ctx, warnings, column, pos, exc.token)
                    rule_fault[ri] = True  # the target matched; the row error fails it
                    faulted = True
                    continue
                found.append((ri, ordered_matches, cell_leaves))
            if faulted:
                # Rules that matched before the fault lose this row's leaves; none of them is a
                # zero-match misconfiguration.
                for ri, _matches, _leaves in found:
                    rule_fault[ri] = True
                continue
            if not found:
                continue
            refuse_rule_overlap(column, [(i, [match_path(m) for m in ms]) for i, ms, _ in found])
            for i, _matches, cell_leaves in found:
                leaves[i].extend(cell_leaves)
                leaf_outer_pos[i].extend([pos] * len(cell_leaves))
            per_position_state[pos] = (parsed, [(i, ms) for i, ms, _ in found])

        # A rule that matched NOTHING in the whole column is a typoed or wrong path, not a sparse
        # path: returning the column would emit every cell's cleartext unmasked. Sparse per-cell
        # no-match (some cell matched) never reaches here.
        for rule, rule_leaves, faulted in zip(rules, leaves, rule_fault, strict=True):
            if saw_parseable and not rule_leaves and not faulted:
                raise StrategyError(
                    code=reasons.runtime.NESTED_TARGET_MATCHED_NOTHING,
                    strategy="nested",
                    message=(
                        f"nested target {rule.target!r} matched no value in any "
                        f"non-null cell of column {column!r}. A target that matches "
                        "nothing across the whole column is treated as a "
                        "misconfiguration (a typoed or wrong path) rather than a "
                        "silent passthrough, which would emit every cell unmasked. "
                        "Verify the target path."
                    ),
                )
        if not any(leaves):
            return df, warnings

        new_values: dict[int, list[Any]] = {}
        non_finite_pos: set[int] = set()
        for i, rule in enumerate(rules):
            if not leaves[i]:
                continue
            out = run_rule_child(
                rule.handler, rule.seed, column, ctx, leaves[i], leaf_outer_pos[i], rule.rule_index
            )
            warnings.extend(out.warnings)
            new_values[i] = out.values
            non_finite_pos |= out.non_finite_positions

        # Writeback walks matches in the order the leaves were collected, then writes each cell
        # once. The column is rebuilt from `col_values` by position (QA-3 F2).
        cursor = dict.fromkeys(new_values, 0)
        for pos, (parsed, per_rule) in per_position_state.items():
            if pos in non_finite_pos:
                # The cell keeps its input text and the row fails closed, so no `Infinity` is written.
                for i, ms in per_rule:
                    cursor[i] += len(ms)
                record_fault(ctx, warnings, column, pos, "child_non_finite")
                continue
            for i, matches in per_rule:
                for m in matches:
                    new_value = new_values[i][cursor[i]]
                    cursor[i] += 1
                    # Refuse a write jsonpath-ng would misapply: it would leave the source value
                    # in place (a cleartext leak), so the whole run fails.
                    refuse_corrupting_write(m, parsed, column)
                    # Capture the return: a ROOT target has no parent to write into, so
                    # `update()` returns the replacement without mutating `parsed`.
                    parsed = m.full_path.update(parsed, new_value)
            col_values[pos] = strict_json_write(parsed)

        df[column] = pd.Series(col_values, index=df.index, dtype=object)
        return df, warnings


def _order_matches_deepest_first(matches: list) -> list:
    """Return matches sorted by path depth descending.

    QA-3 F14 (2026-05-31): when the JSONPath produces overlapping
    matches (one path is a prefix of another), `jsonpath_ng.update`
    in original order can silently lose the inner write. Sorting
    deepest-first makes the outer container's masked value the LAST
    write, so the final cell reflects the parent's masking; this is
    deterministic and matches the operator's intuition for a
    recursive selector (`$..*` -> mask the root, then nothing else
    matters; the inner-leaf writes are discarded by the parent write).
    """
    return sorted(matches, key=lambda m: -len(match_path(m)))


def _has_prefix_overlap(ordered_matches: list) -> bool:
    """Return True if any match's path is a strict prefix of another.

    The list is expected to be deepest-first; under that order a
    prefix-overlap means some pair (deeper, shallower) where shallower
    is a strict prefix of deeper. We do an O(n^2) scan; n is at most
    the number of matches in a single cell (typically <50), and the
    function only runs when matches are non-empty.
    """
    seg_lists = [match_path(m) for m in ordered_matches]
    n = len(seg_lists)
    for i in range(n):
        deeper = seg_lists[i]
        for j in range(i + 1, n):
            shallower = seg_lists[j]
            if len(shallower) < len(deeper) and deeper[: len(shallower)] == shallower:
                return True
    return False
