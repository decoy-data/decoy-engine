"""Every committed baseline or allowlist a sentry reads is registered and mirrored.

The ratchet only protects what ``sentry_registry.toml`` names. This test ties each live source
to its registered baseline (same key set) and fails when a sentry reads a committed list that is
not registered, so a new allowlist cannot slip in beside the ratchet.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _baseline_sources as bs

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

LIST_NAME = re.compile(
    r"ALLOW|EXEMPT|WAIVER|SEAMS|DELIBERATELY|E0_TEST_FILES|BASELINE|EXCEPTION|CENSUS|LIMITS"
)
DATA_LITERAL = re.compile(r"[\w.\-]+\.(?:json|toml)$")
IGNORED_DATA = {"pyproject.toml", "Cargo.toml", "package.json", "e1-1.json"}


def registry() -> dict[str, str]:
    text = (bs.ROOT / "scripts" / "dev" / "sentry_registry.toml").read_text(encoding="utf-8")
    return {r["id"]: r["baseline"] for r in tomllib.loads(text).get("sentry", [])}


@pytest.mark.parametrize("src", bs.SOURCES, ids=lambda s: s.sentry_id)
def test_source_matches_its_registered_baseline(src: bs.Source) -> None:
    rel = registry().get(src.sentry_id)
    assert rel == f"tests/sentry/baselines/{src.sentry_id}.json", "sentry not registered"
    doc = json.loads((bs.ROOT / rel).read_text(encoding="utf-8"))
    assert doc["sentry_id"] == src.sentry_id
    live, recorded = src.keys(), set(doc["entries"])
    assert live - recorded == set(), "live entries missing from the baseline"
    assert recorded - live == set(), "stale baseline entries (shrink the baseline)"
    for field, bounds in (("max", src.maxes), ("min", src.mins)):
        recorded_bounds = {k: e[field] for k, e in doc["entries"].items() if field in e}
        assert all(type(v) is int for v in recorded_bounds.values()), f"a {field} is not an integer"
        assert recorded_bounds == (bounds() if bounds else {}), (
            f"a recorded {field} differs from the live value, or an entry carries a {field} "
            "the source does not declare"
        )


def _is_count(value: object) -> bool:
    """An int that is not a bool, or a tuple holding one: a value the ratchet must see as a bound."""
    if isinstance(value, tuple):
        return any(_is_count(v) for v in value)
    return isinstance(value, int) and not isinstance(value, bool)


def numeric_in_code_sources(sources: tuple[bs.Source, ...]) -> list[str]:
    """Ids of in-code sources with a numeric value and no ``maxes`` (their raise is invisible)."""
    out = []
    for s in sources:
        if isinstance(s.keys, bs.InCode) and s.maxes is None:
            table = getattr(s.keys._module(), s.keys.constant)
            if isinstance(table, dict) and any(_is_count(v) for v in table.values()):
                out.append(s.sentry_id)
    return sorted(out)


def test_every_numeric_in_code_source_declares_max() -> None:
    """A source with an integer value, or a tuple holding one, must emit it as ``max``."""
    assert numeric_in_code_sources(bs.SOURCES) == []
    seeded = bs.Source("seeded", "t.py", bs.in_code("test_module_size.py", "ALLOWLIST"))
    assert numeric_in_code_sources((seeded,)) == ["seeded"]  # ints under an undeclared max
    assert {"module-size", "package-fanout", "locator-waivers", "log-interpolation"} <= {
        s.sentry_id for s in bs.SOURCES if s.maxes is not None
    }


def test_limits_list_is_seen_by_the_reader_scan() -> None:
    consts, files = _covered()
    seeded = {"layout/_new.py": "LIMITS: dict[str, str] = {'a.py': 'max'}\n"}
    assert unregistered_readers(seeded, set(), consts, files) == ["layout/_new.py: constant LIMITS"]


def test_live_limit_constants_match_recorded_bounds() -> None:
    """The ``sentry-limits`` baseline records each live scalar bound, caps as ``max`` and
    floors as ``min``, and no entry carries both."""
    src = next((s for s in bs.SOURCES if s.sentry_id == "sentry-limits"), None)
    assert src is not None, "sentry-limits is not a registered source"
    assert src.maxes is not None and src.mins is not None
    doc = json.loads((bs.BASELINES / "sentry-limits.json").read_text(encoding="utf-8"))
    entries = doc["entries"]
    assert {k: e["max"] for k, e in entries.items() if "max" in e} == src.maxes()
    assert {k: e["min"] for k, e in entries.items() if "min" in e} == src.mins()
    assert not [k for k, e in entries.items() if "max" in e and "min" in e]
    assert set(entries) == src.keys()


def test_registry_has_no_source_less_sentry() -> None:
    assert set(registry()) == {s.sentry_id for s in bs.SOURCES}


def unregistered_readers(
    sources: dict[str, str],
    data_files: set[str],
    covered_consts: set[tuple[str, str]],
    covered_files: set[str],
) -> list[str]:
    """Allowlist-shaped module constants and committed data files read but not registered."""
    found = []
    for name, text in sources.items():
        tree = ast.parse(text)
        for node in tree.body:
            targets = (
                node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
            )
            for t in targets:
                is_list = isinstance(t, ast.Name) and LIST_NAME.search(t.id)
                is_coll = isinstance(
                    getattr(node, "value", None), (ast.Dict, ast.Tuple, ast.List, ast.Set)
                )
                if is_list and is_coll and (name, t.id) not in covered_consts:
                    found.append(f"{name}: constant {t.id}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                base = node.value.rsplit("/", 1)[-1]
                if (
                    DATA_LITERAL.fullmatch(base)
                    and base in data_files
                    and base not in covered_files
                ):
                    found.append(f"{name}: data file {base}")
    return sorted(set(found))


def _covered() -> tuple[set[tuple[str, str]], set[str]]:
    files = set(bs.NOT_A_LIST) | IGNORED_DATA | {Path(s.where).name for s in bs.SOURCES}
    consts = {
        (s.keys.test_file, s.keys.constant) for s in bs.SOURCES if hasattr(s.keys, "constant")
    }
    return consts, files


def _data_files() -> set[str]:
    return {
        p.name
        for root in ("tests", "docs")
        for p in (bs.ROOT / root).rglob("*")
        if p.suffix in {".json", ".toml"}
    }


def _scanned(path: Path) -> bool:
    """Every sentry test, in any subfolder, plus the helper modules that hold a table.

    Seeded fixture sources are inputs to a sentry, not sentries, so they are not read.
    """
    rel = path.relative_to(bs.SENTRY).parts
    return rel[0] not in {"fixtures", "fa_fixtures", "__pycache__"} and not path.name.startswith(
        "conftest"
    )


def test_no_sentry_reads_an_unregistered_baseline() -> None:
    consts, files = _covered()
    sources = {
        p.relative_to(bs.SENTRY).as_posix(): p.read_text(encoding="utf-8")
        for p in bs.SENTRY.rglob("*.py")
        if _scanned(p)
    }
    sources.pop("test_baseline_registry.py")  # holds the seeded fixtures below
    assert unregistered_readers(sources, _data_files(), consts, files) == []


def test_seeded_unregistered_readers_are_caught() -> None:
    consts, files = _covered()
    seeded_const = {"test_new.py": 'NEW_ALLOWLIST = {"a::b": "why"}\n'}
    assert unregistered_readers(seeded_const, set(), consts, files) == [
        "test_new.py: constant NEW_ALLOWLIST"
    ]
    seeded_file = {"test_new.py": 'P = ROOT / "tests" / "fixtures" / "fresh-list.json"\n'}
    assert unregistered_readers(seeded_file, {"fresh-list.json"}, consts, files) == [
        "test_new.py: data file fresh-list.json"
    ]


def test_exception_and_census_tables_in_subfolders_are_caught() -> None:
    """The EW1 gap: inline `*_EXCEPTIONS` and `*_CENSUS` tables, one in a subfolder, bypassed this."""
    consts, files = _covered()
    seeded = {
        "layout/_new.py": 'SCOPED_EXCEPTIONS = {("a.py", "u"): "why"}\n',
        "test_new.py": 'CENSUS: dict[str, int] = {"a.py": 1}\n',
    }
    assert unregistered_readers(seeded, set(), consts, files) == [
        "layout/_new.py: constant SCOPED_EXCEPTIONS",
        "test_new.py: constant CENSUS",
    ]


def test_the_scan_reaches_sentry_subfolders() -> None:
    names = {p.relative_to(bs.SENTRY).as_posix() for p in bs.SENTRY.rglob("*.py") if _scanned(p)}
    assert "layout/_scoped_changes.py" in names
    assert "layout/test_package_fanout.py" in names


# Sentry files the discovery scan skips, each with the reason. A skipped file must be pinned by
# another check, so its constants cannot change unseen.
UNSCANNED: dict[str, str] = {
    "ci_scan/test_identity.py": (
        "byte-identical copy shared with the CLI repo and pinned by the ci-lock ledger; its "
        "REPO, COMMIT, PATH tuple is a fixture, not a bound"
    ),
}
UPPER = re.compile(r"_*[A-Z][A-Z0-9_]*")


REFUSED = "must be one module-level NAME = <int> statement"


def _upper_candidates(sources: dict[str, str]) -> dict[tuple[str, str], int | None]:
    parse = bs._limits().int_constants
    return {
        (rel, name): value
        for rel, text in sources.items()
        for name, value in parse(ast.parse(text)).items()
        if UPPER.fullmatch(name)
    }


def module_int_constants(sources: dict[str, str]) -> set[tuple[str, str]]:
    """``(file, NAME)`` of every module-level UPPER_CASE (private or not) candidate bound in
    ``sources`` (``{path under tests/sentry: text}``), plain or refused."""
    return set(_upper_candidates(sources))


def refused_constants(sources: dict[str, str]) -> list[str]:
    """One fixed, value-free message per UPPER_CASE candidate the reader refuses, sorted."""
    return sorted(
        f"{rel}::{name} {REFUSED}"
        for (rel, name), value in _upper_candidates(sources).items()
        if value is None
    )


def _sentry_sources() -> dict[str, str]:
    return {
        p.relative_to(bs.SENTRY).as_posix(): p.read_text(encoding="utf-8")
        for p in bs.SENTRY.rglob("*.py")
        if p.relative_to(bs.SENTRY).as_posix() not in UNSCANNED
    }


def test_every_module_int_is_a_bound_or_named() -> None:
    """Every module-level UPPER_CASE integer literal under tests/sentry is a recorded bound or
    carries a reason it is not one, so a new limit cannot sit outside the ratchet."""
    lc = bs._limits()
    known = set(lc.LIMITS) | set(lc.NOT_A_BOUND)
    assert refused_constants(_sentry_sources()) == [], "a constant the reader refuses"
    found = module_int_constants(_sentry_sources())
    assert sorted(found - known) == [], "an integer constant is neither a bound nor named"
    assert sorted(known - found) == [], "a LIMITS or NOT_A_BOUND row names no constant"
    assert not set(lc.LIMITS) & set(lc.NOT_A_BOUND)
    assert all(len(r) >= 20 for r in lc.NOT_A_BOUND.values()), "a NOT_A_BOUND row needs a reason"
    assert all(len(r) >= 20 for r in UNSCANNED.values()), "an UNSCANNED file needs a reason"


@pytest.mark.parametrize(
    "path, text",
    [
        ("test_baseline_registry.py", "NEW_CAP = 99\n"),
        ("test_x.py", "_NEW_CAP = 99\n"),
        ("test_x.py", "NEW_FLOOR = -5\n"),
    ],
)
def test_the_discovery_scan_sees_each_spelling(path: str, text: str) -> None:
    assert module_int_constants({path: text})
    assert not module_int_constants({path: "lower = 5\nFLAG = True\nNAME = 'x'\nX = 1.5\n"})


def test_the_discovery_scan_reads_every_sentry_file() -> None:
    assert "test_baseline_registry.py" in _sentry_sources()
    assert set(UNSCANNED) == {"ci_scan/test_identity.py"}
    assert all((bs.SENTRY / rel).is_file() for rel in UNSCANNED)
    assert not set(UNSCANNED) & set(_sentry_sources())


def limit_problems(
    entries: dict[str, dict[str, object]],
    maxes: dict[str, int],
    mins: dict[str, int],
    keys: set[str],
) -> list[str]:
    """The ``sentry-limits`` entries against the live maps: every key has exactly one integer
    bound, of the direction the live source gives it, equal to the live value."""
    out = []
    if set(maxes) | set(mins) != keys or set(maxes) & set(mins):
        out.append("the numeric maps do not cover the keys exactly once")
    for key, entry in sorted(entries.items()):
        bounds = {f: entry[f] for f in ("max", "min") if f in entry}
        live = {
            **{k: ("max", v) for k, v in maxes.items()},
            **{k: ("min", v) for k, v in mins.items()},
        }
        if len(bounds) != 1 or any(type(v) is not int for v in bounds.values()):
            out.append(f"{key}: needs exactly one integer max or min")
        elif live.get(key) != next(iter(bounds.items())):
            out.append(f"{key}: recorded bound differs from the live one")
    return out


def test_live_limit_entries_have_exactly_one_matching_bound() -> None:
    lc = bs._limits()
    assert lc.direction_problems(lc.LIMITS) == []
    src = next(s for s in bs.SOURCES if s.sentry_id == "sentry-limits")
    assert src.maxes is not None and src.mins is not None
    doc = json.loads((bs.BASELINES / "sentry-limits.json").read_text(encoding="utf-8"))
    assert limit_problems(doc["entries"], src.maxes(), src.mins(), src.keys()) == []


def test_a_misspelled_direction_and_a_reason_only_entry_are_caught() -> None:
    lc = bs._limits()
    assert lc.direction_problems({("a.py", "C"): "floor"}) == [
        "a.py::C: direction 'floor' is not one of max, min"
    ]
    # the key survives in the baseline with a reason only, so key parity alone would pass
    entries: dict[str, dict[str, object]] = {"a.py::C": {"reason": "r"}}
    assert limit_problems(entries, {}, {}, {"a.py::C"})
    assert limit_problems({"a.py::C": {"min": 1}}, {"a.py::C": 1}, {}, {"a.py::C"})
    assert not limit_problems({"a.py::C": {"min": 1}}, {}, {"a.py::C": 1}, {"a.py::C"})


def test_limit_constants_are_imported_never_rederived() -> None:
    """A consumer of a ``LIMITS`` constant must import it by name from its home file and use it
    only as a comparison operand; lowering it in the consumer would pass every other check."""
    lc = bs._limits()
    sources = _sentry_sources()
    problems = []
    for (file, name), _ in lc.LIMITS.items():
        home = Path(file).stem
        for rel, text in sources.items():
            if rel != file and name in text:
                problems += [f"{rel}: {p}" for p in lc.consumer_problems(text, name, home)]
    assert problems == []


def test_a_misspelled_direction_fails_the_live_maps(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = bs._limits()
    mod.LIMITS = {**mod.LIMITS, ("test_module_size.py", "GOAL"): "floor"}
    monkeypatch.setattr(bs, "_limits", lambda: mod)
    for kind in ("max", "min"):
        with pytest.raises(ValueError, match="direction 'floor'"):
            bs.live_bounds(kind)


def test_a_signed_bound_is_read_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Discovery and the live read share one parser: a signed literal that discovery finds must
    also read, or a registered bound would raise instead of ratchet."""
    (tmp_path / "test_new.py").write_text(
        "_NEW_FLOOR = -5\nMIN_A = 59\nMIN_B = 1186\n", encoding="utf-8"
    )
    mod = bs._limits()
    mod.LIMITS = {
        ("test_new.py", "_NEW_FLOOR"): "min",
        ("test_new.py", "MIN_A"): "min",
        ("test_new.py", "MIN_B"): "min",
    }
    monkeypatch.setattr(bs, "_limits", lambda: mod)
    monkeypatch.setattr(bs, "SENTRY", tmp_path)
    assert bs.live_bounds("min") == {
        "test_new.py::_NEW_FLOOR": -5,
        "test_new.py::MIN_A": 59,
        "test_new.py::MIN_B": 1186,
    }
    found = module_int_constants({"test_new.py": (tmp_path / "test_new.py").read_text()})
    assert found == {("test_new.py", n) for _, n in mod.LIMITS}


def test_the_census_floors_are_discovered_and_registered() -> None:
    """The census floors are two plain lines: discovery finds them, the reader accepts them and
    each carries a recorded floor."""
    found = module_int_constants(_sentry_sources())
    lc = bs._limits()
    census = {"release/test_public_census.py": _sentry_sources()["release/test_public_census.py"]}
    assert refused_constants(census) == []
    for name in ("MIN_PACKAGES", "MIN_NAMES"):
        assert ("release/test_public_census.py", name) in found
        assert lc.LIMITS[("release/test_public_census.py", name)] == "min"
