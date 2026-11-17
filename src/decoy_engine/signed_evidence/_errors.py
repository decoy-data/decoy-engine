"""One typed error for the signed-evidence core.

A ``SignedEvidenceError`` is a ``DecoyError`` carrying a registered ``evidence`` reason identity
(``.identity``) and the frozen uppercase wire token (``.code``) that conformance vectors, results and
reports name. The registry classifies only ``.identity``; the wire token is never trusted as a code.

The message is the wire token alone: never an input value, so a hostile document cannot reflect its
content into logs or reports.
"""

from __future__ import annotations

from typing import Any

from decoy_engine._error_base import DecoyError
from decoy_engine.reasons import ReasonCode, evidence


def _identity_of(code: object) -> ReasonCode | None:
    """The registered identity for ``code``: a ``ReasonCode`` itself, or a known frozen wire token."""
    if isinstance(code, ReasonCode):
        known = code.namespace == "evidence" and code in evidence.WIRE_TOKEN
        return code if known else None
    if type(code) is str:
        return evidence.WIRE_IDENTITY.get(code)
    return None


class SignedEvidenceError(DecoyError):
    """A registered refusal plus an optional result status (MALFORMED, UNSUPPORTED, ...)."""

    def __init__(self, code: ReasonCode | str, *, status: str | None = None) -> None:
        identity = _identity_of(code)
        if identity is None:
            raise ValueError("not a registered signed-evidence code")
        self.identity: ReasonCode = identity
        self.code: str = evidence.WIRE_TOKEN[identity]
        self.status = status
        super().__init__(self.code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"SignedEvidenceError({self.code!r})"

    def __reduce__(self) -> tuple[Any, ...]:
        return (_rebuild, (self.code, self.status))


def _rebuild(code: str, status: str | None) -> SignedEvidenceError:
    return SignedEvidenceError(code, status=status)
