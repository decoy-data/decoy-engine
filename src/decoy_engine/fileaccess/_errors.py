"""Denial hygiene: field-key encoding and boundary scrubbing.

A denial names only a config position, escaped and bounded so a table or column name
carrying control characters cannot forge a log line (CWE-117) and no locator, path,
basename or third-party error text rides with it (CWE-209).
"""

from __future__ import annotations

import errno
import os
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Literal, NewType, TypeVar

from decoy_engine.fileaccess._types import (
    DenialKind,
    FileAccessDenied,
    FileAccessReadError,
    FileAccessUnavailable,
)

EncodedKey = NewType("EncodedKey", str)

_MAX_KEY = 256
_TRUNCATED = "...[truncated]"
T = TypeVar("T")
_RESOURCE_ERRNOS = frozenset({errno.ENOSPC, errno.EDQUOT, errno.ENOMEM})
_CHAIN_DEPTH = 16

# The one value-free text for a memory failure the engine recognises by wording. It matches the
# worker's `Wrapping \S+ failed` pattern, so a rebuilt error still classifies as out of memory.
MEMORY_TEXT = "Unknown error: Wrapping <value> failed"

# A descriptor path (`/proc/self/fd/<n>`, `/dev/fd/<n>`) is the locator a strict policy hands a
# library. The specific one is redacted by pair, but a third-party message may name a different
# fd number than the handle we recorded; any descriptor path is a locator, so collapse the whole
# form (CWE-209). No field position is known for an unrecognized fd, so it goes to a fixed marker.
_FD_PATH_RE = re.compile(r"/proc/self/fd/\d+|/dev/fd/\d+")
_FD_REDACTED = "<redacted>"


def encode_field_key(key: str) -> EncodedKey:
    """Backslash-escape non-printables, then bound to 256 characters with a marker."""
    escaped = "".join(ch if ch.isprintable() and ch != "\\" else _escape(ch) for ch in str(key))
    if len(escaped) > _MAX_KEY:
        escaped = escaped[: _MAX_KEY - len(_TRUNCATED)] + _TRUNCATED
    return EncodedKey(escaped)


def _escape(ch: str) -> str:
    return ch.encode("unicode_escape").decode("ascii")


def deny(field_key: str, *, kind: DenialKind | None = None) -> FileAccessDenied:
    """A fresh denial with nothing chained. Build it outside any `except` that holds a
    library error, and raise it `from None`. `kind` is the optional closed no-follow reason."""
    exc = FileAccessDenied(field_key, kind=kind)
    exc.__suppress_context__ = True
    return exc


def has_denial(exc: BaseException | None) -> bool:
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, FileAccessDenied):
            return True
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return False


def scrub(exc: BaseException) -> BaseException:
    """The exception that may cross a process, API or log boundary.

    A chain that holds a denial becomes one fresh denial with no cause, context or
    traceback (so no frame locals are reachable); anything else is returned as it is."""
    inner: BaseException | None = exc
    seen: set[int] = set()
    while inner is not None and id(inner) not in seen:
        if isinstance(inner, FileAccessDenied):
            fresh = FileAccessDenied(inner.field_key, encoded=True, kind=inner.kind)
            fresh.__cause__ = None
            fresh.__context__ = None
            fresh.__suppress_context__ = True
            return fresh.with_traceback(None)
        seen.add(id(inner))
        inner = inner.__cause__ or inner.__context__
    return exc


def redact_locators(text: str, pairs: Iterable[tuple[str, str]]) -> str:
    """`text` with each locator replaced by the display name given for it.

    For third-party text that names the file it was handed: under a strict policy that is the
    descriptor path (`/proc/self/fd/<n>`) as well as the original locator. Longest first, so a
    locator that contains another is replaced whole. Where locator and display are equal (the
    ambient policy) nothing changes."""
    out = text
    for locator, display in sorted(pairs, key=lambda p: len(p[0]), reverse=True):
        if locator and locator != display:
            out = out.replace(locator, display)
    return _FD_PATH_RE.sub(_FD_REDACTED, out)


def _is_typed_memory(exc: BaseException) -> bool:
    if isinstance(exc, MemoryError):
        return True
    if isinstance(exc, OSError) and exc.errno == errno.ENOMEM:
        return True
    return _is_duckdb_out_of_memory(exc)


