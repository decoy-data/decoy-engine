"""Outward text for code_set corpora: the one place a corpus path or label becomes a message.

Every message, log argument, report field and evidence field that names a corpus path or label
goes through `where` (the redacted location) or `_corpus_label`. File-supplied provenance
values never enter error text (only the offending field's name does) and are stripped of URL
credentials on the success path. `tests/sentry/test_corpus_label_single_formatter.py` fails a
new call site that formats these any other way.
"""

from __future__ import annotations

import logging
from typing import Any

import pyarrow as pa

from decoy_engine import fileaccess, reasons
from decoy_engine.plan._errors import (
    PlanCompileError,  # `decoy_engine.plan` itself imports this module chain
)
from decoy_engine.transforms._codeset_provenance import (
    SHIPPED_CORPUS_NAMES as _SHIPPED_CORPORA,
)
from decoy_engine.transforms._codeset_provenance import CodeSetProvenance

_LOG = logging.getLogger("decoy_engine.transforms._codeset_loader")


def _where(locator: object) -> str:
    """How a diagnostic names a corpus file: the redacted path (CLI) or the config position."""
    text = "<no path>" if locator is None else str(locator)
    return fileaccess.shown(text, "code_set.corpus_source")


def _corpus_label(name: str) -> str:
    """The one formatter for a corpus label in a message, report or evidence field: a registered
    shipped name as is, any other label (configured text, maybe a URL) under the policy."""
    return name if name in _SHIPPED_CORPORA else fileaccess.shown(name, "code_set.code_set")


def _unknown_shipped_corpus() -> PlanCompileError:
    """The one message for a name that is not a registry key; it echoes neither the name nor a
    path."""
    return PlanCompileError(
        code=reasons.plan.CODE_SET_CORPUS_NOT_FOUND,
        path="provider_config.code_set",
        message=(
            "shipped corpus name is not one of the registered corpora. "
            f"Available: {sorted(_SHIPPED_CORPORA)}."
        ),
    )


def _check_source_version_pin(
    name: str,
    shown: str | None,
    record: Any,
    expected_source_version: str | None,
) -> None:
    """Fail closed when a config-pinned corpus release does not match (HC-2 D2a).

    ``corpus_source_version`` (``CodeSetConfig``) is the plan author's
    declared expectation of the corpus's SOURCE release id (e.g. "FY2024"),
    independently verified here against the release actually embedded in the
    loaded file's provenance (``CodeSetProvenance.source_version``). This is
    distinct from ``corpus_version`` / ``CORPUS_METADATA_VERSION``, which is
    the metadata FORMAT, not the source's release. Runs for BOTH shipped and
    customer corpora: a shipped corpus update and a customer swapping in a
    different release must fail exactly the same way. Unset (None) is a
    no-op -- today's unpinned behavior is unchanged.
    """
    if expected_source_version is None:
        return
    actual = record.provenance.source_version if record.provenance else ""
    if actual != expected_source_version:
        at = f" at {shown}" if shown is not None else ""
        raise PlanCompileError(
            code=reasons.plan.CODE_SET_CORPUS_VERSION_MISMATCH,
            path="provider_config.corpus_source_version",
            message=(
                f"corpus {_corpus_label(name)!r}{at}: "
                "corpus_source_version does not match the "
                "loaded corpus's embedded source_version. The corpus at this name/path has "
                "changed since the plan was authored (or never carried the pinned "
                "release). Update corpus_source_version to match the corpus you "
                "intend to use, or remove the pin to accept whatever is loaded."
            ),
        )


def _check_corpus_schema(tbl: pa.Table, where: str) -> None:
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
    if "code" not in tbl.schema.names:
        raise PlanCompileError(
            code=reasons.plan.CODE_SET_CORPUS_MISSING_CODE_COLUMN,
            path="provider_config.corpus_source",
            message=(
                f"corpus at {where} is missing required 'code' column. "
                f"Customer corpora must have a 'code' (string) column. "
                f"The file has {len(tbl.schema.names)} column(s); their names are not listed."
            ),
        )

    if tbl.num_rows == 0:
        raise PlanCompileError(
            code=reasons.plan.CODE_SET_CORPUS_EMPTY,
            path="provider_config.corpus_source",
            message=f"corpus at {where} has 0 rows. Corpus must be non-empty.",
        )

    code_col = tbl.column("code")
    if code_col.null_count > 0:
        raise PlanCompileError(
            code=reasons.plan.CODE_SET_CORPUS_NULL_CODE,
            path="provider_config.corpus_source",
            message=(
                f"corpus at {where} has {code_col.null_count} null value(s) in the "
                "'code' column. Every row must carry a code."
            ),
        )

    # str() every value up front: codes are treated as strings everywhere
    # downstream (sorting, HMAC keying), so duplicate/empty detection must
    # compare on the same representation, not the raw Arrow-decoded type.
    codes = [str(c) for c in code_col.to_pylist()]

    empty = sum(1 for c in codes if c.strip() == "")
    if empty:
        raise PlanCompileError(
            code=reasons.plan.CODE_SET_CORPUS_EMPTY_CODE,
            path="provider_config.corpus_source",
            message=(
                f"corpus at {where} has {empty} empty-string value(s) in the 'code' "
                "column. Every code must be a non-empty string."
            ),
        )

    duplicates = len(codes) - len(set(codes))
    if duplicates:
        raise PlanCompileError(
            code=reasons.plan.CODE_SET_CORPUS_DUPLICATE_CODES,
            path="provider_config.corpus_source",
            message=(
                f"corpus at {where} has {duplicates} duplicate code value(s). code_set "
                "requires unique codes: HMAC-keyed candidate selection assumes a 1:1 "
                "code -> row mapping, and a duplicate makes selection ambiguous."
            ),
        )

    if "chapter" in tbl.schema.names:
        chapters = tbl.column("chapter").to_pylist()
        incoherent = sum(1 for c in chapters if c is None or str(c).strip() == "")
        if incoherent:
            raise PlanCompileError(
                code=reasons.plan.CODE_SET_CORPUS_INCOHERENT_CHAPTER,
                path="provider_config.corpus_source",
                message=(
                    f"corpus at {where} has {incoherent} row(s) with a null/empty "
                    "'chapter' value. A corpus that has a 'chapter' column must "
                    "populate it for every row (chapter_preserve assumes full coverage)."
                ),
            )


