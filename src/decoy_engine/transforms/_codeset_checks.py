"""Corpus schema and provenance checks for code_set (split from `_codeset_loader`).

One checker with two callers: the load path (`_codeset_loader._read_corpus_record`) and the
standalone `verify_corpus`, so a corpus can never pass one and fail the other. Every refusal is
built by `config_refusal`: it names the field and the problem, never a column name, a file name
or a value from the corpus.
"""

from __future__ import annotations

import logging

import pyarrow as pa

from decoy_engine import reasons
from decoy_engine._config_text import (
    Expected,
    Name,
    Problem,
    Refusal,
    config_position,
    config_refusal,
)
from decoy_engine._error_base import raise_bare
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.transforms._codeset_provenance import CodeSetProvenance

_LOG = logging.getLogger(__name__)


def refusal_error(code: str, refusal: Refusal) -> PlanCompileError:
    """The compile error for `refusal`: its key as the path, its detail as the message."""
    return PlanCompileError(code=code, path=refusal.key, message=refusal.detail)


def _check_corpus_schema(tbl: pa.Table) -> None:
    """Generic, corpus-agnostic schema invariants (HC-2 D2c).

    Shared by the load path (:func:`_read_corpus_record`) and the standalone
    :func:`verify_corpus` primitive, so a corpus can never pass one and fail
    the other -- ONE checker, two callers. Deliberately corpus-agnostic: a
    ``code`` column that is present, non-null, non-empty, and unique, plus
    (only when the column exists) a ``chapter`` column that is populated for
    every row. Code-system-specific regexes and a mandatory ``description``
    column are deferred to HC-1 slice 2, when the real full corpora (each
    with its own per-system format conventions) land.
    """
    at_corpus = config_position("provider_config", "corpus_source")
    if "code" not in tbl.schema.names:
        raise_bare(
            refusal_error(
                reasons.plan.CODE_SET_CORPUS_MISSING_CODE_COLUMN,
                config_refusal(
                    at_corpus,
                    Problem.MISSING,
                    expected=Expected.CODE_COLUMN,
                    hint="Customer corpora must have a 'code' string column",
                ),
            )
        )

    if tbl.num_rows == 0:
        raise_bare(
            refusal_error(
                reasons.plan.CODE_SET_CORPUS_EMPTY,
                config_refusal(
                    at_corpus, Problem.EMPTY, hint="The corpus has 0 rows and must be non-empty"
                ),
            )
        )

    code_col = tbl.column("code")
    if code_col.null_count > 0:
        raise_bare(
            refusal_error(
                reasons.plan.CODE_SET_CORPUS_NULL_CODE,
                config_refusal(
                    at_corpus,
                    Problem.NOT_ALLOWED,
                    hint="The 'code' column holds null values. Every row must carry a code",
                ),
            )
        )

    # str() every value up front: codes are treated as strings everywhere
    # downstream (sorting, HMAC keying), so duplicate/empty detection must
    # compare on the same representation, not the raw Arrow-decoded type.
    codes = [str(c) for c in code_col.to_pylist()]

    empty = sum(1 for c in codes if c.strip() == "")
    if empty:
        raise_bare(
            refusal_error(
                reasons.plan.CODE_SET_CORPUS_EMPTY_CODE,
                config_refusal(
                    at_corpus,
                    Problem.NOT_ALLOWED,
                    hint="The 'code' column holds empty strings. Every code must be non-empty",
                ),
            )
        )

    duplicates = len(codes) - len(set(codes))
    if duplicates:
        raise_bare(
            refusal_error(
                reasons.plan.CODE_SET_CORPUS_DUPLICATE_CODES,
                config_refusal(
                    at_corpus,
                    Problem.DUPLICATE,
                    hint=(
                        "code_set requires unique codes: HMAC-keyed candidate selection "
                        "assumes a 1:1 code to row mapping, and a duplicate makes selection "
                        "ambiguous"
                    ),
                ),
            )
        )

    if "chapter" in tbl.schema.names:
        chapters = tbl.column("chapter").to_pylist()
        incoherent = sum(1 for c in chapters if c is None or str(c).strip() == "")
        if incoherent:
            raise_bare(
                refusal_error(
                    reasons.plan.CODE_SET_CORPUS_INCOHERENT_CHAPTER,
                    config_refusal(
                        at_corpus,
                        Problem.NOT_ALLOWED,
                        hint=(
                            "Some rows have a null or empty 'chapter'. A corpus that has a "
                            "'chapter' column must populate it for every row "
                            "(chapter_preserve assumes full coverage)"
                        ),
                    ),
                )
            )


