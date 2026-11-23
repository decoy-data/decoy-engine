"""The faker operator's provider allowlist is total over the live registry.

The native faker operator indexes into a pool Python builds, so any provider that builds a pool of
strings can run on it. `OPERATORS["faker"].provider_allowlist` is the one admission fact. This
sentry walks the live registry, not source text, and fails when:

- a provider classified `pool_native` is neither allowed nor named in `EXCLUDED` with a reason that
  still holds (a new provider cannot silently stay on the slow route),
- the allowlist names a provider the registry does not classify `pool_native` (a stale entry),
- an `EXCLUDED` reason no longer holds, or
- a second copy of the allowlist appears beside the registry literal.

`EXCLUDED` is an allowlist for the sentry itself, so it is registered in
`scripts/dev/sentry_registry.toml` and may only shrink.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from decoy_engine.execution._operator_registry import OPERATORS
from decoy_engine.execution.native._provider_class import classify_provider
from decoy_engine.execution.native._real_type_admission import C1_PROVIDER_ALLOWLIST
from decoy_engine.generation.pool._builder import PoolBuilder
from decoy_engine.providers_v2 import ProviderRegistry, get_default_registry

SRC = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"
REGISTRY_FILE = "execution/_operator_registry.py"
_DECOY_NATIVE = (
    "decoy_native backend; its deterministic mode bypasses the Faker pool adapter, "
    "so the faker pool operator does not serve it"
)
# provider -> reason it is classified `pool_native` but kept off the faker pool operator.
EXCLUDED: dict[str, str] = {
    "person_dob": "date pool; the operator takes string pools only",
    "synthetic_ssn": _DECOY_NATIVE,
    "synthetic_ein": _DECOY_NATIVE,
    "synthetic_npi": _DECOY_NATIVE,
    "synthetic_ndc": _DECOY_NATIVE,
    "synthetic_mrn": _DECOY_NATIVE,
    "synthetic_pan": _DECOY_NATIVE,
    "synthetic_icd10": _DECOY_NATIVE,
    "synthetic_iban": _DECOY_NATIVE,
    "synthetic_cusip": _DECOY_NATIVE,
}


# Files whose provider-name sets answer another question than faker-operator admission.
OTHER_PROVIDER_SETS = {
    "providers_v2/mimesis/_adoption_matrix.py": "which providers the Mimesis backend serves",
}


def _allowlist() -> frozenset[str]:
    allowed = OPERATORS["faker"].provider_allowlist
    assert allowed is not None
    return allowed


def _pool_native(registry: ProviderRegistry) -> set[str]:
    return {
        p
        for p in registry.known_providers()
        if classify_provider(p, None, registry=registry) == "pool_native"
    }


def _builds_only_strings(registry: ProviderRegistry, provider: str) -> bool:
    pool = PoolBuilder(registry).build(provider, size=50, job_seed=b"\x03" * 8)
    return all(isinstance(v, str) for v in pool.values.tolist())


def audit(
    registry: ProviderRegistry, allowed: frozenset[str], excluded: dict[str, str]
) -> list[str]:
    """Problems found walking `registry`; empty when the allowlist is total and honest."""
    problems: list[str] = []
    native = _pool_native(registry)
    for provider in sorted(native - allowed - set(excluded)):
        problems.append(f"missing:{provider}")
    for provider in sorted(allowed - native):
        problems.append(f"stale_allowed:{provider}")
    for provider in sorted(set(excluded) - native):
        problems.append(f"stale_excluded:{provider}")
    for provider in sorted(allowed & set(excluded)):
        problems.append(f"in_both:{provider}")
    for provider in sorted(set(excluded) & native):
        caps = registry.get_capabilities(provider)
        if caps.backend_type == "decoy_native":
            continue
        # A non-decoy_native exclusion must hold on its own: its pool is not all strings.
        if _builds_only_strings(registry, provider):
            problems.append(f"reason_fails:{provider}")
    return problems


def test_the_live_registry_is_covered_by_the_allowlist_or_the_exclusions() -> None:
    assert audit(get_default_registry(), _allowlist(), EXCLUDED) == []


def test_every_allowlisted_provider_builds_a_pool_of_strings() -> None:
    registry = get_default_registry()
    assert [p for p in sorted(_allowlist()) if not _builds_only_strings(registry, p)] == []


def test_the_excluded_map_does_not_grow() -> None:
    assert len(EXCLUDED) == 10


def test_the_allowlist_has_one_source() -> None:
    assert C1_PROVIDER_ALLOWLIST is OPERATORS["faker"].provider_allowlist
    names = {"person_first_name", "person_last_name"}
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel == REGISTRY_FILE or rel in OTHER_PROVIDER_SETS:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Set | ast.List | ast.Tuple):
                found = {
                    e.value
                    for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                }
                if names <= found:
                    offenders.append(f"{rel}:{node.lineno}")
    assert offenders == []


# Seeded cases: the audit itself must go red on each shape, so the live walk cannot rot.


class _Stub:
    backend_type = "faker"
    backend_version = "stub"

    def generate(self, provider: str, *, spec: object, source_value: bytes | None = None) -> str:
        return "x"

    def generate_batch(self, provider: str, *, spec: object, count: int) -> list[object]:
        return [1] * count

    def capability_matrix(self, provider: str):  # type: ignore[no-untyped-def]
        return get_default_registry().get_capabilities("person_email")


def _with_stub(name: str, *, backend: str) -> ProviderRegistry:
    default = get_default_registry()
    caps = default.get_capabilities("person_email").model_copy(
        update={"backend_type": backend, "backend_version": "stub"}
    )
    stub = _Stub()
    stub.backend_type = backend
    return default.override(name, stub, caps)


@pytest.mark.parametrize("backend", ["faker", "mimesis", "decoy_native"])
def test_a_new_pool_native_provider_missing_from_both_sets_is_reported(backend: str) -> None:
    registry = _with_stub("stub_provider", backend=backend)
    assert "missing:stub_provider" in audit(registry, _allowlist(), EXCLUDED)


def test_an_allowlist_entry_the_registry_does_not_know_is_reported() -> None:
    allowed = _allowlist() | {"no_such_provider"}
    assert "stale_allowed:no_such_provider" in audit(get_default_registry(), allowed, EXCLUDED)


def test_a_string_provider_in_the_excluded_map_is_reported() -> None:
    excluded = {**EXCLUDED, "person_email": "not a real reason"}
    problems = audit(get_default_registry(), _allowlist() - {"person_email"}, excluded)
    assert "reason_fails:person_email" in problems


def test_a_provider_in_both_sets_is_reported() -> None:
    excluded = {**EXCLUDED, "person_email": "dup"}
    assert "in_both:person_email" in audit(get_default_registry(), _allowlist(), excluded)


def test_removing_an_allowed_provider_is_reported() -> None:
    allowed = _allowlist() - {"person_email"}
    assert "missing:person_email" in audit(get_default_registry(), allowed, EXCLUDED)


def test_adding_person_dob_to_the_allowlist_is_reported() -> None:
    allowed = _allowlist() | {"person_dob"}
    problems = audit(get_default_registry(), allowed, {**EXCLUDED})
    assert "in_both:person_dob" in problems
