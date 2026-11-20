"""The RFC 8785 (JCS) form: the third named canonical byte form.

``jcs_bytes`` serves the signed-evidence profile, whose statement bytes are what a detached JWS
signs. Property order, string escapes and number text are the maintained ``rfc8785`` package's job
(Trail of Bits), so this module only maps its refusals to one value-free error. It is the only
module that imports ``rfc8785`` (a sentry holds that).

Pattern: RFC 8785 JSON Canonicalization Scheme (RFC 8785; rfc8785, Apache-2.0, Trail of Bits).

The refusal is raised after the ``except`` block, so it carries no ``__context__`` and no text of
the value.
"""

from __future__ import annotations

import rfc8785

from decoy_engine._canonical._json import CanonicalJsonError, _summary

__all__ = ["JcsError", "jcs_bytes"]


class JcsError(CanonicalJsonError):
    """A value has no RFC 8785 form (a type JCS cannot write, or an unpaired surrogate)."""

    def __init__(self) -> None:
        super().__init__(_summary(self.code))

    def __reduce__(self) -> tuple[type[JcsError], tuple[()]]:
        return (type(self), ())


def jcs_bytes(value: object) -> bytes:
    """RFC 8785 canonical bytes of ``value``. Raises ``JcsError``, value-free."""
    out: bytes | None = None
    try:
        out = rfc8785.dumps(value)  # type: ignore[arg-type]
    except (rfc8785.CanonicalizationError, TypeError, ValueError, RecursionError, UnicodeError):
        out = None
    if out is None:
        raise JcsError()
    return out
