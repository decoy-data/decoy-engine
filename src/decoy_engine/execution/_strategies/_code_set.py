"""code_set strategy handler (engine-v2 SP-09b, 2026-06-28).

Thin V2 StrategyHandler wrapping ``decoy_engine.transforms.code_set``.
Core logic (HMAC-keyed code selection, per-row gen-mode seeding, corpus
loading, chapter_preserve, config validation) lives in the transforms
module for testability and reuse outside the execution layer.

Config keys accepted via ``plan.provider_config``:
  code_set       str   Corpus name (e.g. ``"icd10"``, ``"hcpcs"``, ``"ndc"``, ``"mcc"``).
  mode           str   ``"mask"`` (default) or ``"gen"``.
  chapter_preserve bool When True, restrict to the same chapter bucket as input.
  corpus_source  str   ``"shipped"`` (default) or ``"customer:<absolute_path>"``.

Sprint 2 honesty pack (2026-07-04, D7/S6): ``apply_code_set`` can raise
``PlanCompileError`` PER VALUE under ``chapter_preserve`` (the input's
chapter absent from the corpus, or a sole-member chapter bucket with no
alternative code). Before this sprint one bad value killed the whole job
with no row attribution. ``run`` now catches exactly those two per-value
codes (``code_set_chapter_absent``, ``code_set_sole_member_bucket``) and
records a ``RowError`` (trigger ``"mask_error"``) instead, leaving the
original value in the frame (trap T4). Every OTHER ``PlanCompileError`` code
(corpus not loadable, missing/empty corpus, missing chapter column, single-
row corpus) is a config/corpus-level defect that affects every row, not a
row defect, and is re-raised unchanged: the discriminator is the exception's
``.code`` attribute, not a string match on its message (trap T8 -- no
heuristic re-derivation of what "corpus-level" means).

HC-1 slice 1 (2026-07-17): ``run`` stamps one corpus-provenance entry into
``ctx.code_set_corpora`` per (table, column), before the per-value loop
(``describe_loaded_corpus``). ``PandasExecutionAdapter`` surfaces the
accumulated sink into ``ExecutionResult.quality_metrics['code_set_corpora']``
at the end of the job -- counts and identifiers only (source, source_version,
effective_date, license, row_count), never raw codes. Keyed by (table,
column) rather than bare column name so two tables with a same-named
code_set column bound to different corpora each surface their own evidence
entry instead of one overwriting the other.

Codex P2 FAIL-CLOSED VALIDATION BYPASSED BY A ZERO-MATCH `when` GATE
remediation (2026-07-17): ``run``'s eager corpus load/validation only fires
when ``run`` is actually invoked, but ``execution._when_gate.run_with_
when_gate`` never calls ``run`` for a `when:`-gated column whose predicate
matches zero rows -- it short-circuits to a passthrough. That let a
code_set column referencing a missing/invalid corpus succeed silently
whenever its gate happened to match nothing. ``CodeSetHandler.preflight``
(an optional hook the when-gate calls unconditionally, before its
zero-match short-circuit) re-runs the same load/validate call so the
corpus is validated regardless of match count, while evidence stamping
(NIT-1: only on ``masked_any``) stays exclusively ``run``'s job.

Codex round-6 P2 MASKING/EVIDENCE VERSION DIVERGENCE remediation
(2026-07-17): pre-fix, ``run`` stamped evidence via one ``describe_loaded_
corpus`` call while each per-value ``apply_code_set`` call independently
re-resolved the corpus from the cache. The customer cache invalidates on
(path, mtime_ns, ctime_ns, size), so a customer corpus file REPLACED mid-run
could make later values mask off a DIFFERENT corpus version than the one
evidence already reported -- outputs and evidence silently disagreeing.
Root-cause fix: ``run`` now resolves ONE ``_CorpusRecord`` via
``resolve_corpus_record`` before the per-value loop and threads that SAME
pinned record into both ``describe_loaded_corpus`` and every
``apply_code_set`` call, so masking and evidence structurally cannot
diverge -- there is only ever one record in play for the whole column.
"""

from __future__ import annotations

import sys

import pandas as pd

from decoy_engine import fileaccess, reasons
from decoy_engine.execution._adapter import (
    StrategyContext,
    StrategyOption,
    option,
    provider_config_to_dict,
)
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._row_errors import RowError
from decoy_engine.generation.pool._events import QualityWarning
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.transforms.code_set import (
    SHIPPED_CODE_SETS,
    CodeSetConfig,
    apply_code_set,
    check_mode,
    describe_loaded_corpus,
    resolve_corpus_record,
)

# PlanCompileError codes that are PER-VALUE defects (this specific input
# code cannot be masked under chapter_preserve), not corpus/config-level
# defects. Exhaustive per transforms/code_set.py's chapter_preserve raises;
# every other code (corpus load/schema/emptiness, missing chapter column,
# single-row corpus) affects every row and stays job-fatal.
_PER_VALUE_CODE_SET_ERRORS: frozenset[str] = frozenset(
    {reasons.plan.CODE_SET_CHAPTER_ABSENT, reasons.plan.CODE_SET_SOLE_MEMBER_BUCKET}
)


