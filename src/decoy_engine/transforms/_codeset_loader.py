"""Corpus file I/O, caching, and provenance validation for code_set (HC-1 slice 1).

Split out of ``transforms/code_set.py`` to keep that module under its LOC cap
(``CLAUDE.md``: "Use established methodology" + orchestration-module size
discipline). This module owns the low-level "read a Parquet file off disk,
validate it, cache it" concern; ``code_set.py`` owns the strategy-level
concepts (``CodeSetConfig``, HMAC-keyed selection, chapter_preserve) and the
config-aware wrapper (``describe_loaded_corpus``) that needs both.

Pattern: Parquet key/value metadata carries provenance (see
``transforms/_codeset_provenance.py`` for the ``CodeSetProvenance`` type and
its ``ModelPackManifest``-imitating shape).
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from decoy_engine import fileaccess, reasons
from decoy_engine._config_text import (
    Expected,
    Problem,
    Refusal,
    config_position,
    config_refusal,
    read_config,
)
from decoy_engine._error_base import raise_bare
from decoy_engine.fileaccess import FileAccess, FileAccessDenied, FileHandle, FileRequest, FileRole
from decoy_engine.fileaccess.adapters import arrow as arrow_adapter
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.transforms._codeset_checks import (
    _check_corpus_schema,
    _validate_provenance,
)
from decoy_engine.transforms._codeset_checks import (
    refusal_error as _refusal_error,
)
from decoy_engine.transforms._codeset_index import SelectionIndexes, build_selection_indexes
from decoy_engine.transforms._codeset_provenance import CODESET_REGISTRY, CodeSetProvenance

_LOG = logging.getLogger(__name__)

# Shipped corpora live in this directory.
_CODESETS_DIR = Path(__file__).parent.parent / "codesets"

# Recognised shipped corpus names, derived from the single-source-of-truth
# registry (HC-1 slice 1 item 5; transforms/_codeset_provenance.py).
_SHIPPED_CORPORA = frozenset(CODESET_REGISTRY)
# The names a refusal lists: engine-owned and constant, so they are safe text.
SHIPPED_CORPUS_NAMES: tuple[str, ...] = tuple(sorted(_SHIPPED_CORPORA))

# A shipped name resolves ONLY through this table, to a constant path: membership is checked
# before any file-system call, so a name like "../x" or an absolute stem never reaches one.
_SHIPPED_PATHS: dict[str, Path] = {n: _CODESETS_DIR / f"{n}.parquet" for n in _SHIPPED_CORPORA}


def _read_error(refusal: Refusal) -> PlanCompileError:
    return _refusal_error(reasons.plan.CODE_SET_CORPUS_READ_ERROR, refusal)


def _unknown_shipped_corpus() -> PlanCompileError:
    """The one refusal for a name that is not a registry key; it echoes neither the name nor a
    path."""
    return _refusal_error(
        reasons.plan.CODE_SET_CORPUS_NOT_FOUND,
        config_refusal(
            config_position("provider_config", "code_set"),
            Problem.NOT_FOUND,
            expected=Expected.SHIPPED_NAME,
            choices=SHIPPED_CORPUS_NAMES,
        ),
    )


@dataclass(frozen=True)
class _CorpusRecord:
    """A loaded, validated corpus: rows, provenance, and memoized selection indices.

    Built once per cache key and cached in ``_shipped_cache`` / ``_customer_cache``
    (module-level, HC-1 slice 1). ``selection`` (a ``SelectionIndexes``) is built
    once at load time by ``_codeset_index.build_selection_indexes`` so
    ``code_set``'s per-VALUE candidate selection is O(1) instead of the O(n)
    scan / O(corpus) filter it would otherwise re-run per masked value -- what
    makes an ICD-10-CM-scale (~70k row) corpus viable.
    """

    rows: list[dict[str, Any]]
    provenance: CodeSetProvenance | None
    selection: SelectionIndexes


# Memoized corpus loads. A corpus is read from disk, validated,
# provenance-checked, and chapter-indexed at MOST ONCE per cache key; every
# subsequent apply_code_set call for the same corpus reuses the cached
# record. Without this, every masked VALUE would re-read and re-sort the
# whole Parquet file (fine at 65 rows, a disaster at ICD-10-CM's ~70k).
#
# MEDIUM-1 remediation (HC-1 slice 1 gap): split into two caches with
# different invalidation/eviction policies, because SHIPPED and CUSTOMER
# corpora have different lifetimes.
#
# Shipped corpora are bundled package files, immutable for the life of a
# running process, so a simple resolved-path key is correct AND self-bounds
# in size (CODESET_REGISTRY is a small, fixed set -- 4 corpora today) with
# no eviction needed.
_shipped_cache: dict[str, _CorpusRecord] = {}

# Customer corpora are operator-supplied files at a path the engine does not
# own; the pre-HC-1 code re-read one from disk on every call, so a file
# REPLACED at the same path between jobs was always picked up. Caching by
# path alone (as HC-1 slice 1 originally shipped) silently broke that: a
# replaced file would be served the STALE pre-replacement rows forever
# (correctness), and the cache also grew one entry per distinct path ever
# seen with no eviction (memory, in a long-lived platform worker). Keying on
# (resolved_path, mtime_ns, ctime_ns, size) makes a same-path file
# replacement mint a new cache entry automatically, and bounding it as an
# LRU (OrderedDict, move-to-end on hit, evict-oldest on overflow) caps
# worst-case memory for a worker that processes many distinct customer
# corpus files over its lifetime.
#
# Codex P2 CUSTOMER CACHE SAME-MTIME+SAME-SIZE STALENESS remediation:
# mtime+size alone under-identifies a file. A coarse-timestamp filesystem
# (1s or 2s resolution, common on some network/Windows mounts) or tooling
# that explicitly restores the original mtime after writing (rsync
# --times, some backup/deploy tooling) can produce a replacement file that
# keeps the exact same mtime, and a same-length replacement keeps the same
# size -- the old key then silently reuses the stale cached rows. ``ctime``
# (inode change time; POSIX st_ctime, or Windows' "last metadata change" on
# platforms without POSIX ctime semantics) updates on content write AND on
# metadata-only operations like ``rename``/``utime``, closing the common
# case: even a same-path replace that deliberately re-stamps mtime still
# bumps ctime because the re-stamping utime() call is itself a metadata
# change. This is still best-effort file identity, not a content hash --
# hashing every customer corpus (up to ICD-10-CM scale, ~70k rows) on every
# load would defeat the point of caching it.
_CUSTOMER_CACHE_MAX_ENTRIES = 32
_customer_cache: OrderedDict[tuple[str, int, int, int], _CorpusRecord] = OrderedDict()


def _open_customer(path: Path) -> FileHandle:
    """The policy's handle for a customer corpus; the config position is named, never the path."""
    return fileaccess.current().open_read(
        FileRequest(
            FileRole.CORPUS, "read", str(path), fileaccess.position_key("code_set.corpus_source")
        )
    )


