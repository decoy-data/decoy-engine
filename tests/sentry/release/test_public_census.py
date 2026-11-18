"""X0 (freeze batch plan 4.1, 8): every public engine name has exactly one stability tier.

The census walks `decoy_engine.__all__`, `decoy_engine.sdk`, `decoy_engine.providers` and every
public subpackage that declares `__all__` (the floors below are the measured walk). A tier belongs
to an object, so an object exported from two places must get the same tier in both.
"""

from __future__ import annotations

import re
import sys
import textwrap
from pathlib import Path

import pytest

import decoy_engine
from decoy_engine.contracts import stability as st
from tests.sentry.layout import section
from tests.sentry.release import _census as census

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = (ROOT / "docs" / "compatibility-contract.md").read_text(encoding="utf-8")
MIN_PACKAGES, MIN_NAMES = 59, 1186


@pytest.fixture(scope="module")
def walk() -> tuple[list[census.Export], dict[tuple[str, str], str], list[str]]:
    exports, declared = census.load()
    return exports, census.classify(exports), declared


def test_every_root_name_has_exactly_one_tier(walk) -> None:
    """AT-X0a: root exports are all classified; a re-exported sdk object shares the sdk tier."""
    _, tiers, _ = walk
    missing = [n for n in decoy_engine.__all__ if ("decoy_engine", n) not in tiers]
    assert not missing, f"root names without a tier: {missing}"
    for name in ("FileSource", "FileSink", "ConnectorConfig", "SDK_VERSION"):
        assert tiers[("decoy_engine", name)] == tiers[("decoy_engine.sdk", name)] == st.EXPERIMENTAL
    assert tiers[("decoy_engine", "run_pipeline")] == st.FROZEN
    assert tiers[("decoy_engine", "register_faker_provider")] == st.EXPERIMENTAL
    assert tiers[("decoy_engine.sdk", "FileSource")] == st.EXPERIMENTAL


def test_errors_reached_through_sdk_stay_frozen(walk) -> None:
    """AT-X0f: the tier follows the object, not the `sdk` name that exports it."""
    _, tiers, _ = walk
    for name in ("ConfigError", "ConnectorError"):
        assert tiers[("decoy_engine.sdk", name)] == tiers[("decoy_engine", name)] == st.FROZEN
    assert tiers[("decoy_engine.sdk", "TransientError")] == st.EXPERIMENTAL


def test_the_walk_meets_the_measured_floors(walk) -> None:
    """AT-X0e: 59 packages and 1,186 names; a walk that skips a package fails here."""
    exports, _, declared = walk
    importable = [e for e in exports if not e.static and e.module not in census.EXTRA_MODULES]
    assert len(declared) >= MIN_PACKAGES, f"only {len(declared)} public packages walked"
    assert len(importable) >= MIN_NAMES, f"only {len(importable)} public names walked"
    assert {"decoy_engine.sdk", "decoy_engine.providers"} <= {e.module for e in exports}


def test_exceptions_are_unique_and_not_stale(walk) -> None:
    """AT-X0e: an exception row names a real export once, with a real tier."""
    exports, _, _ = walk
    keys = [(m, n) for m, n, _ in st.TIER_EXCEPTIONS]
    assert len(keys) == len(set(keys)), "duplicate tier exception"
    assert set(keys) <= {(e.module, e.name) for e in exports}, "stale tier exception"
    assert {t for _, _, t in st.TIER_EXCEPTIONS} <= set(st.TIERS)


def test_every_frozen_package_is_named_by_contract_3_4() -> None:
    """Contract 3.4 is the only source of a frozen subpackage; everything else is internal."""
    text = section(CONTRACT, "### 3.4 The public API + CLI contract")
    for package, tier in st.PACKAGE_TIERS.items():
        assert tier in st.TIERS
        if tier == st.FROZEN and package != "decoy_engine":
            assert package in text or package.replace(".", "/") in text, package
    assert st.package_tier("decoy_engine.verification") == st.INTERNAL


def test_every_experimental_name_is_in_the_walk(walk) -> None:
    exports, tiers, _ = walk
    found = {n for (m, n), t in tiers.items() if t == st.EXPERIMENTAL}
    objects = {q.split(".")[0] for _, q in st.EXPERIMENTAL_OBJECTS}
    assert objects | set(st.EXPERIMENTAL_CONSTANTS[1]) == found, found ^ objects


def test_optional_extra_is_a_declared_extra_of_the_package() -> None:
    """AT-X0e: the registered missing dependency is one the project names as an extra."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    extras = pyproject.split("[project.optional-dependencies]")[1].split("\n[")[0]
    declared = set(re.findall(r"^([a-z0-9_-]+) = \[", extras, flags=re.M))
    assert st.OPTIONAL_EXTRAS, "no optional-extra package registered"
    for package, extra in st.OPTIONAL_EXTRAS.items():
        assert extra in declared, f"{package}: {extra} is not an optional dependency"
        assert (ROOT / "src" / "decoy_engine" / package.replace(".", "/") / "__init__.py").is_file()


def _fixture_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wanted: str) -> None:
    pkg = tmp_path / "fx_optional"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        textwrap.dedent(
            f"""
            try:
                import {wanted}  # noqa: F401
            except ModuleNotFoundError as exc:
                raise ImportError("needs the extra") from exc
            __all__ = ["Thing", "make_thing"]
            """
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "fx_optional", raising=False)


def test_a_registered_missing_extra_is_classified_statically(tmp_path, monkeypatch) -> None:
    """AT-X0e: the package cannot import, but its declared names still get a tier."""
    _fixture_package(tmp_path, monkeypatch, "fx_missing_dependency")
    monkeypatch.setitem(st.OPTIONAL_EXTRAS, "fx_optional", "fx_missing_dependency")
    exports, _ = census.load(["fx_optional"], extra=())
    assert [(e.name, e.static) for e in exports] == [("Thing", True), ("make_thing", True)]
    assert set(census.classify(exports).values()) == {st.INTERNAL}


def test_any_other_import_error_fails_the_walk(tmp_path, monkeypatch) -> None:
    """AT-X0e: only the registered dependency may be missing."""
    _fixture_package(tmp_path, monkeypatch, "fx_missing_dependency")
    monkeypatch.setitem(st.OPTIONAL_EXTRAS, "fx_optional", "some_other_extra")
    with pytest.raises(AssertionError, match="unregistered import failure"):
        census.load(["fx_optional"], extra=())


def test_a_second_tier_for_one_object_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """AT-X0a: seeded second row; the census must see the clash it exists to catch."""
    exports, _ = census.load(["decoy_engine.config"])
    rows = (*st.TIER_EXCEPTIONS, ("decoy_engine", "FileSource", st.FROZEN))
    monkeypatch.setattr(st, "TIER_EXCEPTIONS", rows)
    with pytest.raises(AssertionError, match="one object, two tiers"):
        census.classify(exports)