def _is_duckdb_out_of_memory(exc: BaseException) -> bool:
    """DuckDB's OOM, recognised by its own class hierarchy so nothing is imported on the failure
    path (a capped worker has no headroom to load DuckDB). The native module raises
    `_duckdb.OutOfMemoryException`; the `duckdb` wrapper re-exports the same class, and either may
    be unloaded when it is raised. Pinned against duckdb 1.5.4, where `__module__` is `_duckdb`."""
    return any(
        cls.__name__ == "OutOfMemoryException"
        and cls.__module__.partition(".")[0] in ("duckdb", "_duckdb")
        for cls in type(exc).__mro__
    )


# The under-cap failure shapes fk_memory_probe documents evidence for: OpenSSL's EVP_MD_CTX copy
# (hashlib, masking the FK key) and Arrow's arrow-to-pandas value conversion raise their own error
# type under a hard cap instead of MemoryError, and glibc's per-thread TLS setup aborts the
# process outright. See fk_memory_probe.py for the reproduction evidence.
MEMORY_ERROR_MARKERS: tuple[str, ...] = (
    "not able to copy ctx",
    "digital envelope routines",
)
MEMORY_ERROR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Unknown error: Wrapping \S+ failed"),
)
GLIBC_TLS_OOM_MARKER = "cannot allocate memory for thread-local data"


def typed_memory_member(exc: BaseException) -> BaseException | None:
    """The first typed memory error in `exc` or its `__cause__`/`__context__` links, else None.

    Native code at the cap can surface exhaustion wrapped: an Arrow cancellation reaches Python
    as `KeyboardInterrupt` raised while a `MemoryError` was being handled. Only the TYPE of each
    link is read, never its message. Bounded and cycle-safe. The one chain walker."""
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending and len(seen) < _CHAIN_DEPTH:
        link = pending.pop()
        if id(link) in seen:
            continue
        seen.add(id(link))
        if _is_typed_memory(link):
            return link
        pending.extend(x for x in (link.__cause__, link.__context__) if x is not None)
    return None


def is_memory_failure(exc: BaseException) -> bool:
    """True iff `exc` is one of the documented under-cap failure shapes.

    The isolated worker calls this to self-classify a caught exception as `oom_killed` (exits 0
    with a clean diagnostic) versus `crashed` (a genuine bug, reported as data in the result
    envelope but NOT hidden behind an OOM label). A typed memory error anywhere in the
    `__cause__`/`__context__` chain counts; a bare `KeyboardInterrupt` with no memory-typed link
    stays `crashed`. Imports nothing, so it is safe at the memory cap."""
    if typed_memory_member(exc) is not None:
        return True
    message = str(exc)
    if any(marker in message for marker in MEMORY_ERROR_MARKERS):
        return True
    return any(pattern.search(message) for pattern in MEMORY_ERROR_PATTERNS)


def is_conversion_memory_failure(exc: BaseException) -> bool:
    """True iff `exc` from an Arrow-to-pandas conversion is a memory failure: a typed memory
    error in its chain, or Arrow's own `Wrapping <cell> failed` text. The OpenSSL markers are not
    read here: only hashlib raises them, and pandas can quote one (an invalid period frequency)
    in an ordinary conversion error."""
    if typed_memory_member(exc) is not None:
        return True
    message = str(exc)
    return any(pattern.search(message) for pattern in MEMORY_ERROR_PATTERNS)


def passes_by_type(exc: Exception) -> bool:
    """Failures the caller classifies by TYPE keep their class under a strict policy: memory
    pressure, and a full disk or quota. Masking them as a read failure would break OOM
    handling and disk-quota reporting."""
    if _is_typed_memory(exc):
        return True
    return isinstance(exc, OSError) and exc.errno in _RESOURCE_ERRNOS


def resurface_scrubbed(exc: Exception) -> Exception | None:
    """A failure the engine recognises only by its TEXT (Arrow's `Wrapping <cell> failed`,
    OpenSSL's context copy), rebuilt as the same type around the scrubbed text; None when `exc`
    is not such a failure or cannot be rebuilt so that the predicate still matches."""
    from decoy_engine.execution._isolated_common import is_memory_failure, scrub_error_text

    if not is_memory_failure(exc):
        return None
    try:
        rebuilt = type(exc)(scrub_error_text(str(exc)))
    except Exception:
        return None
    return rebuilt if is_memory_failure(rebuilt) else None


def _errno_rebuild(exc: OSError) -> OSError:
    """`exc` rebuilt from its errno alone: the canonical text and no filename."""
    code = exc.errno or 0
    try:
        return type(exc)(code, os.strerror(code))
    except Exception:
        return OSError(code, os.strerror(code))