def _validate_provenance(
    name: str, provenance: CodeSetProvenance | None, *, is_shipped: bool
) -> None:
    """Fail-closed for shipped corpora; warn for customer corpora (HC-1 slice 1).

    A shipped corpus without a complete provenance stamp (source,
    source_version, effective_date, license) is a packaging defect: the
    engine ships it, so it must be able to say where the codes came from.
    A customer corpus may legitimately have no provenance metadata at all
    (it is not required for the strategy to function); if the operator did
    stamp it, the stamp must be complete -- a half-filled provenance block
    is worse than none, since it looks authoritative but is not.
    """
    at_corpus = config_position("provider_config", "corpus_source")
    at_name = config_position("provider_config", "code_set")
    if provenance is None:
        if is_shipped:
            raise_bare(
                refusal_error(
                    reasons.plan.CODE_SET_CORPUS_MISSING_PROVENANCE,
                    config_refusal(
                        at_name,
                        Problem.MISSING,
                        names=(Name(name),),
                        hint=(
                            "The shipped corpus has no provenance metadata (source, "
                            "source_version, effective_date, license). This is a packaging "
                            "defect, not a customer-corpus configuration issue"
                        ),
                    ),
                )
            )
        _LOG.warning(
            "customer code_set corpus %r at %s has no provenance metadata "
            "(source, source_version, effective_date, license). Provenance is "
            "optional for customer corpora but recommended for audit evidence.",
            name,
            "code_set.corpus_source",
        )
        return

    missing = provenance.missing_required_fields()
    if not missing:
        # Codex round-5 P2 SHIPPED PROVENANCE IDENTITY UNVERIFIED
        # remediation: a complete provenance stamp is not proof the stamp
        # belongs to THIS corpus. A packaging/metadata mistake (or a
        # deliberate swap) can ship `icd10.parquet` carrying `mcc`'s
        # embedded `decoy_corpus` metadata; the completeness check above
        # passes either way, so `describe_loaded_corpus` would report
        # `code_set: icd10` with MCC's attribution as if it were genuine.
        # Shipped-only: a customer corpus's provenance is optional and may
        # legitimately name a different embedded id (e.g. a customer's own
        # code_set built from a shipped seed), so this identity check does
        # not apply to the customer path.
        if is_shipped and provenance.corpus != name:
            raise_bare(
                refusal_error(
                    reasons.plan.CODE_SET_CORPUS_PROVENANCE_IDENTITY_MISMATCH,
                    config_refusal(
                        at_name,
                        Problem.MISMATCH,
                        names=(Name(name),),
                        hint=(
                            "The shipped corpus carries provenance for a different corpus. "
                            "This looks like a packaging or metadata swap; the embedded "
                            "provenance.corpus must match the requested corpus name"
                        ),
                    ),
                )
            )
        # Codex round-7 P2 remediation: the required-field check above does
        # not cover is_seed or the metadata format version, so a shipped
        # corpus with all four required fields but an absent/garbled is_seed
        # (silently coerced to False -> evidence reports a seed as a full
        # corpus) or a stale corpus_version slipped through. Shipped corpora
        # are our own build artifacts; those are packaging defects, fail
        # closed. Customer corpora are exempt (they may omit is_seed and never
        # carry our corpus_version).
        if is_shipped:
            stamp_defects = provenance.shipped_stamp_defects()
            if stamp_defects:
                raise_bare(
                    refusal_error(
                        reasons.plan.CODE_SET_CORPUS_PROVENANCE_MALFORMED_STAMP,
                        config_refusal(
                            at_name,
                            Problem.NOT_ALLOWED,
                            names=(Name(name),),
                            hint=(
                                "The shipped corpus has a malformed provenance stamp. A "
                                "shipped corpus is a build artifact: is_seed and the "
                                "metadata format version must be explicit and current "
                                "so evidence cannot misreport a seed as a full corpus"
                            ),
                        ),
                    )
                )
        return
    if is_shipped:
        raise_bare(
            refusal_error(
                reasons.plan.CODE_SET_CORPUS_MISSING_PROVENANCE,
                config_refusal(
                    at_name,
                    Problem.MISSING,
                    names=(Name(name),),
                    hint=(
                        "The shipped corpus has incomplete provenance metadata. "
                        "Required: source, source_version, effective_date, license"
                    ),
                ),
            )
        )
    raise_bare(
        refusal_error(
            reasons.plan.CODE_SET_CORPUS_MISSING_PROVENANCE,
            config_refusal(
                at_corpus,
                Problem.MISSING,
                names=(Name(name),),
                hint=(
                    "The customer corpus has partial provenance metadata. Required: "
                    "source, source_version, effective_date, license. Either remove the "
                    "partial stamp or complete it; a half-filled provenance block is not "
                    "surfaced as evidence"
                ),
            ),
        )
    )
