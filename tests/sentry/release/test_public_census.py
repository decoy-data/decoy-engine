"""X0 (freeze batch plan 4.1, 8): every public engine name has exactly one stability tier.

The census walks `decoy_engine.__all__`, `decoy_engine.sdk`, `decoy_engine.providers` and every
public subpackage that declares `__all__` (the floors below are the measured walk). A tier belongs
to an object and applies to every path that exports it, so an object exported from two places
must get the same tier in both.
"""

from __future__ import annotations

import ast
import re
import sys
import textwrap
from pathlib import Path

import pytest

import decoy_engine
import decoy_engine.sdk as sdk_module
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
    for name in ("FileSource", "FileSink", "ConnectorConfig", "SDK_VERSION", "CAP_STREAMING"):
        assert tiers[("decoy_engine", name)] == tiers[("decoy_engine.sdk", name)] == st.EXPERIMENTAL
    assert tiers[("decoy_engine", "run_pipeline")] == st.FROZEN
    assert tiers[("decoy_engine", "register_faker_provider")] == st.EXPERIMENTAL


def test_errors_reached_through_sdk_stay_frozen(walk) -> None:
    """AT-X0f: the tier follows the object, not the `sdk` name that exports it."""
    _, tiers, _ = walk
    for name in ("ConfigError", "ConnectorError"):
        assert tiers[("decoy_engine.sdk", name)] == tiers[("decoy_engine", name)] == st.FROZEN
    assert tiers[("decoy_engine.sdk", "TransientError")] == st.EXPERIMENTAL


def test_everything_sdk_defines_is_experimental(walk) -> None:
    """H2: derived from where the object is defined, so a new sdk name cannot dodge the tier."""
    exports, tiers, _ = walk
    sdk = [e for e in exports if e.module == "decoy_engine.sdk" and e.obj is not None]
    tree = ast.parse(Path(sdk_module.__file__ or "").read_text(encoding="utf-8"))
    defined = {
        t.id
        for n in tree.body
        for t in (n.targets if isinstance(n, ast.Assign) else [getattr(n, "target", None)])
        if isinstance(t, ast.Name) and isinstance(n, (ast.Assign, ast.AnnAssign))
    }
    for e in sdk:
        owns = e.name in defined if not callable(e.obj) else e.obj.__module__ == "decoy_engine.sdk"
        assert (tiers[(e.module, e.name)] == st.EXPERIMENTAL) == owns, e.name
    assert sum(1 for e in sdk if tiers[(e.module, e.name)] == st.EXPERIMENTAL) >= 15


def test_one_object_has_one_tier_on_every_path(walk) -> None:
    """M2 and M3: functions, classes and constants alike, whatever package re-exports them."""
    _, tiers, _ = walk
    for name in ("FILE_SOURCE_PATH_FIELDS", "RUN_RESULT_SCHEMA", "SEED_PROTOCOL_VERSION"):
        found = {t for (m, n), t in tiers.items() if n == name}
        assert found == {st.FROZEN}, (name, found)


def test_the_walk_meets_the_measured_floors(walk) -> None:
    """AT-X0e: 59 packages and 1,186 names; a walk that skips a package fails here."""
    exports, _, declared = walk
    importable = [e for e in exports if not e.static and e.module not in census.EXTRA_MODULES]
    assert len(declared) >= MIN_PACKAGES, f"only {len(declared)} public packages walked"
    assert len(importable) >= MIN_NAMES, f"only {len(importable)} public names walked"
    assert {"decoy_engine.sdk", "decoy_engine.providers"} <= {e.module for e in exports}


def test_a_public_package_without_all_is_on_the_counted_list() -> None:
    """L5: a package that declares no `__all__` must be listed, and the list stays exact."""
    assert census.packages_without_all() == sorted(st.NO_ALL_PACKAGES)
    assert len(st.NO_ALL_PACKAGES) == 23


def test_exceptions_are_unique_and_not_stale(walk) -> None:
    """AT-X0e: an exception row names a real export once, with a real tier."""
    exports, _, _ = walk
    keys = [(m, n) for m, n, _ in st.TIER_EXCEPTIONS]
    assert len(keys) == len(set(keys)), "duplicate tier exception"
    assert set(keys) <= {(e.module, e.name) for e in exports}, "stale tier exception"
    assert {t for _, _, t in st.TIER_EXCEPTIONS} <= set(st.TIERS)


def _contract_3_4() -> str:
    return section(CONTRACT, "### 3.4 The public API + CLI contract")


def _named(text: str, path: str) -> bool:
    spellings = (path, path.replace(".", "/") + ".py")
    return any(re.search(re.escape(p) + r"(?![\w.])", text) for p in spellings)


