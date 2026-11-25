"""Certified proof-stack provenance gate for the DP fit (DPS-CODEC phase 3).

An artifact's ``(epsilon, delta)`` guarantee is only honest on the exact
software stack it was tested against. This module is the fail-closed gate that
enforces that (guide docs/plans/2026-07-23-dps-codec-implementation-guide.md,
sections 3.8 and 4).

WHY A FINGERPRINT, NOT AN ENUMERATED TUPLE (section 3.8, round-5 root-cause).
Earlier revisions hand-listed the versioned distributions the proof depends on
and the list was never complete: successive plan-reviews found a missing
transitive dep each round (SciPy, then attrs / absl-py / wrapt / Deprecated /
polars / python-dateutil / pytz / six, plus the full CPython patch). The
transitive closure is large and drifts, so any curated subset is incomplete by
construction. The fix is to STOP enumerating and instead certify a mechanical
LOCK FINGERPRINT over the COMPLETE resolved distribution set -- every
transitive dependency the lock pins is in the fingerprint, so it is complete by
construction and needs no maintenance as deps change.

METHODOLOGY (established sources, per the repo's "use established methodology"
rule). Distribution identity is read with the standard library's
``importlib.metadata`` (PEP 566 installed-package metadata), names are
canonicalized with PEP 503 (``packaging.utils.canonicalize_name``) so
``PyYAML`` and ``pyyaml`` cannot hash to two different rows, and the
reproducibility guard parses the ``uv.lock`` universal lockfile (the exact
resolution the environment is synced from). The hash is SHA-256 over a
canonical newline-joined ``name==version`` serialization.

WHAT THE GATE IS AND IS NOT (honest scope, section 3.8). The certified row is
``(platform_triple, cpython_full_version, lock_fingerprint)``. The gate is the
locked distribution/version set, NOT exact binary identity: native inputs below
that layer (OpenDP's bundled ``opendp.abi3.so`` Rust core, numpy/scipy's
bundled OpenBLAS/gfortran, the exact glibc patch, the exact CPython build) are
NOT gated in v1. This matches the non-authentication threat model: recording
the identity is audit evidence, not a MAC (the MAC is ROADMAP item 4 / schema
v4). Exact tested-binary identity (selected wheel/``RECORD`` hashes + an exact
libc constraint) is deferred.

THE CERTIFIED PROFILE (section 7, round-6 -- frozen explicitly). The fingerprint
is over the COMPLETE set of distributions installed in the environment, which is
the ``uv.lock`` resolution synced into it. An unrelated installed package
changes the fingerprint and fails the gate closed; this is deliberate ("safe but
strict"). Hosts that install a different profile (e.g. a slimmer runtime, or
extra tools) therefore need their OWN certified row, or an isolated fit
environment -- that host wiring is ROADMAP item 2 / phase 9, out of this phase's
scope. See the note on ``_CERTIFIED_STACKS`` for the exact profile pinned here.

v1 certifies EXACTLY ONE platform -- Linux / x86-64 / CPython / glibc
(manylinux) -- the only platform CI actually exercises (``ci.yml`` is
Ubuntu-only). Anything else (Windows, macOS, ARM, PyPy, musl) fails closed: a
false guarantee on an untested platform is exactly the bug class this redesign
exists to kill, so v1 refuses rather than over-certifies.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import platform
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from packaging.utils import canonicalize_name

from decoy_engine import fileaccess, reasons
from decoy_engine._config_text import (
    Expected,
    Name,
    Problem,
    config_position,
    config_refusal,
    read_config,
)
from decoy_engine._error_base import raise_bare
from decoy_engine.fileaccess import FileRequest, FileRole
from decoy_engine.quality._dp_record import (
    PlatformTriple,
    Provenance,
    ProvenanceError,
    _refusal_error,
    coerce_recorded,
)
from decoy_engine.quality.dp_certified_stacks import CERTIFIED_ROWS

__all__ = [
    "CERTIFIED_PLATFORM",
    "PlatformTriple",
    "Provenance",
    "ProvenanceError",
    "assert_lock_matches_installed",
    "check_fit_environment",
    "compute_lock_fingerprint",
    "current_cpython",
    "current_platform",
    "current_provenance",
    "installed_distribution_set",
    "validate_recorded_provenance",
]


# ---------------------------------------------------------------------------
# Distribution set + fingerprint (importlib.metadata + PEP 503 + SHA-256).
# ---------------------------------------------------------------------------


def installed_distribution_set() -> tuple[tuple[str, str], ...]:
    """The sorted, PEP-503-canonicalized ``(name, version)`` pairs of every
    installed distribution.

    Duplicate canonical names are REJECTED (coded
    ``dp_provenance_duplicate_distribution``): two distributions resolving to
    one canonical name make the fingerprint ambiguous, which is exactly the
    silent drift the gate exists to catch, so it fails loud instead of picking
    one arbitrarily. A distribution with no ``Name`` metadata is likewise
    rejected (``dp_provenance_distribution_unnamed``)."""
    seen: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        raw_name = dist.metadata["Name"]
        if raw_name is None:
            raise_bare(
                _refusal_error(
                    reasons.quality.DP_PROVENANCE_DISTRIBUTION_UNNAMED,
                    config_refusal(
                        config_position("dp", "distributions"),
                        Problem.MISSING,
                        expected=Expected.NAME,
                        hint=(
                            "An installed distribution reports no 'Name' metadata; the "
                            "proof-stack fingerprint cannot be computed unambiguously"
                        ),
                    ),
                )
            )
        name: str = canonicalize_name(raw_name)
        version = dist.version
        if name in seen:
            # A leftover same-version dist-info produces an identical
            # `name==version` line and so is NOT ambiguous for the hash -- collapse
            # it. Only DIFFERENT versions of one canonical name are a genuine
            # ambiguity the fingerprint cannot resolve; those fail closed.
            if seen[name] != version:
                raise_bare(
                    _refusal_error(
                        reasons.quality.DP_PROVENANCE_DUPLICATE_DISTRIBUTION,
                        config_refusal(
                            config_position("dp", "distributions", Name(name)),
                            Problem.DUPLICATE,
                            hint=(
                                "The distribution is installed at two different versions; "
                                "the proof-stack fingerprint would be ambiguous"
                            ),
                        ),
                    )
                )
            continue
        seen[name] = version
    return tuple(sorted(seen.items()))


def _canonical_serialization(dist_set: Iterable[tuple[str, str]]) -> str:
    """The exact bytes-before-hashing serialization. One ``name==version`` per
    line, sorted, newline-joined. Sorting here (not only in the producer) makes
    the fingerprint a pure function of the SET regardless of iteration order."""
    return "\n".join(f"{name}=={version}" for name, version in sorted(dist_set))


def compute_lock_fingerprint(dist_set: Iterable[tuple[str, str]]) -> str:
    """A stable SHA-256 hex fingerprint over the canonical serialization of a
    distribution set. Deterministic and platform-independent given the same
    set: the same resolved lock always yields the same fingerprint."""
    canonical = _canonical_serialization(dist_set)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Platform + interpreter identity.
# ---------------------------------------------------------------------------


def current_platform() -> PlatformTriple:
    """The running platform triple. ``libc`` is the family only (not the patch,
    which v1 does not gate on -- see the module docstring's honest-scope note)."""
    libc_family = platform.libc_ver()[0] or "unknown"
    return PlatformTriple(
        system=sys.platform,
        machine=platform.machine(),
        implementation=platform.python_implementation(),
        libc=libc_family,
    )


def current_cpython() -> str:
    """The full CPython version: ``major.minor.micro.releaselevel``. The FULL
    patch, not a bare minor (section 3.8, round-5): a ``3.10`` row admits a
    moving patch release, but the PLD overflow boundary and other numerics can
    drift by patch, so the gate pins the exact micro."""
    info = sys.version_info
    return f"{info.major}.{info.minor}.{info.micro}.{info.releaselevel}"


def current_provenance() -> Provenance:
    """The full boundary-independent identity of THIS running environment,
    computed live from ``importlib.metadata`` + the interpreter."""
    return Provenance(
        platform=current_platform(),
        cpython=current_cpython(),
        fingerprint=compute_lock_fingerprint(installed_distribution_set()),
    )


# ---------------------------------------------------------------------------
# The STATIC certified manifest.
# ---------------------------------------------------------------------------
#
# This MUST be a checked-in literal, never a value recomputed at import time:
# a manifest that recomputed the local fingerprint would trivially match itself
# and could never fail closed. The gate below compares the LIVE-computed
# fingerprint against these frozen literals.

CERTIFIED_PLATFORM = PlatformTriple(
    system="linux",
    machine="x86_64",
    implementation="CPython",
    libc="glibc",
)

# Certified rows keyed by (platform, cpython_full) -> lock_fingerprint.
#
# The 3.10 row below is pinned from a REPRODUCIBLE synced environment: exactly
# ``uv sync --frozen --extra dev --extra lint --extra vault --extra cloud`` (77
# distributions = 76 registry + the editable ``decoy-engine``). That exact command
# is the frozen profile -- anyone who runs it against this ``uv.lock`` on
# Linux/x86-64/CPython 3.10.20 reproduces this fingerprint. (An earlier draft
# pinned a "dirty" working ``.venv`` that no single ``uv sync`` reproduced; that
# was the phase-3 Codex MEDIUM -- fixed by pinning the clean ``dev+lint+vault``
# profile the CI workflow actually syncs. ``cloud`` was added when
# boto3/google-cloud-storage moved from base deps to an opt-in extra, since
# google-cloud-storage does not survive the profile without it.) See
# ``assert_lock_matches_installed`` for the guard that proves
# the installed set is exactly the lock's marker-selected pins.
# CI ADDS THE OTHER ROWS. The dependency-matrix workflow
# (``.github/workflows/dps-dependency-matrix.yml``) runs on exact-pinned CPython
# patches (3.10.x / 3.11.x / 3.12.x), computes the fingerprint per row, and
# asserts it against the row present here (a regression guard). For a patch/row
# not yet present, the workflow PRINTS the computed fingerprint for a maintainer
# to paste in as a new certified row; only patches CI actually exercises may be
# admitted (section 3.8: "admit no patch the matrix does not exercise"). Until a
# row is added, that interpreter fails closed with ``dp_stack_uncertified``.
# A given (platform, cpython) admits a SET of certified fingerprints, one per
# reproducible locked profile tested on that interpreter: the engine's own
# dev/CI lock, and the `decoy` CLI's pristine runtime profile (engine + CLI
# runtime deps, no dev tooling), whose proof-critical library versions are pinned to EXACTLY the
# certified ones (opendp/dp-accounting/numpy/scipy/pandas/pyarrow, per the annotation below) so the
# DP behaviour is the tested behaviour; the CLI's extra packages (typer/rich/...) are off the DP
# code path. Membership, not equality: a distinct profile with the same proof-critical set earns
# its own row rather than forcing an isolated fit environment (ROADMAP item 2 / phase 9).
# The row sets live in `dp_certified_stacks.py` (release prep appends to them every release). Rows
# are never removed: a stamp moves only the engine version, so old snapshots stay admitted.
_CERTIFIED_STACKS: dict[tuple[PlatformTriple, str], frozenset[str]] = {
    (CERTIFIED_PLATFORM, cpython): rows for cpython, rows in CERTIFIED_ROWS.items()
}

# INFORMATIONAL annotation only (section 3.8: retained for auditability; the
# GATE is the fingerprint above, NOT this annotation). Human-readable key
# versions of the proof-critical libraries per certified cpython row.
_CERTIFIED_ANNOTATIONS: dict[str, dict[str, str]] = {
    "3.10.20.final": {
        "opendp": "0.15.1",
        "dp-accounting": "0.6.0",
        "numpy": "2.2.6",
        "scipy": "1.15.3",
        "pandas": "2.3.3",
        "pyarrow": "24.0.0",
    },
}


# ---------------------------------------------------------------------------
# The gates.
# ---------------------------------------------------------------------------


def check_fit_environment() -> None:
    """FIT-TIME gate. Fail closed BEFORE any private data is read.

    Raises ``dp_platform_uncertified`` when the running platform is not the
    certified Linux / x86-64 / CPython / glibc, and ``dp_stack_uncertified``
    when the ``(platform, cpython, fingerprint)`` identity is not a certified
    row (an uncertified CPython patch, or any drift in the installed
    distribution set)."""
    plat = current_platform()
    if plat != CERTIFIED_PLATFORM:
        raise_bare(
            _refusal_error(
                reasons.quality.DP_PLATFORM_UNCERTIFIED,
                config_refusal(
                    config_position("dp", "platform"),
                    Problem.NOT_ALLOWED,
                    hint=(
                        "The DP fit is certified only on the certified platform. The "
                        "(epsilon, delta) guarantee is not honest on an untested platform, "
                        "so the fit refuses rather than over-certify"
                    ),
                ),
            )
        )
    cpython = current_cpython()
    fingerprint = compute_lock_fingerprint(installed_distribution_set())
    certified = _CERTIFIED_STACKS.get((plat, cpython))
    if certified is None or fingerprint not in certified:
        raise_bare(
            _refusal_error(
                reasons.quality.DP_STACK_UNCERTIFIED,
                config_refusal(
                    config_position("dp", "proof_stack"),
                    Problem.NOT_ALLOWED,
                    hint=(
                        "No certified proof-stack row matches this cpython, fingerprint and "
                        "platform. The installed distribution set does not match a tested "
                        "lock, so the fit refuses. A host with a different profile needs its "
                        "own certified row or an isolated fit environment"
                    ),
                ),
            )
        )


def validate_recorded_provenance(recorded: object) -> None:
    """GENERATION-TIME gate. Validate an artifact's RECORDED
    ``(platform, cpython, fingerprint)`` against the static certified set.

    Generation does NOT recompute the fingerprint from locally installed
    libraries (the generating host may legitimately differ from the fitting
    host); it checks the identity the artifact carries. Same coded fail-closed
    as the fit gate, plus ``dp_provenance_record_malformed`` when the record's
    shape is unusable."""
    prov = coerce_recorded(recorded)
    if prov.platform != CERTIFIED_PLATFORM:
        raise_bare(
            _refusal_error(
                reasons.quality.DP_PLATFORM_UNCERTIFIED,
                config_refusal(
                    config_position("dp", "recorded", "platform"),
                    Problem.NOT_ALLOWED,
                    hint="The artifact's recorded platform is not the certified platform",
                ),
            )
        )
    certified = _CERTIFIED_STACKS.get((prov.platform, prov.cpython))
    if certified is None or prov.fingerprint not in certified:
        raise_bare(
            _refusal_error(
                reasons.quality.DP_STACK_UNCERTIFIED,
                config_refusal(
                    config_position("dp", "recorded", "proof_stack"),
                    Problem.NOT_ALLOWED,
                    hint=(
                        "The artifact's recorded proof stack (cpython, fingerprint) "
                        "is not a certified row"
                    ),
                ),
            )
        )


# ---------------------------------------------------------------------------
# Reproducibility guard: lock == installed (section 7, round-6 -- Codex).
# ---------------------------------------------------------------------------


def _default_lock_path() -> Path:
    # dp_provenance.py -> quality -> decoy_engine -> src -> <repo root>.
    return Path(__file__).resolve().parents[3] / "uv.lock"


def assert_lock_matches_installed(lock_path: str | Path | None = None) -> None:
    """Assert every installed distribution is a marker-selected ``uv.lock`` pin
    at the exact same version. This is the guard that the fingerprint is
    REPRODUCIBLE from the lock: a fingerprint over a set that has drifted from
    the lock, or carries an off-lock package, is not what CI certified.

    A distribution is "marker-selected" when a ``[[package]]`` entry for its
    canonical name is active in the current interpreter environment -- either it
    carries no ``resolution-markers`` (universal) or at least one of them
    evaluates true here. The installed set must be a SUBSET of the
    marker-active lock at matching versions: the lock is the full multi-group
    resolution (docs / ml / ner / lint / ... extras), so the installed profile
    is legitimately a subset; what must NOT happen is an installed package that
    is absent from the lock (a stray) or pinned to a different version (drift).
    (The reverse direction -- pinning WHICH lock subset the profile installs --
    is fixed by freezing the exact install command in CI, out of this function's
    scope; documented in the workflow.)

    Raises ``dp_lock_installed_mismatch`` on any stray or drift, and
    ``dp_lock_parse_error`` if the lockfile is missing or unreadable. The TOML
    parser and marker evaluator are imported lazily so the fit-time gate
    (``check_fit_environment``) never pays for them."""
    # Version-guarded (not try/except) so mypy under python_version 3.10 does
    # not try to resolve stdlib `tomllib`, which does not exist before 3.11.
    if sys.version_info >= (3, 11):
        import tomllib as toml_reader
    else:
        import tomli as toml_reader  # 3.10 backport, pinned in the lock

    from packaging.markers import Marker

    path = _default_lock_path() if lock_path is None else Path(lock_path)
    req = FileRequest(FileRole.CONFIG, "read", str(path), "dp.lock_path")
    lock_file = (
        fileaccess.engine_handle(path) if lock_path is None else fileaccess.capture().open_read(req)
    )
    at_lock = config_position("dp", "lock_path")

    def _parse() -> Any:
        with lock_file.open_binary() as handle:
            return toml_reader.load(handle)

    lock = read_config(
        _parse,
        at_lock,
        lambda r: _refusal_error(reasons.quality.DP_LOCK_PARSE_ERROR, r),
    )

    packages = lock.get("package")
    if not isinstance(packages, list):
        raise_bare(
            _refusal_error(
                reasons.quality.DP_LOCK_PARSE_ERROR,
                config_refusal(
                    at_lock,
                    Problem.MISSING,
                    hint="The dp lockfile has no [[package]] array",
                ),
            )
        )

    # canonical name -> set of versions active in THIS environment.
    lock_active: dict[str, set[str]] = {}
    for entry in packages:
        if not isinstance(entry, dict) or "name" not in entry or "version" not in entry:
            continue
        markers = entry.get("resolution-markers")
        if markers and not _any_marker_true(markers, Marker):
            continue
        name = str(canonicalize_name(str(entry["name"])))
        lock_active.setdefault(name, set()).add(str(entry["version"]))

    strays: list[str] = []
    drift: list[str] = []
    for name, version in installed_distribution_set():
        active_versions = lock_active.get(name)
        if active_versions is None:
            strays.append(name)
        elif version not in active_versions:
            # Names only: a version string is read from the lockfile or the environment.
            drift.append(name)

    if strays or drift:
        raise_bare(
            _refusal_error(
                reasons.quality.DP_LOCK_INSTALLED_MISMATCH,
                config_refusal(
                    at_lock,
                    Problem.MISMATCH,
                    names=tuple(Name(n) for n in sorted([*strays, *drift])),
                    hint=(
                        "Installed distributions do not match the marker-selected lock "
                        "(strays or version drift)"
                    ),
                ),
            )
        )


def _any_marker_true(
    markers: object,
    marker_cls: type,
) -> bool:
    """True if any marker string in ``markers`` evaluates true in the current
    environment. A malformed marker is treated as not-satisfied (it cannot
    make a version active) rather than crashing the guard."""
    if not isinstance(markers, list):
        return False
    for marker in markers:
        if not isinstance(marker, str):
            continue
        try:
            if marker_cls(marker).evaluate():
                return True
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            # Any marker that cannot be constructed OR evaluated (InvalidMarker,
            # UndefinedComparison, UndefinedEnvironmentName, ...) is treated as
            # not-satisfied. That is the fail-CLOSED direction here: an
            # un-evaluable locked version is not counted active, so a matching
            # installed dist surfaces as a stray rather than being silently
            # accepted. The try body is only marker construction + evaluation.
            continue
    return False