@fileaccess.entry_point
def load_corpus(
    name: str, path: Path | None = None, *, file_access: FileAccess | None = None
) -> list[dict[str, Any]]:
    """Load a corpus Parquet file and return rows as a sorted list of dicts.

    Rows are sorted ascending by ``code`` to establish a stable, file-order-
    independent ordering for HMAC-keyed access (same principle as the
    ReferenceTable.keyed_row id-sort in SP-06).

    Args:
        name: Corpus name (e.g. "icd10"). Used only for error messages when
            path is provided by the caller.
        path: Override path. When None, loads from the shipped codesets dir.

    Returns:
        List of row dicts with at least a ``code`` key. A fresh list AND
        fresh row dicts per call (NIT-2 remediation: neither the returned
        list nor its row dicts are the cached objects), so mutating the
        returned rows -- the list, or an individual row's fields -- never
        corrupts the shared cache record another caller reads next.

    Raises:
        PlanCompileError: File not found, not readable, missing ``code``
            column, corpus is empty, or (HC-1) a shipped corpus is missing
            required provenance metadata (``code_set_corpus_missing_
            provenance``).
    """
    record = _get_corpus_record(name, path, is_shipped=path is None)
    return [dict(row) for row in record.rows]


@fileaccess.entry_point
def load_corpus_provenance(
    name: str, path: Path | None = None, *, file_access: FileAccess | None = None
) -> CodeSetProvenance | None:
    """Return the parsed provenance for a corpus (HC-1 slice 1).

    Shares the module cache with :func:`load_corpus`, so calling this before
    or after ``load_corpus`` for the same corpus costs no extra I/O. Same
    fail-closed (shipped) / warn (customer) validation as corpus loading in
    general -- see :func:`_validate_provenance`.

    Args:
        name: Corpus name (e.g. "icd10").
        path: Override path. When None, loads from the shipped codesets dir.

    Returns:
        The corpus's ``CodeSetProvenance``, or ``None`` if the corpus (a
        customer corpus only -- a shipped corpus without provenance raises)
        has no provenance metadata at all.
    """
    record = _get_corpus_record(name, path, is_shipped=path is None)
    return record.provenance