def _validate_provenance(
    name: str, where: str, provenance: CodeSetProvenance | None, *, is_shipped: bool
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
    if provenance is None:
        if is_shipped:
            raise PlanCompileError(
                code=reasons.plan.CODE_SET_CORPUS_MISSING_PROVENANCE,
                path="provider_config.code_set",
                message=(
                    f"shipped corpus {_corpus_label(name)!r} at {where} has no provenance metadata "
                    "(source, source_version, effective_date, license). This is a "
                    "packaging defect, not a customer-corpus configuration issue."
                ),
            )
        _LOG.warning(
            "customer code_set corpus %r at %s has no provenance metadata "
            "(source, source_version, effective_date, license). Provenance is "
            "optional for customer corpora but recommended for audit evidence.",
            _corpus_label(name),
            where,
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
            # The embedded id is file text: shown only when it is a registered corpus name.
            other = provenance.corpus
            embedded = f" ({other!r})" if other in _SHIPPED_CORPORA else ""
            raise PlanCompileError(
                code=reasons.plan.CODE_SET_CORPUS_PROVENANCE_IDENTITY_MISMATCH,
                path="provider_config.code_set",
                message=(
                    f"shipped corpus {_corpus_label(name)!r} at {where} carries provenance "
                    f"for a different corpus{embedded}. This "
                    "looks like a packaging or metadata swap; the embedded "
                    "provenance.corpus must match the requested corpus name."
                ),
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
            stamp_defects = [d.split(" ", 1)[0] for d in provenance.shipped_stamp_defects()]
            if stamp_defects:
                raise PlanCompileError(
                    code=reasons.plan.CODE_SET_CORPUS_PROVENANCE_MALFORMED_STAMP,
                    path="provider_config.code_set",
                    message=(
                        f"shipped corpus {_corpus_label(name)!r} at {where} has a malformed "
                        f"provenance stamp (fields: {', '.join(stamp_defects)}). A "
                        "shipped corpus is a build artifact: is_seed and the "
                        "metadata format version must be explicit and current "
                        "so evidence cannot misreport a seed as a full corpus."
                    ),
                )
        return
    if is_shipped:
        raise PlanCompileError(
            code=reasons.plan.CODE_SET_CORPUS_MISSING_PROVENANCE,
            path="provider_config.code_set",
            message=(
                f"shipped corpus {_corpus_label(name)!r} at {where} has incomplete provenance "
                f"metadata (missing: {', '.join(missing)})."
            ),
        )
    raise PlanCompileError(
        code=reasons.plan.CODE_SET_CORPUS_MISSING_PROVENANCE,
        path="provider_config.corpus_source",
        message=(
            f"customer corpus {_corpus_label(name)!r} at {where} has partial provenance metadata "
            f"(missing: {', '.join(missing)}). Either remove the partial stamp or "
            "complete it; a half-filled provenance block is not surfaced as evidence."
        ),
    )


def _publishable(text: str) -> str:
    """A provenance text field is published only when it carries no URL or credential marker
    (`@`, `?`, `#`); otherwise it is withheld whole, since the stamp is file-supplied."""
    return "<redacted>" if any(mark in text for mark in ("@", "?", "#")) else text


def provenance_summary(prov: CodeSetProvenance | None) -> dict[str, Any] | None:
    """Identifiers of a provenance stamp for evidence and the verify report. Each text field
    passes `_publishable`."""
    if prov is None:
        return None
    return {
        "source": _publishable(prov.source),
        "source_version": _publishable(prov.source_version),
        "effective_date": _publishable(prov.effective_date),
        "license": _publishable(prov.license),
        "is_seed": prov.is_seed,
    }


def corpus_stat_error(exc: OSError, shown: str) -> PlanCompileError:
    """The one translation of an OSError from the customer corpus stat.

    A missing path (or a parent that is not a directory) is `path_not_found`; anything else is
    `read_error` naming only the exception type. The caller raises the result after its
    `except` block closes, so the error carries no `__context__`."""
    if isinstance(exc, (FileNotFoundError, NotADirectoryError)):
        return PlanCompileError(
            code=reasons.plan.CODE_SET_CORPUS_PATH_NOT_FOUND,
            path="provider_config.corpus_source",
            message=f"customer corpus not found at path {shown}.",
        )
    return PlanCompileError(
        code=reasons.plan.CODE_SET_CORPUS_READ_ERROR,
        path="provider_config.corpus_source",
        message=f"failed to stat customer corpus at {shown} ({type(exc).__name__}).",
    )