def _fixed_text_rebuild(exc: BaseException) -> BaseException | None:
    """`exc`'s own type around `MEMORY_TEXT`, or None when the constructor refuses it or the
    result no longer reads as a memory failure."""
    try:
        rebuilt = type(exc)(MEMORY_TEXT)
    except Exception:
        return None
    return rebuilt if is_memory_failure(rebuilt) else None


FailureKind = Literal["typed_memory", "resource", "text_memory"]


@dataclass(frozen=True, slots=True)
class ClassifiedFailure:
    """A recognised memory or resource failure. `fresh` is the value-free replacement (no chain,
    no filename, fixed text), or None when the type cannot be rebuilt. Raise it after the
    `except` block closes, `from None`, as `deny` advises: raising inside the block sets
    `__context__` to the original error."""

    kind: FailureKind
    fresh: BaseException | None


def classified_failure(exc: BaseException) -> ClassifiedFailure | None:
    """Classify `exc` for a boundary that must not forward its text, or None when it is none of
    these. A typed memory error anywhere in the chain wins; then a direct disk or quota
    `OSError`; then a direct failure the worker recognises by wording. Build the result in the
    handler and raise `fresh` outside it (see `ClassifiedFailure`)."""
    member = typed_memory_member(exc)
    if member is not None:
        if isinstance(member, OSError):
            return ClassifiedFailure("typed_memory", _errno_rebuild(member))
        return ClassifiedFailure("typed_memory", _fixed_text_rebuild(member))
    if isinstance(exc, OSError) and exc.errno in _RESOURCE_ERRNOS:
        return ClassifiedFailure("resource", _errno_rebuild(exc))
    if isinstance(exc, Exception) and is_memory_failure(exc):
        return ClassifiedFailure("text_memory", _fixed_text_rebuild(exc))
    return None


def _resurface(exc: Exception) -> Exception | None:
    """The exception to raise for a failure the caller must still classify, or None when it
    is an ordinary library failure (a read error).

    By-type failures keep their object, except a resource `OSError`, rebuilt without the
    filename the library puts there. Text-recognised failures go through `resurface_scrubbed`
    because that text can carry a cell value."""
    if isinstance(exc, OSError) and exc.errno in _RESOURCE_ERRNOS:
        return _errno_rebuild(exc)
    if passes_by_type(exc):
        return exc
    return resurface_scrubbed(exc)


def guarded(display: str, strict: bool, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a library call. Under a strict policy a library failure becomes the typed
    `FileAccessReadError` naming only `display`; memory and disk-resource failures keep
    their class; a denial from inside passes unchanged. Under the local policy the call is
    made as it is, so CLI text is unchanged. The new error is raised after the `except`
    block closes so no library error is left as its `__context__`."""
    return guarded_with_parser_errors(display, strict, (), fn, *args, **kwargs)


def guarded_with_parser_errors(
    display: str,
    strict: bool,
    parser_errors: tuple[type[Exception], ...],
    fn: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    """`guarded`, except the named parser error types also pass through unchanged.

    For a caller that classifies a parse failure itself and raises its own value-free coded
    refusal (the library text can carry a cell value, so the caller must never forward it).
    Every other library failure maps exactly as in `guarded`. The one place a library error
    type is allowed past a strict policy; adapters name the types, never a caller."""
    if not strict:
        return fn(*args, **kwargs)
    resurfaced: Exception | None = None
    try:
        return fn(*args, **kwargs)
    except (FileAccessDenied, FileAccessReadError, FileAccessUnavailable, StopIteration):
        # FileAccessUnavailable is only raised at the policy/open and txn layers today, never by a
        # library read/write of an open handle; passing it through is defensive, not load-bearing.
        raise
    except parser_errors:
        raise
    except Exception as exc:
        resurfaced = _resurface(exc)
        if resurfaced is exc:
            raise
    if resurfaced is not None:
        raise resurfaced from None
    raise read_error(display) from None


def read_error(field_key: str) -> FileAccessReadError:
    exc = FileAccessReadError(field_key)
    exc.__suppress_context__ = True
    return exc


def guarded_iter(
    display: str,
    strict: bool,
    it: Iterable[T],
    parser_errors: tuple[type[Exception], ...] = (),
) -> Iterator[T]:
    """Step an iterator under `guarded` semantics (`guarded_with_parser_errors` when
    `parser_errors` is given). Under the local policy it is a plain `yield from`, so CLI text
    is unchanged."""
    if not strict:
        yield from it
        return
    iterator = iter(it)
    while True:
        try:
            item = guarded_with_parser_errors(display, True, parser_errors, next, iterator)
        except StopIteration:
            return
        yield item
