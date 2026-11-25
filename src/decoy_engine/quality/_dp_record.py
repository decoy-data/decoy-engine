"""The proof-stack provenance types and the coercion of a recorded provenance.

Split from `dp_provenance` for size; that module re-exports every public name here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple

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
from decoy_engine.errors import DecoyError


class ProvenanceError(DecoyError):
    """A proof-stack provenance violation the DP fit/generation must not run
    through. Mirrors ``carriers.CarrierError`` / ``dp_budget.DpBudgetError``:
    it carries a machine-readable ``code`` so callers branch on the failure
    class rather than parsing prose. Fail-closed by construction -- every gate
    below raises this BEFORE any private data is read."""

    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def _refusal_error(code: str, refusal: Refusal) -> ProvenanceError:
    return ProvenanceError(code=code, message=refusal.text)


class PlatformTriple(NamedTuple):
    """The certified platform identity. ``NamedTuple`` so it is hashable (a
    static-manifest key) and immutable. ``system`` is ``sys.platform``,
    ``machine`` is ``platform.machine()``, ``implementation`` is
    ``platform.python_implementation()``, ``libc`` is the libc family from
    ``platform.libc_ver()`` (``"glibc"`` on manylinux; ``""``/``"unknown"`` on
    musl, which is therefore NOT the certified platform)."""

    system: str
    machine: str
    implementation: str
    libc: str


class Provenance(NamedTuple):
    """The full boundary-independent proof-stack identity of an environment or
    artifact: the platform, the full CPython version, and the lock fingerprint.
    Boundary-independent because the fingerprint is over the installed lock and
    so is identical for the direct-carrier and DataFrame-adapter boundaries in
    one venv (section 3.8: the boundary distinction is enforced by the
    import-isolation assertion, not by two different hashes)."""

    platform: PlatformTriple
    cpython: str
    fingerprint: str


# The keys a recorded provenance and its platform must carry, in lookup order. A missing key is
# named from this tuple, never from the KeyError, so the message holds only engine text.
_RECORD_KEYS = ("platform", "cpython", "fingerprint")
_PLATFORM_KEYS = ("system", "machine", "implementation", "libc")


def coerce_recorded(recorded: object) -> Provenance:
    """Narrow a recorded provenance (a ``Provenance``, or a mapping with
    ``platform`` / ``cpython`` / ``fingerprint`` keys where ``platform`` is a
    ``PlatformTriple``, a 4-element sequence, or a mapping of its fields) to a
    ``Provenance``. Anything else is a coded malformed record."""
    if isinstance(recorded, Provenance):
        return recorded
    if not isinstance(recorded, Mapping):
        raise_bare(
            _refusal_error(
                reasons.quality.DP_PROVENANCE_RECORD_MALFORMED,
                config_refusal(
                    config_position("dp", "recorded"),
                    Problem.WRONG_TYPE,
                    expected=Expected.MAPPING,
                    got=recorded,
                ),
            )
        )
    absent = next((k for k in _RECORD_KEYS if k not in recorded), None)
    if absent is not None:
        raise_bare(
            _refusal_error(
                reasons.quality.DP_PROVENANCE_RECORD_MALFORMED,
                config_refusal(
                    config_position("dp", "recorded", Name(absent)),
                    Problem.MISSING,
                    expected=Expected.FIELD_PRESENT,
                ),
            )
        )
    plat = _coerce_platform(recorded["platform"])
    cpython = recorded["cpython"]
    fingerprint = recorded["fingerprint"]
    if not isinstance(cpython, str) or not isinstance(fingerprint, str):
        raise_bare(
            _refusal_error(
                reasons.quality.DP_PROVENANCE_RECORD_MALFORMED,
                config_refusal(
                    config_position("dp", "recorded"),
                    Problem.WRONG_TYPE,
                    expected=Expected.STRING,
                    hint="The 'cpython' and 'fingerprint' fields must both be strings",
                ),
            )
        )
    return Provenance(platform=plat, cpython=cpython, fingerprint=fingerprint)


def _coerce_platform(value: object) -> PlatformTriple:
    """Narrow a recorded platform to a ``PlatformTriple``."""
    at_platform = config_position("dp", "recorded", "platform")
    if isinstance(value, PlatformTriple):
        return value
    if isinstance(value, Mapping):
        absent = next((k for k in _PLATFORM_KEYS if k not in value), None)
        if absent is not None:
            raise_bare(
                _refusal_error(
                    reasons.quality.DP_PROVENANCE_RECORD_MALFORMED,
                    config_refusal(
                        config_position("dp", "recorded", "platform", Name(absent)),
                        Problem.MISSING,
                        expected=Expected.FIELD_PRESENT,
                    ),
                )
            )
        fields = (
            value["system"],
            value["machine"],
            value["implementation"],
            value["libc"],
        )
    elif isinstance(value, (list, tuple)):
        if len(value) != 4:
            raise_bare(
                _refusal_error(
                    reasons.quality.DP_PROVENANCE_RECORD_MALFORMED,
                    config_refusal(
                        at_platform,
                        Problem.MISMATCH,
                        hint="The recorded platform sequence must have 4 fields",
                    ),
                )
            )
        fields = (value[0], value[1], value[2], value[3])
    else:
        raise_bare(
            _refusal_error(
                reasons.quality.DP_PROVENANCE_RECORD_MALFORMED,
                config_refusal(
                    at_platform,
                    Problem.WRONG_TYPE,
                    got=value,
                    hint=(
                        "The recorded platform must be a PlatformTriple, a mapping, "
                        "or a 4-element sequence"
                    ),
                ),
            )
        )
    if not all(isinstance(field, str) for field in fields):
        raise_bare(
            _refusal_error(
                reasons.quality.DP_PROVENANCE_RECORD_MALFORMED,
                config_refusal(
                    at_platform,
                    Problem.WRONG_TYPE,
                    expected=Expected.STRING,
                    hint="The recorded platform fields must all be strings",
                ),
            )
        )
    return PlatformTriple(*fields)
