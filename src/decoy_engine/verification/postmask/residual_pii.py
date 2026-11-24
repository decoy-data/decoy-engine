"""Residual PII check (Reframe-A).

Re-runs the existing detectors over the MASKED OUTPUT to find
columns that still match a PII pattern. Distinguishes three cases:

1. Detector hit on a column that was NOT configured to be masked.
   The operator likely forgot a column. Severity: warning.
2. Detector hit on a column that WAS configured to be masked to a
   strategy that legitimately produces detectable values (faker name
   on a person_name column produces person_name detector hits; this
   is the expected outcome). Severity: info.
3. Detector hit on a column that WAS configured to be masked to a
   strategy that should DESTROY the pattern (hash, redact, bucketize),
   but the pattern survived. Indicates the mask did not fire or
   failed silently. Severity: fail.

Strategies that ARE expected to produce detector hits (i.e. legitimate
realistic-fake): faker, formula, categorical (when categories are
realistic-looking), reference (when parent values are realistic), date_shift.

Strategies that DESTROY the detector pattern: hash, redact, bucketize,
truncate (when truncation depth is small enough that the pattern can no
longer match). FPE is a special case -- it preserves character class
distribution but scrambles values, so it might or might not produce
detector hits depending on the source's natural format.

Source comparison (audit C1 fix, 2026-06-12): when ``source_frames``
is supplied, every detector-flagged column is additionally compared
POSITIONALLY against its source column and the base severity can be
escalated (never lowered). The signal is ``source_identity_rate`` --
the fraction of aligned non-null rows where output == source. Value-set
membership is deliberately NOT a signal: shuffle re-emits 100% of
source values by design, categorical(from_profile) resamples the source
category set, and reference draws from the parent domain, so membership
false-positives on exactly the strategies that are working correctly.
The substitution-vs-value-reuse split mirrors
``validation/post/_checks/_leakage.py`` (``_VALUE_REUSE_STRATEGIES``):
substitution strategies escalate on majority positional identity;
value-reuse strategies escalate only on FULL positional identity (the
mask provably did not move anything); constant-source columns
(nunique <= 1) never escalate because identity is meaningless there.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from decoy_engine.detection import NAME_HINT_GATED_DETECTORS
from decoy_engine.detection.detectors import run_all_detectors
from decoy_engine.profiling import passes_through
from decoy_engine.verification.postmask._column_facts import (
    ColumnFacts,
    DetectorRate,
    identity_counts,
)
from decoy_engine.verification.postmask.types import ResidualPIIFinding, Severity

# Strategies whose output is EXPECTED to look like real PII. A detector
# hit on a column masked with one of these is informational, not a
# warning.
_PRODUCES_PII_LIKE_VALUES: frozenset[str] = frozenset(
    {
        "faker",
        "formula",
        "categorical",
        "reference",
        "date_shift",
    }
)

# Strategies that DESTROY detector patterns. A surviving hit on a column
# masked with one of these is a fail (the mask did not work).
# QA-4 F1 (2026-06-01): text_redact was missing from this set.
# text_redact replaces matched PII spans with a fixed token; any
# detector still hitting after text_redact ran is a failure of the
# detector coverage and must surface as 'fail' (not 'warning').
_DESTROYS_PATTERN: frozenset[str] = frozenset(
    {
        "hash",
        "redact",
        "text_redact",
        "bucketize",
    }
)

# The destroying strategies that replace a whole cell. text_redact is left out: it replaces
# matched spans, and the name-hint-only detectors are not in its span set, so a cell can still
# hold a name after it ran.
_WHOLE_CELL_DESTROYS: frozenset[str] = frozenset({"hash", "redact", "bucketize"})

# Dennis M12 fix (2026-06-01): strategies that explicitly leave the
# column untouched. A detector hit on these is expected -- the user
# deliberately marked the column as a passthrough -- so it's classified
# 'info' (a confirmation), not 'warning'. Without this, every
# passthrough column that matched any detector emitted a false-positive
# residual-PII warning.
_NO_OP_BY_DESIGN: frozenset[str] = frozenset(
    {
        "passthrough",
    }
)

# Strategies that REPLACE values per-cell: positional identity with the
# source at scale means the mask did not fire. Mirrors the substitution
# side of validation/post/_checks/_leakage.py.
_SUBSTITUTION_STRATEGIES: frozenset[str] = frozenset(
    {
        "faker",
        "date_shift",
        "fpe",
    }
)

# Strategies that legitimately re-emit source VALUES (in new positions /
# proportions): only FULL positional identity is a failure signal.
# Mirrors _VALUE_REUSE_STRATEGIES in _leakage.py, plus reference (parent
# domain == source FK domain by design).
_REUSES_SOURCE_VALUES: frozenset[str] = frozenset(
    {
        "shuffle",
        "categorical",
        "reference",
    }
)

# Escalation thresholds for substitution strategies and unconfigured
# columns. Faker/FPE positional self-maps are near-impossible at scale,
# so >=50% identity means the mask mostly did not fire; 5-50% surfaces
# as a non-blocking warning (partial failure, operator review). The
# min-rows floor keeps tiny frames from failing on coincidence.
_LEAK_FAIL_RATE = 0.5
_LEAK_WARN_RATE = 0.05
_LEAK_FAIL_MIN_ROWS = 3

_SEVERITY_ORDER: dict[str, int] = {"info": 0, "warning": 1, "fail": 2, "error": 3}


def check_residual_pii(
    output_frames: dict[str, pd.DataFrame],
    config: dict[str, Any],
    *,
    source_frames: dict[str, pd.DataFrame] | None = None,
) -> list[ResidualPIIFinding]:
    """Scan masked output for surviving PII patterns.

    Args:
        output_frames: ``{table_name: post-mask DataFrame}``.
        config: the validated pipeline config dict (from
            ``PipelineConfig.model_dump()``).
        source_frames: ``{table_name: pre-mask DataFrame}``. When
            supplied, detector-flagged columns are compared positionally
            against source and severity escalates on output==source
            identity (see module docstring). When ``None``, behavior
            degrades to detector-plus-strategy classification only --
            real leaks on PII-like-producer strategies are then
            invisible, so callers that have the source should pass it.

    Returns:
        List of ResidualPIIFinding. Empty list if nothing matched.
        Severity is classified based on the column's configured
        masking strategy (or absence of one), then escalated by the
        source comparison when evidence of a leak exists.
    """
    facts = {
        table_name: {
            str(col_name): _frame_column_facts(table_name, df, str(col_name), source_frames)
            for col_name in df.columns
        }
        for table_name, df in output_frames.items()
    }
    return residual_pii_findings(facts, config)


def _frame_column_facts(
    table_name: str,
    df: pd.DataFrame,
    col_name: str,
    source_frames: dict[str, pd.DataFrame] | None,
) -> ColumnFacts:
    """The facts one column of a resident frame yields, so the frame check and the batch check
    share `residual_pii_findings` as the only place a finding is built."""
    series = df[col_name]
    comparable = identical = distinct = 0
    identity_error: str | None = None
    distinct_error: str | None = None
    pair = _aligned_source(source_frames, table_name, col_name, series)
    if pair is not None:
        src, out = pair
        # Each failure is the column's own and is recorded by class name only, as the batch
        # check does: the message of a comparison error can carry a cell value.
        try:
            comparable, identical = identity_counts(src, out)
        except Exception as exc:
            if passes_through(exc):
                raise
            identity_error = type(exc).__name__
        if comparable:
            # A failed count (an unhashable list cell, say) leaves the identity counts standing,
            # as a failed DuckDB count does on the batch path.
            try:
                distinct = int(src.nunique(dropna=True))
            except Exception as exc:
                if passes_through(exc):
                    raise
                distinct_error = type(exc).__name__
    return ColumnFacts(
        table=table_name,
        column=col_name,
        source_rows=0,
        output_rows=len(series),
        comparable_rows=comparable,
        identical_rows=identical,
        bytes_identical=False,
        source_distinct=distinct,
        output_distinct=0,
        detectors=tuple(
            DetectorRate(m.detector_id, m.match_rate, m.confidence)
            for m in run_all_detectors(series, col_name)
        ),
        identity_error=identity_error,
        distinct_error=distinct_error,
        source_distinct_failed=distinct_error is not None,
    )


def configured_columns(
    config: Mapping[str, Any],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    """The column entry per (table, column) that names a strategy; the model passes read it too.

    Per-table strategy = column-level "strategy" key in tables[].columns[].
    """
    entries: dict[tuple[str, str], Mapping[str, Any]] = {}
    for table_cfg in config.get("tables") or []:
        table_name = table_cfg.get("name")
        if not isinstance(table_name, str):
            continue
        for col_cfg in table_cfg.get("columns") or []:
            col_name = col_cfg.get("name")
            if isinstance(col_name, str) and isinstance(col_cfg.get("strategy"), str):
                entries[(table_name, col_name)] = col_cfg
    return entries


def is_source_identity_finding(finding: ResidualPIIFinding) -> bool:
    """A regex finding raised from positional output==source evidence; a dismissal never lowers it."""
    rate = finding.source_identity_rate
    if finding.source != "regex" or rate is None:
        return False
    gated = _is_gated_whole_cell(finding.configured_strategy, finding.detector_id)
    return _identity_evidence(rate, gated=gated)


def dismissible(finding: ResidualPIIFinding) -> bool:
    """True when a `post_scan.dismissed` entry may lower this finding.

    The one rule the scanner applies to a warning and the post-scan review checks before it writes
    a dismissal: a warning, and not one raised from source-identity evidence.
    """
    return finding.severity == "warning" and not is_source_identity_finding(finding)


def _aligned_source(
    source_frames: dict[str, pd.DataFrame] | None,
    table_name: str,
    col_name: str,
    out_col: pd.Series,
) -> tuple[pd.Series, pd.Series] | None:
    """The source column and `out_col` on one positional index (QA-4 F6), or None when there is
    no source column or the row counts differ (policy_validation's M13 concern, not a leak)."""
    if source_frames is None:
        return None
    src_df = source_frames.get(table_name)
    if src_df is None or col_name not in src_df.columns:
        return None
    src_col = src_df[col_name]
    if len(src_col) != len(out_col):
        return None
    return src_col.reset_index(drop=True), out_col.reset_index(drop=True)


# With no config entry for the table (no `--config`, or a table the config omits) the engine
# cannot know whether the column was meant to be masked, so it says only what it knows.
_UNCONFIGURED_CLAUSE = {
    True: "was not configured to be masked",
    False: "the config has no entry for its table, so its strategy is unknown",
}


def _escalate(
    *,
    configured: str | None,
    identity_rate: float,
    identical_count: int,
    src_distinct: int,
    detector_confidence: str,
    detector_id: str,
    table_present: bool = True,
) -> tuple[Severity, str] | None:
    """Severity override from source-identity evidence, or None.

    Decision table (module docstring): substitution strategies fail at
    majority identity and warn at the 5% floor; value-reuse strategies
    and everything else fail only at FULL identity; unconfigured
    columns fail at majority identity but only on a high-confidence
    detector hit (loose detectors like mrn/license_num must not fail
    verbatim-preserved ID columns on a medium-confidence guess).
    Constant-source columns never escalate.
    """
    if src_distinct <= 1:
        return None

    full_identity = identity_rate == 1.0

    if configured is None:
        if (
            identity_rate >= _LEAK_FAIL_RATE
            and identical_count >= _LEAK_FAIL_MIN_ROWS
            and detector_confidence == "high"
        ):
            return (
                "fail",
                f"column matched {detector_id!r}, {_UNCONFIGURED_CLAUSE[table_present]}, "
                f"and is positionally identical to source for "
                f"{identity_rate:.0%} of rows -- real values shipped to the "
                "output unmasked.",
            )
        return None

    if configured in _SUBSTITUTION_STRATEGIES:
        if identity_rate >= _LEAK_FAIL_RATE and identical_count >= _LEAK_FAIL_MIN_ROWS:
            return (
                "fail",
                f"column matched {detector_id!r} and output is positionally "
                f"identical to source for {identity_rate:.0%} of comparable "
                f"rows; strategy {configured!r} should have replaced these "
                "values -- the mask did not fire.",
            )
        if identity_rate >= _LEAK_WARN_RATE:
            return (
                "warning",
                f"column matched {detector_id!r} and {identity_rate:.0%} of "
                f"output rows kept their source value under strategy "
                f"{configured!r} -- partial mask failure, verify the output.",
            )
        return None

    if configured == "formula":
        # Formula may legitimately incorporate / echo source fragments;
        # only full-column identity (an identity formula on a PII
        # column) is certain failure.
        if full_identity:
            return (
                "fail",
                f"column matched {detector_id!r} and the formula output is "
                "identical to source for every row -- the expression does "
                "not transform the value.",
            )
        if identity_rate >= _LEAK_FAIL_RATE:
            return (
                "warning",
                f"column matched {detector_id!r} and {identity_rate:.0%} of "
                "formula output rows equal their source value -- verify the "
                "expression actually masks.",
            )
        return None

    # Value-reuse strategies (shuffle/categorical/reference) and any
    # other configured strategy: full positional identity means the
    # mask provably moved nothing.
    if full_identity:
        return (
            "fail",
            f"column matched {detector_id!r} and output is positionally "
            f"identical to source for every row; strategy {configured!r} "
            "produced no movement -- the mask did not fire.",
        )
    return None


def _is_gated_whole_cell(strategy: str | None, detector_id: str) -> bool:
    """A whole-cell destroying strategy on a hit from a name-hint-gated detector."""
    return strategy in _WHOLE_CELL_DESTROYS and detector_id in NAME_HINT_GATED_DETECTORS


def _identity_evidence(identity_rate: float, *, gated: bool) -> bool:
    """Whether a source-identity rate is evidence the mask missed rows.

    The one rule for grading and for the dismissal guard. On the gated path a whole-cell
    strategy never legitimately leaves a cell equal to its source, so any identity counts; on
    every other path the 5% floor keeps coincidence from escalating.
    """
    return identity_rate > 0 if gated else identity_rate >= _LEAK_WARN_RATE


def _grade_gated(
    *, identical_rows: int, comparable_rows: int, detector_id: str, strategy: str
) -> tuple[Severity, str]:
    """Grade a column whose detector hits all come from name-hint-gated detectors, under a
    whole-cell destroying strategy, when the source comparison ran.

    The hit itself proves nothing (the detector's regex is loose by design), so the source
    comparison decides: a whole-cell strategy never legitimately leaves a non-null cell equal to
    its source. There is no constant-source or minimum-row exception. Messages carry no rate,
    count or value.
    """
    identity = identical_rows / comparable_rows
    if not _identity_evidence(identity, gated=True):
        return (
            "info",
            f"column matched {detector_id!r} only through its column name; "
            f"strategy {strategy!r} replaced the values.",
        )
    if identical_rows == comparable_rows or (
        identical_rows >= _LEAK_FAIL_MIN_ROWS and identity >= _LEAK_FAIL_RATE
    ):
        return (
            "fail",
            f"column matched {detector_id!r} only through its column name, and the output "
            f"equals the source under strategy {strategy!r}; the mask did not fire.",
        )
    return (
        "warning",
        f"column matched {detector_id!r} only through its column name, and some output "
        f"values still equal their source under strategy {strategy!r}; verify the output.",
    )


def _classify(
    detector_id: str, configured: str | None, table_present: bool = True
) -> tuple[Severity, str]:
    """Classify a detector hit + return (severity, human-readable message).

    Three buckets per the module docstring:
      - no strategy configured: warning (operator may have forgotten)
      - PII-like-producer strategy: info (expected)
      - pattern-destroying strategy: fail (mask didn't work)
      - other strategy (passthrough, fpe, shuffle, etc.): warning
        (might be a leak depending on context; let the operator decide)
    """
    if configured is None:
        return (
            "warning",
            f"column matched {detector_id!r} but {_UNCONFIGURED_CLAUSE[table_present]}. "
            "Verify whether this column should be sensitive.",
        )
    if configured in _NO_OP_BY_DESIGN:
        # Dennis M12 fix: passthrough is an explicit operator decision
        # to leave the column unchanged. A detector hit is expected.
        return (
            "info",
            f"column matched {detector_id!r}; the configured strategy "
            f"{configured!r} is a no-op by design, so the value survives "
            "unchanged.",
        )
    if configured in _PRODUCES_PII_LIKE_VALUES:
        return (
            "info",
            f"column matched {detector_id!r}; expected because the configured "
            f"strategy {configured!r} produces realistic-looking values.",
        )
    if configured in _REUSES_SOURCE_VALUES:
        # Shuffle re-emits the source value multiset by design, so a
        # detector hit on shuffled real values is the expected outcome
        # (categorical/reference already classify as info via
        # _PRODUCES_PII_LIKE_VALUES). The source-identity backstop in
        # _escalate fails the column if the shuffle moved nothing.
        return (
            "info",
            f"column matched {detector_id!r}; expected because the configured "
            f"strategy {configured!r} re-emits source values in new positions.",
        )
    if configured in _DESTROYS_PATTERN:
        return (
            "fail",
            f"column matched {detector_id!r} but was configured for strategy "
            f"{configured!r}, which should destroy the pattern. The mask "
            "may not have fired -- inspect the output.",
        )
    return (
        "warning",
        f"column matched {detector_id!r}; configured strategy {configured!r} "
        "does not have a documented residual-PII expectation. Verify the "
        "output is acceptable.",
    )


def _compare_raised(detector_id: str | None, error: str) -> str:
    """The message of a failed source comparison: the class name only, as text can carry a value."""
    hit = f"column matched {detector_id!r} but the" if detector_id else "the"
    return f"{hit} source comparison raised {error} (see job log); a leak cannot be ruled out."


def residual_pii_findings(
    output_facts: Mapping[str, Mapping[str, ColumnFacts]],
    config: Mapping[str, Any],
    failed_tables: Mapping[str, str] | None = None,
) -> list[ResidualPIIFinding]:
    """`check_residual_pii` from column facts: `{table: {column: ColumnFacts}}` over the output,
    in column order. The decision tables are the ones the frame check uses."""
    strategy_by_col = {key: entry["strategy"] for key, entry in configured_columns(config).items()}
    # Table presence comes from the config's table list, not from the (table, column) strategy
    # lookup, so "table absent" and "table present, column absent" stay distinct.
    config_tables = {
        t["name"]
        for t in config.get("tables") or []
        if isinstance(t, Mapping) and isinstance(t.get("name"), str)
    }
    findings: list[ResidualPIIFinding] = [
        ResidualPIIFinding(
            table=table,
            column="",
            detector_id="",
            match_rate=0.0,
            severity="error",
            message=f"residual_pii check raised {error} (see job log for details)",
        )
        for table, error in (failed_tables or {}).items()
    ]
    for table_name, columns in output_facts.items():
        for col_name, fact in columns.items():
            configured = strategy_by_col.get((table_name, col_name))
            failed_compare = fact.identity_error is not None and configured not in _NO_OP_BY_DESIGN
            if not fact.detectors:
                # A configured column whose comparison raised is reported with no detector hit
                # too: the check could not run. An unconfigured one with no hit was never checked.
                if failed_compare and configured is not None:
                    findings.append(
                        ResidualPIIFinding(
                            table=table_name,
                            column=col_name,
                            detector_id="",
                            match_rate=0.0,
                            severity="error",
                            configured_strategy=configured,
                            message=_compare_raised(None, str(fact.identity_error)),
                        )
                    )
                continue
            top = fact.detectors[0]
            table_present = table_name in config_tables
            severity, message = _classify(top.detector_id, configured, table_present)
            # Identity needs comparable rows; none means no source column or a row-count mismatch.
            compared = fact.comparable_rows > 0 and configured not in _NO_OP_BY_DESIGN
            rate = fact.identical_rows / fact.comparable_rows if compared else None
            if (
                rate is not None
                and configured in _WHOLE_CELL_DESTROYS
                and all(d.detector_id in NAME_HINT_GATED_DETECTORS for d in fact.detectors)
            ):
                # Every hit is a loose regex held back by a column-name hint, so the source
                # comparison, not the hit, says whether the mask fired.
                severity, message = _grade_gated(
                    identical_rows=fact.identical_rows,
                    comparable_rows=fact.comparable_rows,
                    detector_id=top.detector_id,
                    strategy=str(configured),
                )
            elif rate is not None:
                override = _escalate(
                    configured=configured,
                    identity_rate=rate,
                    identical_count=fact.identical_rows,
                    # An uncounted source distinct is unknown, not constant: keep it above the
                    # constant-source cutoff so the valid identity rate still decides. A failed
                    # output count says nothing about the source.
                    src_distinct=max(fact.source_distinct, 2)
                    if fact.source_distinct_failed
                    else fact.source_distinct,
                    detector_confidence=top.confidence,
                    detector_id=top.detector_id,
                    table_present=table_present,
                )
                if override is not None and (
                    _SEVERITY_ORDER[override[0]] > _SEVERITY_ORDER[severity]
                ):
                    severity, message = override
            elif failed_compare:
                # The source comparison could not run, so the escalation this column may need is
                # unknown. Say so at error severity rather than report a clean "not compared".
                severity = "error"
                message = _compare_raised(top.detector_id, str(fact.identity_error))
            findings.append(
                ResidualPIIFinding(
                    table=table_name,
                    column=col_name,
                    detector_id=top.detector_id,
                    match_rate=top.match_rate,
                    severity=severity,
                    configured_strategy=configured,
                    sample_match_count=int(top.match_rate * fact.output_rows),
                    message=message,
                    source_identity_rate=rate,
                    source_compared=rate is not None,
                )
            )
    return findings