def test_every_frozen_package_and_exception_is_named_by_contract_3_4() -> None:
    """Contract 3.4 is the only source of a frozen path; everything else is internal."""
    text = _contract_3_4()
    assert set(st.PACKAGE_TIERS) == {"decoy_engine", "decoy_engine.sdk"}
    for package, tier in st.PACKAGE_TIERS.items():
        assert tier in st.TIERS
        if package != "decoy_engine":
            assert _named(text, package), package
    for module, name, tier in st.TIER_EXCEPTIONS:
        assert tier == st.FROZEN and _named(text, name), f"3.4 does not name {module}.{name}"
    assert st.package_tier("decoy_engine.verification") == st.INTERNAL
    assert st.package_tier("decoy_engine.profiling") == st.INTERNAL


def test_the_package_match_is_anchored() -> None:
    """L2: `decoy_engine.profile` is not found inside `decoy_engine.profiling`."""
    assert not _named("see decoy_engine.profiling here", "decoy_engine.profile")
    assert not _named("see decoy_engine.profile.x here", "decoy_engine.profile")
    assert _named("the `decoy_engine/sdk.py` file", "decoy_engine.sdk")
    assert _named("module decoy_engine.sdk, and", "decoy_engine.sdk")


def test_experimental_objects_outside_sdk_are_real_exports(walk) -> None:
    exports, tiers, _ = walk
    listed = {q.split(".")[0] for _, q in st.EXPERIMENTAL_OBJECTS}
    assert listed <= census.experimental_names(tiers)
    assert census.experimental_names(tiers) - listed >= {"FileSource", "SDK_VERSION"}


def test_optional_extra_is_a_declared_extra_of_the_package() -> None:
    """AT-X0e: the registered missing dependency is one the project names as an extra."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    extras = pyproject.split("[project.optional-dependencies]")[1].split("\n[")[0]
    declared = set(re.findall(r"^([a-z0-9_-]+) = \[", extras, flags=re.M))
    assert st.OPTIONAL_EXTRAS, "no optional-extra package registered"
    for package, extra in st.OPTIONAL_EXTRAS.items():
        assert extra in declared, f"{package}: {extra} is not an optional dependency"
        assert (ROOT / "src" / "decoy_engine" / package.replace(".", "/") / "__init__.py").is_file()


def _fixture_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wanted: str, tail: str = ""
) -> None:
    pkg = tmp_path / "fx_optional"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        textwrap.dedent(
            f"""
            try:
                import {wanted}  # noqa: F401
            except ModuleNotFoundError as exc:
                raise ImportError("needs the extra") from exc
            """
        )
        + (tail or '__all__ = ["Thing", "make_thing"]\n')
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


def test_an_installed_dependency_is_not_tolerated(tmp_path, monkeypatch) -> None:
    """M1: a ModuleNotFoundError naming a module that does exist is a real failure."""
    _fixture_package(tmp_path, monkeypatch, "fx_missing_dependency")
    monkeypatch.setitem(st.OPTIONAL_EXTRAS, "fx_optional", "json")
    exc = ImportError("x")
    exc.__cause__ = ModuleNotFoundError("x", name="json")
    assert census.missing_extra("fx_optional", exc) is None
    exc.__cause__ = ModuleNotFoundError("x", name="fx_not_installed_anywhere")
    monkeypatch.setitem(st.OPTIONAL_EXTRAS, "fx_optional", "fx_not_installed_anywhere")
    assert census.missing_extra("fx_optional", exc) == "fx_not_installed_anywhere"


@pytest.mark.parametrize(
    ("tail", "expected"),
    [
        ('__all__: list[str] = ["A", "B"]\n', ["A", "B"]),
        ('__all__ = ["A"]\n__all__ += ["B"]\n', ["A", "B"]),
        ('__all__ = ("A",)\n', ["A"]),
    ],
)
def test_static_all_reads_every_literal_form(tmp_path, monkeypatch, tail, expected) -> None:
    """M1: annotated and augmented `__all__` are read, not dropped."""
    _fixture_package(tmp_path, monkeypatch, "fx_missing_dependency", tail)
    assert census.static_all("fx_optional") == expected


@pytest.mark.parametrize("tail", ["x = 1\n", "__all__ = build()\n"])
def test_static_all_fails_instead_of_returning_nothing(tmp_path, monkeypatch, tail) -> None:
    """M1: a package whose names cannot be read is an error, never an empty list."""
    _fixture_package(tmp_path, monkeypatch, "fx_missing_dependency", tail)
    with pytest.raises(AssertionError):
        census.static_all("fx_optional")


def test_a_second_tier_for_one_object_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """AT-X0a: seeded second row; the census must see the clash it exists to catch."""
    exports, _ = census.load(["decoy_engine.config"])
    rows = (*st.TIER_EXCEPTIONS, ("decoy_engine", "FileSource", st.FROZEN))
    monkeypatch.setattr(st, "TIER_EXCEPTIONS", rows)
    with pytest.raises(AssertionError, match="one object, two tiers"):
        census.classify(exports)


SEAM_NAMES = (
    "FROZEN",
    "EXPERIMENTAL",
    "INTERNAL",
    "TIERS",
    "EXPERIMENTAL_MARKER",
    "is_experimental_export",
    "tier_key",
)


def test_the_consumer_seam_names_import_from_the_stability_module() -> None:
    """AT-10: the CLI census imports these names; a rename fails here before it fails a repin."""
    namespace: dict[str, object] = {}
    exec(  # noqa: S102 - a fixed import statement, no input
        f"from decoy_engine.contracts.stability import {', '.join(SEAM_NAMES)}", namespace
    )
    assert set(SEAM_NAMES) <= namespace.keys()
    assert namespace["TIERS"] == (st.FROZEN, st.EXPERIMENTAL, st.INTERNAL)
    assert namespace["EXPERIMENTAL_MARKER"] == "Experimental:"


def test_the_seam_predicate_decides_the_sdk_cases() -> None:
    """AT-10: a constant, a class and a frozen `errors` object that `sdk` re-exports."""
    assert st.is_experimental_export("SDK_VERSION", sdk_module.SDK_VERSION)
    assert st.is_experimental_export("FileSource", sdk_module.FileSource)
    assert not st.is_experimental_export("ConfigError", sdk_module.ConfigError)
    assert st.is_experimental_export(
        "register_faker_provider", decoy_engine.register_faker_provider
    )


def test_the_seam_matches_a_constant_by_name_and_identity() -> None:
    """A constant `sdk` assigns is experimental under its own name and object only."""
    assert not st.is_experimental_export("OTHER_NAME", sdk_module.SDK_VERSION)
    assert not st.is_experimental_export("SDK_VERSION", object())
    assert not st.is_experimental_export(
        "SEED_PROTOCOL_VERSION", decoy_engine.SEED_PROTOCOL_VERSION
    )


def test_the_tier_key_is_the_object_or_the_name_and_the_object() -> None:
    """A callable is keyed by identity; a constant also by name, as small ints are shared."""
    assert st.tier_key("a", decoy_engine.run_pipeline) == st.tier_key(
        "b", decoy_engine.run_pipeline
    )
    assert st.tier_key("A", 7) != st.tier_key("B", 7)
    assert st.tier_key("A", 7) == st.tier_key("A", 7)
    assert st.tier_key("FileSource", sdk_module.FileSource) == st.tier_key(
        "FileSource", decoy_engine.FileSource
    )


def test_the_seam_fails_closed_when_the_sdk_source_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A constant is never called non-experimental because its source could not be read."""
    st._assigned_constants.cache_clear()
    try:
        monkeypatch.setattr(st.importlib.util, "find_spec", lambda _name: None)
        with pytest.raises(RuntimeError, match="decoy_engine.sdk"):
            st.is_experimental_export("SDK_VERSION", sdk_module.SDK_VERSION)
    finally:
        monkeypatch.undo()
        st._assigned_constants.cache_clear()


