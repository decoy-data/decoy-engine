"""Read a whole file through the installed policy: the one helper small readers share."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable

from decoy_engine.fileaccess._entry import current, is_ambient
from decoy_engine.fileaccess._errors import encode_field_key, passes_by_type, resurface_scrubbed
from decoy_engine.fileaccess._types import FileRequest, FileRole


def read_all(role: FileRole, locator: str, field_key: str, limit: int | None = None) -> bytes:
    """The bytes of one file the installed policy authorizes for `role`.

    Errors from a local read are the plain `OSError` the caller always saw, so CLI text is
    unchanged; a strict policy raises the one denial instead."""
    handle = current().open_read(FileRequest(role, "read", locator, field_key))
    try:
        return handle.read_all(limit)
    finally:
        handle.close()


def read_text(role: FileRole, locator: str, field_key: str, encoding: str = "utf-8") -> str:
    """Like `read_all`, decoded in text mode so newline translation matches `open(..., "r")`."""
    handle = current().open_read(FileRequest(role, "read", locator, field_key))
    try:
        with handle.open_text(encoding) as stream:
            return stream.read()
    finally:
        handle.close()


def read_checked(
    role: FileRole, locator: str, field_key: str, check: Callable[[os.stat_result], None]
) -> bytes:
    """The bytes of one authorized file, with `check` run first on `fstat` of the descriptor the
    bytes are then read from. Nothing re-resolves the locator after the check (a path `stat`
    followed by a second open is the check-then-use race). A regular file is read with `pread`
    from offset 0 so a shared descriptor's offset is untouched; anything else is read in order.
    The descriptor is closed on every exit."""
    handle = current().open_read(FileRequest(role, "read", locator, field_key))
    try:
        fd = handle.fileno()
        info = os.fstat(fd)
        check(info)
        chunks: list[bytes] = []
        regular = stat.S_ISREG(info.st_mode)
        offset = 0
        while True:
            data = os.pread(fd, 1 << 16, offset) if regular else os.read(fd, 1 << 16)
            if not data:
                return b"".join(chunks)
            chunks.append(data)
            offset += len(data)
    except BaseException:
        # A read that fails part way, or a failing close, must not leave the bytes already read
        # in this frame: the role is SECRET for the mask secret (`_opaque`).
        chunks = data = None  # type: ignore[assignment]
        raise
    finally:
        try:
            handle.close()
        except BaseException:
            chunks = data = None  # type: ignore[assignment]
            raise


# A locator may be a URL (`s3://user:secret@host/key?token=...`), or one a `Path` has squeezed to a
# single slash (`s3:/user:secret@host/...`) or turned to backslashes on Windows. Its userinfo,
# query and fragment are credentials. The scheme may follow whitespace or sit inside a sentence,
# but must not continue a path or a word, so a local path such as `/tmp/a:/b@c/f?x=1` is not a
# URL. Two or more scheme characters, so not a drive letter.
_HEAD = r"(?<![\w+.\-/\\])(?P<scheme>[A-Za-z][A-Za-z0-9+.-]+):(?P<slashes>[/\\]{1,2})"
_TOKEN_URL_RE = re.compile(_HEAD + r"(?P<rest>\S*)")  # free text: a URL ends at whitespace
_LOCATOR_URL_RE = re.compile(_HEAD + r"(?P<rest>.*)", re.DOTALL)  # a locator: nothing ends it
_DELIMS_RE = re.compile(r"[/?#]")
_MARKS_RE = re.compile(r"[?#]")
_SENSITIVE_RE = re.compile(r"[@?#]")


def _redact_url(match: re.Match[str]) -> str:
    head = f"{match['scheme']}:{match['slashes'].replace(chr(92), '/')}"
    rest = match["rest"]
    if not _SENSITIVE_RE.search(rest):
        return head + rest.replace("\\", "/")
    # Whitespace inside a URL is a password or query holding a space: nothing is kept.
    if re.search(r"\s", rest):
        return head + "<redacted>"
    rest = rest.replace("\\", "/")
    delim = _DELIMS_RE.search(rest)
    cut = delim.start() if delim else len(rest)
    authority, tail = rest[:cut], rest[cut:]
    # A literal `@` after the authority is a password holding a `/`, `?` or `#`, or an `@` in a
    # query: the parsers disagree on where userinfo ends, so nothing of the URL is kept.
    if "@" in tail:
        return head + "<redacted>"
    authority = authority.rpartition("@")[2]
    if "@" in authority or "?" in authority:
        return head + "<redacted>"
    tail_delim = _MARKS_RE.search(tail)
    path = tail[: tail_delim.start()] if tail_delim else tail
    marks = tail[tail_delim.start() :] if tail_delim else ""
    out = head + authority + path
    if "?" in marks.split("#", 1)[0]:
        out += "?<redacted>"
    if "#" in marks:
        out += "#<redacted>"
    return out


def without_url_credentials(text: str, *, free_text: bool = False) -> str:
    """`text` with the userinfo, query and fragment of any URL-shaped locator removed.

    A single locator (the default) is read whole: whitespace does not end a URL, so a password
    or query holding a space is removed with the rest. Free-form message text (`free_text`)
    ends each URL at whitespace, then removes every later token that holds `@`, `?` or `#`,
    since the text may have split a credential at a space."""
    if not free_text:
        return _LOCATOR_URL_RE.sub(_redact_url, text)
    out: list[str] = []
    pos = 0
    seen = False
    for match in _TOKEN_URL_RE.finditer(text):
        out.append(_scrub_tokens(text[pos : match.start()]) if seen else text[pos : match.start()])
        out.append(_redact_url(match))
        pos = match.end()
        seen = True
    out.append(_scrub_tokens(text[pos:]) if seen else text[pos:])
    return "".join(out)


def _scrub_tokens(text: str) -> str:
    return "".join(
        "<redacted>" if _SENSITIVE_RE.search(part) else part for part in re.split(r"(\s+)", text)
    )


def shown(locator: str, field_key: str) -> str:
    """What an engine message may call a file: the locator under the ambient CLI policy (so
    CLI text is unchanged, minus any URL credentials), the encoded config position under any
    other."""
    return without_url_credentials(locator) if is_ambient() else encode_field_key(field_key)


def keeps_class(exc: BaseException) -> bool:
    """True when a handler that translates, stores or swallows an exception raised from a file
    call must re-raise it unchanged under a strict policy: a policy decision, a typed read
    error, and the failures callers classify by type or by the memory predicate (memory, a
    full disk or quota). Always False under the ambient policy, whose handlers keep today's
    behavior."""
    if is_ambient():
        return False
    if isinstance(exc, Exception) and passes_by_type(exc):
        return True
    from decoy_engine.fileaccess._types import (
        FileAccessDenied,
        FileAccessReadError,
        FileAccessUnavailable,
    )

    if isinstance(exc, (FileAccessDenied, FileAccessReadError, FileAccessUnavailable)):
        return True
    return isinstance(exc, Exception) and resurface_scrubbed(exc) is not None
