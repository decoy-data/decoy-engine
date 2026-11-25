"""One recognizer and redactor for credentials in file locators (LOCATOR-CREDS D1 to D13).

`scan_locator` is the only place in the engine that decides whether a locator carries
credentials and what its display and publish text is. It splits an authority the way RFC 3986,
the WHATWG URL Standard and CPython `urllib.parse` agree (userinfo ends at the last `@`; the
authority ends at `/ ? #`, and at `\\` in the WHATWG reading), and where they disagree it takes
the reading that redacts more. Pip's `redact_netloc` and SQLAlchemy's `render_as_string` set the
precedent for masking the whole userinfo; fsspec's `split_protocol` for treating a one-letter
scheme as a drive letter; the Referrer Policy `strict-origin` rule for publishing origin only.
Stdlib only, so it sits in the bottom tier and costs a capped worker nothing to import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_REDACTED = "<redacted>"
_SEPS = "/\\"
_DEVICE_PREFIXES = ("\\\\?\\", "\\\\.\\", "//?/", "//./")
# Schemes whose userinfo without ":" names a container or an account, not a secret (D3).
_ID_SCHEMES = frozenset({"abfs", "abfss", "wasb", "wasbs", "sftp"})
# Schemes that count as a URL after a path separator even with one separator (D2).
_REMOTE = frozenset(
    {"http", "https", "s3", "s3a", "gs", "gcs", "abfs", "abfss", "az", "wasb", "wasbs"}
    | {"ftp", "ftps", "sftp", "hdfs", "webhdfs", "smb", "r2", "oss"}
)
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]+:")
_HOST = re.compile(r"(?:\[[0-9A-Za-z:.%_~-]+\]|[A-Za-z0-9._~%!$&'()*+,;=-]*)(?::[0-9]*)?")
# `name:secret@` inside one segment: an scp-style or `/tmp/a:b@c` shape (D6).
_SCP_USERINFO = re.compile(r"[^\s/\\:]+:[^\s/\\@]*@")


class LocatorKind(str, Enum):
    LOCAL = "local"  # POSIX or relative path, or free text with no URL at the start
    DRIVE = "drive"  # one letter, ':' then a separator: C:\x, C:/x, C://x
    DEVICE = "device"  # \\?\ or \\.\ (and //?/, //./), including \\?\UNC\server\share
    NETWORK = "network"  # leading // or \\ with no scheme: //host/key, \\server\share
    URL = "url"  # scheme of 2+ characters, ':' then a separator


@dataclass(frozen=True, slots=True)
class LocatorScan:
    kind: LocatorKind
    shown: str  # display text; credential spans replaced by "<redacted>"
    carries_credentials: bool  # True exactly when shown != text
    published: str | None  # third-party publish form (D6); None means withhold the value


def scan_locator(text: str) -> LocatorScan:
    """Classify `text` and return its display and publish forms. Never raises on `str`."""
    lead = len(text) - len(text.lstrip(_C0_AND_SPACE))
    walk = _Walk(text[lead:])
    kind = walk.run()
    spans = sorted(walk.replaced)
    shown = text[:lead]
    pos = 0
    for start, end in spans:
        shown += walk.body[pos:start] + _REDACTED
        pos = end
    shown += walk.body[pos:]
    return LocatorScan(kind, shown, shown != text, walk.published(text, shown))


_C0_AND_SPACE = "".join(map(chr, range(0x21)))


class _Walk:
    """One pass over a value (leading C0/space already removed): finds every URL start, parses
    each authority, and records the character ranges to replace and the origins to publish."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.replaced: list[tuple[int, int]] = []
        self.origins: list[str] = []
        self.kind = LocatorKind.LOCAL
        self.urls = 0
        self.withhold = False
        self.userinfo_hidden = False

    def run(self) -> LocatorKind:
        body = self.body
        if body.startswith(_DEVICE_PREFIXES):
            self.kind = LocatorKind.DEVICE
            return self.kind
        first = self._next_start(0)
        if first is not None and first[3] == 0:
            self.kind = LocatorKind.URL
        elif _is_drive(body):
            self.kind = LocatorKind.DRIVE
            first = self._next_start(self._drive())
        elif body[:2] in ("//", "\\\\"):
            self.kind = LocatorKind.NETWORK
            first = None
        nxt = first[:3] if first else None
        if self.kind is LocatorKind.NETWORK:
            nxt = self._span("", 2, body[:2] == "//")
        while nxt is not None:
            nxt = self._span(*nxt)
        return self.kind

    def _is_start(self, p: int) -> tuple[str, int, bool, int] | None:
        """A URL start at `p`: (scheme, index after the separators, literal "//", p)."""
        body = self.body
        m = _SCHEME.match(body, p)
        if m is None:
            return None
        end = m.end()
        n = 0
        while n < 2 and end + n < len(body) and body[end + n] in _SEPS:
            n += 1
        if n == 0:
            return None
        scheme = body[p : end - 1]
        if p > 0 and body[p - 1] in _SEPS and n == 1 and scheme.lower() not in _REMOTE:
            return None
        return scheme, end + n, n == 2 and body[end : end + 2] == "//", p

    def _next_start(self, frm: int) -> tuple[str, int, bool, int] | None:
        body = self.body
        for p in range(frm, len(body)):
            if p > 0:
                prev = body[p - 1]
                if not (prev.isspace() or prev in "='\"(,;<" or prev in _SEPS):
                    continue
            found = self._is_start(p)
            if found is not None:
                return found
        return None

    def _drive(self) -> int:
        """D7: a drive path is unchanged unless its first segment reads as userinfo. Returns
        where URL scanning resumes."""
        body = self.body
        start = 3 + (1 if len(body) > 3 and body[3] in _SEPS else 0)
        end = _scan(body, start, _SEPS)
        seg = body[start:end]
        colon = seg.find(":")
        if colon < 0:
            return end
        at = seg.rfind("@")
        if at > colon:
            self.replaced.append((start, start + at))
        elif "@" in body[end:]:
            self.replaced.append((start, len(body)))
            end = len(body)
        else:
            return end
        self.userinfo_hidden = True
        return end

    def _span(self, scheme: str, auth: int, literal: bool) -> tuple[str, int, bool] | None:
        """Parse one authority and its path. Returns the next URL start, or None at the end."""
        body = self.body
        if scheme:
            self.urls += 1
        w_end = _scan(body, auth, "/?#\\")
        at = body.rfind("@", auth, w_end)
        end = w_end
        if literal:
            u_end = _scan(body, auth, "/?#")
            u_at = body.rfind("@", auth, u_end)
            if u_at > at:
                at, end = u_at, u_end
        host = body[at + 1 : end] if at >= 0 else body[auth:end]
        if _HOST.fullmatch(host) is None:
            self.replaced.append((auth, len(body)))
            self.withhold = True
            return None
        if "%" in body[auth:end]:
            self.withhold = True
        userinfo = body[auth:at] if at >= 0 else ""
        if userinfo and (scheme.lower() not in _ID_SCHEMES or ":" in userinfo):
            self.replaced.append((auth, at))
        origin = f"{scheme}://{host}" if scheme else f"//{host}"
        found = self._next_start(end)
        limit = found[3] if found else len(body)
        marks = [i for i in (body.find("?", end, limit), body.find("#", end, limit)) if i >= 0]
        if marks:
            q = min(marks)
            if q + 1 < len(body):
                self.replaced.append((q + 1, len(body)))
            self.origins.append(origin + "/" + _REDACTED)
            return None
        chunk = body[end:limit]
        piece = origin + ("/" + _REDACTED if chunk else "")
        if found:
            piece += chunk[len(chunk.rstrip()) :]
        self.origins.append(piece)
        return found[:3] if found else None

    def published(self, text: str, shown: str) -> str | None:
        if self.kind in (LocatorKind.URL, LocatorKind.NETWORK):
            return None if self.withhold else "".join(self.origins)
        if self.withhold or self.urls or self.userinfo_hidden or _SCP_USERINFO.search(text):
            return None
        return shown


def _is_drive(body: str) -> bool:
    return (
        len(body) > 2
        and body[0].isascii()
        and body[0].isalpha()
        and body[1] == ":"
        and body[2] in _SEPS
    )


def _scan(text: str, start: int, stops: str) -> int:
    end = start
    while end < len(text) and text[end] not in stops:
        end += 1
    return end