# Caps on the per-call memo in ``CodeSetHandler.run`` (bound the extra memory
# on high-cardinality or long-string columns; past a cap the loop falls back
# to one scalar call per value).
_MEMO_MAX_ENTRIES = 65_536
_MEMO_MAX_KEY_BYTES = 8 * 1024 * 1024


class CodeSetHandler:
    """Code-corpus masking: replaces each value with a code drawn from a named corpus.

    Delegates to ``decoy_engine.transforms.code_set.apply_code_set``.
    Config validation runs at execution time, pre-mutation, fail-closed: an invalid
    ``provider_config`` raises ``PlanCompileError`` (via ``CodeSetConfig.from_dict``)
    before any row is processed.

    Gen mode uses per-row variation (row_index threaded into the RNG seed) so
    the output column is not constant for a fixed job_seed.
    """

    name: str = "code_set"
    namespace_required: bool = True
    join_safe: bool = False
    wizard_options: tuple[StrategyOption, ...] = (
        option("code_set", "str", "icd10", required=True, choices=SHIPPED_CODE_SETS),
        option("mode", "str", "gen", choices=("mask", "gen")),
        option("chapter_preserve", "bool", True),
    )
    offer_in_wizard: bool = True

    def preflight(self, plan: ColumnSeed, ctx: StrategyContext) -> None:
        """Load and validate this column's corpus, regardless of row count.

        Codex P2 FAIL-CLOSED VALIDATION BYPASSED BY A ZERO-MATCH `when` GATE
        remediation: `run()`'s eager `describe_loaded_corpus` call below
        (the fail-closed corpus check) never executes when this column has a
        `when:` gate that matches zero rows, because
        `execution._when_gate.run_with_when_gate` short-circuits to a
        passthrough before calling `run()` at all. That let a code_set
        column referencing a missing or invalid corpus succeed silently
        whenever its gate happened to match nothing. `run_with_when_gate`
        calls this optional hook unconditionally, before its zero-match
        short-circuit, so the corpus is always validated. Deliberately does
        NOT touch `ctx.code_set_corpora` -- NIT-1 (evidence stamped only
        when the column actually masks >= 1 value) is `run()`'s job alone;
        this method exists purely to make the load raise when the corpus is
        bad, not to record evidence.
        """
        cfg = provider_config_to_dict(plan.provider_config)
        check_mode(str(cfg.get("mode", "mask")))
        code_cfg = CodeSetConfig.from_dict(cfg)
        describe_loaded_corpus(code_cfg)

    def run(
        self,
        df: pd.DataFrame,
        column: str,
        plan: ColumnSeed,
        ctx: StrategyContext,
    ) -> tuple[pd.DataFrame, list[QualityWarning]]:
        cfg = provider_config_to_dict(plan.provider_config)
        mode = str(cfg.get("mode", "mask"))
        check_mode(mode)
        code_cfg = CodeSetConfig.from_dict(cfg)

        if mode == "gen" and plan.namespace is None:
            raise StrategyError(
                code=reasons.runtime.CODE_SET_GEN_REQUIRES_NAMESPACE,
                strategy="code_set",
                message=(
                    f"column {column!r} uses code_set gen mode but has no namespace. "
                    "Set namespace on the ColumnSeed so gen-mode columns are "
                    "decorrelated across namespaces via derive_index."
                ),
            )

        # HC-1 slice 1: eagerly load (and fail-close/warn on) the corpus up
        # front, same as the first per-value apply_code_set call would have,
        # just earlier -- catches a corpus-level defect even for an all-null
        # (or, under a `when` gate, fully-suppressed-subset) column that would
        # otherwise never dispatch a single value below. `evidence` is the
        # candidate provenance-evidence entry for this column; NIT-1
        # remediation (HC-1 slice 1 gap) below only commits it into the
        # shared sink if this column actually masked >=1 value, so a
        # column that validates cleanly but never dispatches (all-null, or
        # when-gated to zero live rows in this subset) does not falsely
        # report its corpus as "used."
        #
        # Codex round-6 P2 MASKING/EVIDENCE VERSION DIVERGENCE remediation:
        # resolve the corpus record ONCE here and thread the SAME object into
        # `describe_loaded_corpus` and every `apply_code_set` call below,
        # instead of each independently re-resolving from the cache. A
        # customer corpus file replaced mid-run can then no longer make a
        # later value mask off a different version than the one evidence
        # already reported -- see this module's docstring.
        #
        # Codex round-7 P2 CROSS-INVOCATION DIVERGENCE remediation: pin the
        # record on `ctx` keyed by (table, column) so the round-6 single-run
        # guarantee extends across the TWO `run` invocations an FK parent
        # under `orphan_policy=REMAP` triggers (the parent's own masking, plus
        # the orphan-REMAP closure re-running the parent strategy). Both key on
        # the same (current_table, evidence-column) identity, so orphan remaps
        # mask off -- and stamp evidence for -- the exact same corpus version
        # as the parent's real values, even if the file is replaced between
        # the two calls. Falls through to a fresh resolve on the first call
        # (byte-identical to round-6 behavior when no replacement occurs).
        record_key = (ctx.current_table, ctx.nested_outer_column or column)
        corpus_record = ctx.code_set_records.get(record_key)
        if corpus_record is None:
            with fileaccess.at_position(f"tables.{record_key[0]}.columns.{record_key[1]}"):
                corpus_record = resolve_corpus_record(code_cfg)
            ctx.code_set_records[record_key] = corpus_record
        evidence = describe_loaded_corpus(code_cfg, record=corpus_record)

        source = df[column]
        na_mask = source.isna().to_numpy()
        out: list[object] = []
        masked_any = False
        # Mask mode is a pure function of str(value), so repeats reuse the first
        # answer. Gen mode depends on row_index and keeps one call per row.
        use_memo = mode == "mask"
        done: dict[str, str] = {}
        failed: dict[str, str] = {}
        memo_bytes = 0
        memo_open = use_memo
        for i, value in enumerate(source):
            if na_mask[i]:
                out.append(None)
                continue
            key = str(value)
            if use_memo and key in done:
                out.append(done[key])
                masked_any = True
                continue
            reason = failed.get(key) if use_memo else None
            if reason is None:
                try:
                    result = apply_code_set(
                        key,
                        code_cfg,
                        mode=mode,
                        job_seed=ctx.mask_key,
                        row_index=i,
                        namespace=plan.namespace,
                        corpus_record=corpus_record,
                    )
                except PlanCompileError as exc:
                    if exc.code not in _PER_VALUE_CODE_SET_ERRORS:
                        raise  # corpus/config-level defect: still job-fatal
                    reason = f"code_set could not mask this value ({exc.code})"
                    result = None
                # Check and insert share one `size`; once a cap is hit the memo
                # stays closed so a later short key cannot sneak in.
                if memo_open:
                    size = sys.getsizeof(key)
                    if (
                        len(done) + len(failed) < _MEMO_MAX_ENTRIES
                        and memo_bytes + size <= _MEMO_MAX_KEY_BYTES
                    ):
                        if reason is None:
                            done[key] = result  # type: ignore[assignment]
                        else:
                            failed[key] = reason
                        memo_bytes += size
                    else:
                        memo_open = False
                # Drop the local name before the next str(value) is built. On a
                # miss that frees the string unless the memo stored it. On a hit
                # for a failed value the name is not deleted here; that string
                # equals one `failed` already holds (and counted against the byte
                # cap), so the transient copy adds at most one stored-size key.
                del key
            if reason is not None:
                # Sprint 2 honesty pack (D7): a per-value defect. Record it
                # and keep the ORIGINAL value in the frame (trap T4); the
                # pipeline-level rule (D8) guarantees this row never reaches
                # the main output. Not a successful mask, so it does not set
                # masked_any (the raw value stays put, same as a null row).
                ctx.row_errors.append(
                    RowError(
                        column=column,
                        row_index=i,
                        trigger="mask_error",
                        reason=reason,
                    )
                )
                out.append(value)
                continue
            out.append(result)
            masked_any = True

        if masked_any:
            # Once-per-(table, column) stamp (not once-per-value): a column
            # dispatched more than once (e.g. re-run under a when_gate across
            # repeated calls is not a real code path today, but this stays
            # idempotent either way) just overwrites with the same evidence
            # dict. Keyed by (table, column) rather than a bare column name --
            # two tables can legally declare a same-named code_set column
            # bound to different corpora (Codex P2 MULTI-TABLE EVIDENCE
            # COLLISION); a bare-column key let the second table's stamp
            # silently overwrite the first's. `table`/`column` ride along in
            # the evidence dict itself so the flattened metrics list (which
            # discards the sink's keys) still records which table+column used
            # which corpus.
            #
            # Codex round-4 P2 NESTED CODE_SET MIS-KEYED EVIDENCE
            # remediation: when this handler is running as a nested
            # strategy's child, `column` is the synthetic `_nested_leaves`
            # batch-collection name, not a real column on the frame --
            # `NestedStrategyHandler` stamps the real outer column onto
            # `ctx.nested_outer_column` before dispatching here. Prefer that
            # when set so evidence attributes to the column the operator
            # actually configured, and so two nested code_set columns in one
            # table key on their distinct outer columns instead of both
            # colliding on `_nested_leaves`.
            evidence_column = ctx.nested_outer_column or column
            ctx.code_set_corpora[(ctx.current_table, evidence_column)] = {
                **evidence,
                "table": ctx.current_table,
                "column": evidence_column,
            }

        if out:
            df[column] = out
        else:
            # An empty `out` (a zero-row chunk, or a genuinely empty
            # full-frame table) assigned as a plain `[]` infers pandas
            # float64 -> Arrow `double`, diverging from a non-empty chunk's
            # object/string output and breaking chunk concatenation (a
            # code_set column's output is always a string, at any row
            # count). Force the empty case to the same string type instead
            # of leaving pandas to guess.
            df[column] = pd.array([], dtype="string")
        return df, []