def _resolve_read_path(name: str, path: Path | None) -> Path:
    """Resolve the corpus path to read.

    Preserves the pre-HC-1 error semantics exactly: a missing SHIPPED corpus
    raises ``code_set_corpus_not_found``; a missing CUSTOMER path raises
    ``code_set_corpus_path_not_found``. Called on every access (a cheap
    ``Path.exists()`` stat), independent of the cache, so a corpus deleted
    between calls is still caught -- only the expensive read+parse+sort is
    memoized.
    """
    if path is None:
        if not isinstance(name, str) or name not in _SHIPPED_PATHS:
            raise _unknown_shipped_corpus()
        shipped = _SHIPPED_PATHS[name]
        if not shipped.exists():
            raise_bare(
                _refusal_error(
                    reasons.plan.CODE_SET_CORPUS_NOT_FOUND,
                    config_refusal(
                        config_position("provider_config", "code_set"),
                        Problem.NOT_FOUND,
                        choices=SHIPPED_CORPUS_NAMES,
                        hint="A registered shipped corpus file is missing from this installation",
                    ),
                )
            )
        return shipped

    absent = False
    handle = _open_customer(path)
    try:
        handle.stat()
    except (FileNotFoundError, NotADirectoryError):
        absent = True
    finally:
        handle.close()
    if absent:
        raise_bare(
            _refusal_error(
                reasons.plan.CODE_SET_CORPUS_PATH_NOT_FOUND,
                config_refusal(
                    config_position("provider_config", "corpus_source"),
                    Problem.NOT_FOUND,
                    expected=Expected.FILE,
                ),
            )
        )
    return path


