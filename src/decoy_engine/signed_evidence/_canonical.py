"""Compatibility delegate for the RFC 8785 (JCS) bytes of the signed profile.

The one JCS owner is ``decoy_engine._canonical.jcs_bytes``. This module keeps the name the
package and its tests already import and maps the owner's value-free refusal to the registered
``CANONICALIZATION_FAILED`` identity. It never imports ``rfc8785``.
"""

from __future__ import annotations

from typing import Any

from decoy_engine._canonical import JcsError, jcs_bytes
from decoy_engine.reasons import evidence as ev

from ._errors import SignedEvidenceError


def canonical_bytes(value: Any) -> bytes:
    out: bytes | None = None
    try:
        out = jcs_bytes(value)
    except JcsError:
        out = None
    if out is None:
        raise SignedEvidenceError(ev.CANONICALIZATION_FAILED)
    return out
