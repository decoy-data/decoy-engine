"""Credentials in a file locator: find them and take them out of text that leaves the engine.

A locator may be a URL (`s3://user:secret@host/key?token=...`), a network path
(`//user:secret@host/key`), or one a `Path` has squeezed to a single slash
(`s3:/user:secret@host/...`) or turned to backslashes on Windows. Its userinfo, query and
fragment are credentials. This leaf module is below `fileaccess` and `plan`, so the diagnostics
and the plan check share one detector: `locator_carries_credentials` is true exactly when
`without_url_credentials` took something out, so a clean locator that only needed its
backslashes turned to slashes is not a hit.
"""

from __future__ import annotations

import re

__all__ = ["locator_carries_credentials", "without_url_credentials"]

# The scheme may follow whitespace or sit inside a sentence, but must not continue a path or a
# word, so a local path such as `/tmp/a:/b@c/f?x=1` is not a URL. Two or more scheme characters,
# so not a drive letter.
_HEAD = r"(?<![\w+.\-/\\])(?P<scheme>[A-Za-z][A-Za-z0-9+.-]+):(?P<slashes>[/\\]{1,2})"
_LOCATOR_URL_RE = re.compile(_HEAD + r"(?P<rest>.*)", re.DOTALL)  # a locator: nothing ends it
# A URL after a path separator (`a/https://u:p@h`) is skipped by the lookbehind above so a local
# path like `/tmp/a:/b@c` stays readable. It is a URL when it has two slashes, or when the scheme
# is a known remote one: `Path` collapses `https://` to `https:/`, and the API takes a `Path`.
_REMOTE_SCHEMES = r"(?:https?|s3a?|gs|gcs|abfss?|az|wasbs?|ftps?|sftp|hdfs|webhdfs|smb|r2|oss)"
_EMBEDDED_URL_RE = re.compile(
    r"[/\\](?:[A-Za-z][A-Za-z0-9+.-]+:(?:/{2}|\\{2})|(?i:"
    + _REMOTE_SCHEMES
    + r"):[/\\])(?P<rest>.*)",
    re.DOTALL,
)
# A network path with no scheme: `//user:secret@host/key`, read like the part after a scheme.
_NETWORK_PATH_RE = re.compile(r"\A(?P<slashes>[/\\]{2})(?P<rest>.*)", re.DOTALL)
_DELIMS_RE = re.compile(r"[/?#]")
_MARKS_RE = re.compile(r"[?#]")
_SENSITIVE_RE = re.compile(r"[@?#]")
_REDACTED = "<redacted>"


def _redact_rest(head: str, rest: str, hits: list[bool]) -> str:
    """`head + rest` with userinfo, query and fragment removed; a hit is appended to `hits`."""
    if not _SENSITIVE_RE.search(rest):
        return head + rest.replace("\\", "/")
    # Whitespace inside a URL is a password or query holding a space: nothing is kept.
    if re.search(r"\s", rest):
        hits.append(True)
        return head + _REDACTED
    rest = rest.replace("\\", "/")
    delim = _DELIMS_RE.search(rest)
    cut = delim.start() if delim else len(rest)
    authority, tail = rest[:cut], rest[cut:]
    # A literal `@` after the authority is a password holding a `/`, `?` or `#`, or an `@` in a
    # query: the parsers disagree on where userinfo ends, so nothing of the URL is kept.
    if "@" in tail:
        hits.append(True)
        return head + _REDACTED
    host = authority.rpartition("@")[2]
    if "@" in host or "?" in host:
        hits.append(True)
        return head + _REDACTED
    if host != authority:
        hits.append(True)
    tail_delim = _MARKS_RE.search(tail)
    path = tail[: tail_delim.start()] if tail_delim else tail
    marks = tail[tail_delim.start() :] if tail_delim else ""
    out = head + host + path
    if "?" in marks.split("#", 1)[0]:
        hits.append(True)
        out += "?" + _REDACTED
    if "#" in marks:
        hits.append(True)
        out += "#" + _REDACTED
    return out


def _redact_url(match: re.Match[str], hits: list[bool]) -> str:
    head = f"{match['scheme']}:{match['slashes'].replace(chr(92), '/')}"
    return _redact_rest(head, match["rest"], hits)


def _scan(text: str) -> tuple[str, bool]:
    embedded = _EMBEDDED_URL_RE.search(text)
    if embedded is not None and _SENSITIVE_RE.search(embedded["rest"]):
        return _REDACTED, True
    hits: list[bool] = []
    network = _NETWORK_PATH_RE.match(text)
    if network is not None:
        # One rule with the scheme URLs. A path with no `@`, `?` or `#` is left as written.
        out = _redact_rest("//", network["rest"], hits)
        return (out, True) if hits else (text, False)
    return _LOCATOR_URL_RE.sub(lambda m: _redact_url(m, hits), text), bool(hits)


def without_url_credentials(text: str) -> str:
    """`text`, one locator, with the userinfo, query and fragment of a URL in it removed.

    The locator is read whole: whitespace does not end a URL. A URL that follows a path
    separator is ambiguous (a path, or a URL under a prefix), so a value holding one with a
    sensitive character after it is suppressed whole."""
    return _scan(text)[0]


def locator_carries_credentials(text: str) -> bool:
    """True when `text` holds URL userinfo, or a query or fragment on a URL."""
    return _scan(text)[1]