def _get_corpus_record(
    name: str,
    path: Path | None,
    *,
    is_shipped: bool,
    expected_source_version: str | None = None,
) -> _CorpusRecord:
    """Return the cached (or freshly-read) ``_CorpusRecord`` for this corpus.

    MEDIUM-1 remediation (HC-1 slice 1 gap): shipped corpora cache on the
    resolved path alone (bundled + immutable, see ``_shipped_cache``'s module
    comment); customer corpora additionally key on ``(mtime_ns, ctime_ns,
    size)`` so a file replaced at the same path between calls invalidates
    automatically (Codex P2 remediation: ``ctime`` closes the case where a
    same-size replacement is deliberately re-stamped with the original
    mtime -- see ``_customer_cache``'s module comment), in a bounded LRU
    (``_customer_cache``) so the cache cannot grow without bound over a
    long-lived process's lifetime.

    ``expected_source_version`` (HC-2 D2a) is checked on EVERY call, cache
    hit or miss: the pin is a property of the CALLER's config, not of the
    cached bytes on disk, so two callers hitting the SAME cached record with
    different expectations (or none) must each be checked independently
    rather than only at the point the record is first read from disk.
    """
    resolved = _resolve_read_path(name, path)
    if is_shipped:
        # A registry-resolved corpus keys on its name (no file-system call); an explicit path
        # (an internal caller's override) keeps the resolved-path key.
        resolved_str = name if path is None else str(resolved.resolve())
        cached = _shipped_cache.get(resolved_str)
        if cached is not None:
            record = cached
        else:
            record = _read_corpus_record(name, resolved, is_shipped=True)
            _shipped_cache[resolved_str] = record
        _check_source_version_pin(name, resolved, record, expected_source_version)
        return record

    # A customer corpus can disappear or become unreadable between
    # `_resolve_read_path`'s existence check and this stat (TOCTOU). Translate
    # the bare OSError to the loader's typed error contract (load_corpus
    # documents PlanCompileError for missing/unreadable corpora) instead of
    # leaking FileNotFoundError/PermissionError. The handle is opened first so the
    # policy decides before any cache lookup: a cached record is never served to a
    # request the policy refuses.
    handle = _open_customer(resolved)
    try:
        gone = False
        stat = None
        try:
            stat = read_config(
                handle.stat,
                config_position("provider_config", "corpus_source"),
                _read_error,
                passes=(FileNotFoundError,),
            )
        except FileNotFoundError:
            gone = True
        if gone:
            raise_bare(
                _refusal_error(
                    reasons.plan.CODE_SET_CORPUS_PATH_NOT_FOUND,
                    config_refusal(
                        config_position("provider_config", "corpus_source"),
                        Problem.NOT_FOUND,
                        expected=Expected.FILE,
                        hint="The corpus became unavailable after the existence check",
                    ),
                )
            )
        assert stat is not None  # noqa: S101 - read_config returned a value, or raised
        # Best-effort file identity, not a content hash (see the module-level
        # comment on `_customer_cache` for why ctime is included and a hash is
        # not).
        cache_key = (handle.identity(), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        cached = _customer_cache.get(cache_key)
        if cached is not None:
            _customer_cache.move_to_end(cache_key)  # LRU: mark as most recently used.
            record = cached
        else:
            record = _read_corpus_record(name, resolved, is_shipped=False, handle=handle)
            _customer_cache[cache_key] = record
            if len(_customer_cache) > _CUSTOMER_CACHE_MAX_ENTRIES:
                _customer_cache.popitem(last=False)  # evict the least-recently-used entry.
    finally:
        handle.close()
    _check_source_version_pin(name, resolved, record, expected_source_version)
    return record


def _check_source_version_pin(
    name: str,
    path: Path | None,
    record: _CorpusRecord,
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
        raise_bare(
            _refusal_error(
                reasons.plan.CODE_SET_CORPUS_VERSION_MISMATCH,
                config_refusal(
                    config_position("provider_config", "corpus_source_version"),
                    Problem.MISMATCH,
                    hint=(
                        "The corpus at this name or path has changed since the plan was "
                        "authored, or never carried the pinned release. Update "
                        "corpus_source_version to match the corpus you intend to use, or "
                        "remove the pin to accept whatever is loaded"
                    ),
                ),
            )
        )


def _read_corpus_record(
    name: str, path: Path, *, is_shipped: bool, handle: FileHandle | None = None
) -> _CorpusRecord:
    """Internal: read, validate, and index a corpus from disk (uncached).

    Validation is execution-time, pre-mutation (fail-closed). No data is
    mutated before this check. Invalid corpora raise PlanCompileError. A shipped
    corpus is package data the engine owns; any other path is read through the
    handle the caller's policy issued.
    """
    if handle is None:
        handle = fileaccess.engine_handle(path) if is_shipped else _open_customer(path)
        owned = True
    else:
        owned = False

    def _load() -> _CorpusRecord:
        # Read, check the schema, then convert: a corpus that fails the schema check is refused
        # on its own fault before any unrelated cell is converted. Reading and every
        # materialization run inside `read_config`, so a library failure is a value-free refusal.
        tbl = arrow_adapter.read_table(handle)
        _check_corpus_schema(tbl)

        # Build row dicts and sort by code for stable HMAC-keyed access.
        columns = tbl.schema.names
        rows: list[dict[str, Any]] = []
        for i in range(tbl.num_rows):
            row = {col: tbl.column(col)[i].as_py() for col in columns}
            rows.append(row)

        rows.sort(key=lambda r: str(r["code"]))

        # HC-1 slice 1/2: memoized selection indices, built once instead of
        # re-derived / re-filtered per masked VALUE by code_set.py's selection.
        selection = build_selection_indexes(rows)

        provenance = CodeSetProvenance.from_parquet_metadata(tbl)
        _validate_provenance(name, provenance, is_shipped=is_shipped)

        return _CorpusRecord(rows=rows, provenance=provenance, selection=selection)

    try:
        return read_config(
            _load,
            config_position("provider_config", "corpus_source"),
            _read_error,
            passes=(FileAccessDenied, PlanCompileError),
        )
    finally:
        if owned:
            handle.close()


# ── Standalone verification primitive (HC-2 item 1) ──────────────────────────


@dataclass(frozen=True)
class CorpusVerifyReport:
    """Structured result of validating a corpus Parquet file (HC-2).

    Attributes:
        ok: True when the corpus passed every check.
        path: The verified file's path, as given (for display; not resolved).
        row_count: Row count on success. Always 0 on failure (``ok=False``):
            validation raises at the first failed check, before a row count is
            returned, so a partially-read corpus reports 0 rather than a
            possibly-misleading partial count.
        provenance: A counts/identifiers-only provenance summary -- the same
            shape ``describe_loaded_corpus`` stamps into evidence, never raw
            codes. ``None`` when the corpus carries no provenance stamp, or
            failed before provenance could be read.
        problems: Coded, human-readable failure descriptions
            (``"<PlanCompileError.code>: <message>"``). Empty when ``ok``.
    """

    ok: bool
    path: str
    row_count: int
    provenance: dict[str, Any] | None
    problems: tuple[str, ...] = ()


@fileaccess.entry_point
def verify_corpus(path: Path, *, file_access: FileAccess | None = None) -> CorpusVerifyReport:
    """Validate a corpus Parquet file without running a masking job.

    Runs the EXACT same schema check (:func:`_check_corpus_schema`) and
    provenance validation (:func:`_validate_provenance`) the load path runs
    in :func:`_read_corpus_record` -- the single validation source of truth
    the CLI ``codesets verify``/``add`` and the platform upload check call
    (both live in sibling repos; this is the primitive they call into).
    Treats the file as a CUSTOMER corpus (``is_shipped=False``): a file under
    review for upload has no registered shipped name to identity-check
    against, and the shipped-only strictness (identity match, ``is_seed``,
    metadata format version) does not apply to it.

    Unlike :func:`_read_corpus_record`, this NEVER raises
    :class:`PlanCompileError` -- that is the point of a standalone,
    non-job-fatal check: every coded failure is caught and translated into
    ``problems`` instead of propagating. Does not use the module cache (a
    corpus under review is not yet a job's corpus).

    Args:
        path: Path to the corpus Parquet file to verify. A ``str`` is accepted
            and coerced (the "never raises" contract must hold for a path-like
            string too, not only a ``Path``).

    Returns:
        A :class:`CorpusVerifyReport`. ``ok=False`` on any failure (unreadable
        file, missing/empty/duplicate/null code column, incomplete
        provenance, ...); ``problems`` names exactly what failed.
    """
    path = Path(path)
    name = path.stem
    try:
        record = _read_corpus_record(name, path, is_shipped=False)
    except PlanCompileError as exc:
        return CorpusVerifyReport(
            ok=False,
            path=str(path),
            row_count=0,
            provenance=None,
            problems=(f"{exc.code}: {exc.message}",),
        )

    prov = record.provenance
    summary = (
        {
            "source": prov.source,
            "source_version": prov.source_version,
            "effective_date": prov.effective_date,
            "license": prov.license,
            "is_seed": prov.is_seed,
        }
        if prov is not None
        else None
    )
    return CorpusVerifyReport(
        ok=True,
        path=str(path),
        row_count=len(record.rows),
        provenance=summary,
        problems=(),
    )
