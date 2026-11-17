"""The synthetic probe: one known-answer digest over the engine's Python reference code.

Fixed public inputs run through the keyed hash core, FF1 and the seeded Faker pool, and the
answers are digested. A host whose digest differs from ``PROBE_GOLDEN`` for its seed protocol
does not reproduce the engine's own bytes. The probe covers the Python reference path only; the
native companion route has its own known-answer vectors.

Pattern: known-answer self-tests run on demand (Libgcrypt runtime self-tests, NSS power-up tests,
FIPS 140 independent known-answer tests). The key, the job seed and every input are public
constants, so the probe never reads a key provider, an environment variable or a file, and the
digest holds nothing of the user's.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Final, Literal

from decoy_engine import reasons
from decoy_engine._canonical import canonical_json_bytes
from decoy_engine.determinism import SEED_PROTOCOL_VERSION
from decoy_engine.errors import DecoyError

__all__ = ["PROBE_GOLDEN", "ProbeError", "probe_status", "run_probe"]

PROBE_KEY: Final = hashlib.sha256(b"decoy-probe/v1").digest()
PROBE_JOB_SEED: Final = PROBE_KEY[:8]
HASH_NAMESPACE: Final = "probe/hash"
FPE_NAMESPACE: Final = "probe/fpe"
FPE_TWEAK_IDENTITY: Final = "probe.fpe"
POOL_PROVIDER: Final = "person_first_name"
POOL_SIZE: Final = 16
POOL_LOCALE: Final = "en_US"

_HASH_INPUTS: Final = (
    "alice",
    "Bob Example",
    "carol@example.test",
    "0",
    "12345",
    "dave-smith",
    "eve.o'neil",
    "FRANK 99",
)
# FF1 needs at least 6 numerals at radix 10.
_FPE_INPUTS: Final = ("123456", "9876543", "00000000", "4111111111")

# One row per seed protocol. Changed only in a PR that bumps the protocol or repins Faker, and
# that PR's changelog fragment names the change.
PROBE_GOLDEN: Final[Mapping[int, str]] = {
    7: "1807cd26ed7736c174c4c00d1111038d8114d1cee8f695489cdbff7eec18388c",
}

_MESSAGE: Final = reasons.get_reason("runtime", "probe_failed").summary


class ProbeError(DecoyError):
    """The probe could not run. The code and text are fixed; no value, path or cause is carried."""

    code = reasons.runtime.PROBE_FAILED
    message = _MESSAGE

    def __init__(self) -> None:
        super().__init__(f"{self.code}: {self.message}")


def _hash_part() -> list[str]:
    from decoy_engine.determinism import derive
    from decoy_engine.kernel import canonicalize_derive_source

    return [
        derive(PROBE_KEY, HASH_NAMESPACE, canonicalize_derive_source(value)).hex()
        for value in _HASH_INPUTS
    ]


def _fpe_part() -> list[str]:
    from decoy_engine.determinism import derive
    from decoy_engine.transforms.fpe import (
        FF1_KEY_LABEL,
        FF1_TWEAK_SCOPE_COLUMN,
        build_ff1_tweak,
        fpe_encrypt_value,
    )

    tweak = build_ff1_tweak(FF1_TWEAK_SCOPE_COLUMN, FPE_TWEAK_IDENTITY)
    return [
        fpe_encrypt_value(
            value, derive(PROBE_KEY, FPE_NAMESPACE, FF1_KEY_LABEL), "0123456789", tweak
        )
        for value in _FPE_INPUTS
    ]


def _pool_part() -> list[str]:
    from decoy_engine import providers_v2
    from decoy_engine.generation.pool import PoolBuilder

    registry = providers_v2.get_default_registry()
    caps = registry.get_capabilities(POOL_PROVIDER)
    # With the mimesis extra the default registry binds `person_first_name` to the Mimesis
    # adapter. The golden is a Faker answer on every install, so the pool part pins the Faker
    # adapter for this one provider and leaves the shared registry untouched.
    faker = providers_v2.FakerAdapter(capabilities_lookup=lambda _name: caps)
    pinned = registry.override(POOL_PROVIDER, faker, caps)
    pool = PoolBuilder(pinned).build(
        POOL_PROVIDER, size=POOL_SIZE, job_seed=PROBE_JOB_SEED, locale=POOL_LOCALE
    )
    return [str(value) for value in pool.values.tolist()]


def _digest() -> str | None:
    """The digest, or ``None`` on any failure. The caller raises, so no exception context holds a value."""
    try:
        from decoy_engine import providers_v2

        # The custom-provider table is process-global; a custom `person_first_name` would be
        # digested in place of the shipped one.
        if POOL_PROVIDER in providers_v2.custom_provider_names():
            return None
        parts = {"hash": _hash_part(), "fpe": _fpe_part(), "pool": _pool_part()}
        return hashlib.sha256(canonical_json_bytes(parts)).hexdigest()
    except Exception:
        return None


def run_probe() -> str:
    """The probe digest: 64 lowercase hex characters, the same on every host that reproduces the engine."""
    digest = _digest()
    if digest is None:
        raise ProbeError
    return digest


def probe_status(digest: str | None) -> Literal["ok", "mismatch"]:
    """``ok`` only when ``digest`` equals the golden for the current seed protocol."""
    expected = PROBE_GOLDEN.get(SEED_PROTOCOL_VERSION)
    return "ok" if expected is not None and digest == expected else "mismatch"