CENSUS_SOURCE = Path(census.__file__)
_TABLE_NAMES = {"EXPERIMENTAL_MODULE", "EXPERIMENTAL_OBJECTS"}
_DUNDERS = {"__module__", "__qualname__"}


def second_rule_problems(source: str, filename: str) -> list[str]:
    """E13: a census that names the experimental tables, reads an object's origin or calls
    `id()` decides a tier itself instead of calling the seam. Matches AST nodes, not text."""
    problems = []
    for node in ast.walk(ast.parse(source)):
        hit = (
            (isinstance(node, ast.Name) and node.id in _TABLE_NAMES)
            or (isinstance(node, ast.Attribute) and node.attr in _TABLE_NAMES | _DUNDERS)
            or (isinstance(node, ast.alias) and node.name in _TABLE_NAMES)
            or (isinstance(node, ast.Constant) and node.value in _TABLE_NAMES | _DUNDERS)
            or (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "id"
            )
        )
        if hit:
            line = getattr(node, "lineno", 0)
            problems.append(f"second engine tier rule in {filename}:{line}")
    return problems


def test_the_census_has_no_second_experimental_rule() -> None:
    """E13: the engine census calls the seam; it does not read the tables or object origins."""
    assert second_rule_problems(CENSUS_SOURCE.read_text(encoding="utf-8"), "_census.py") == []


@pytest.mark.parametrize(
    "line",
    [
        "x = st.EXPERIMENTAL_OBJECTS",
        "x = EXPERIMENTAL_MODULE",
        "from decoy_engine.contracts.stability import EXPERIMENTAL_OBJECTS as T",
        "x = obj.__module__",
        "x = getattr(obj, '__qualname__')",
        "x = id(obj)",
    ],
)
def test_the_second_rule_guard_sees_each_seeded_spelling(line: str) -> None:
    """E13: a guard that cannot see a seeded violation proves nothing."""
    assert second_rule_problems(f"\n{line}\n", "seed.py") == [
        "second engine tier rule in seed.py:2"
    ]
