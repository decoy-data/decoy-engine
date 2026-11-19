"""REL-GATE RG-F1 (plan 5.1, design note 1): every frozen engine surface has a row in the map.

`docs/frozen-surfaces.md` names, for each surface, the code that owns it and the test that pins it.
The sources of "every" are read here, not copied: the tag block of compatibility-contract 3.1, and
`decoy_engine.__all__` plus `decoy_engine.sdk.__all__` (3.4). A surface with no pinning test says
`accepted-known-limit: <id>`, and that id must be in the map's known-limits table.
"""

from __future__ import annotations

import collections
import re
from pathlib import Path

from scripts.release.frozen_map import rows

import decoy_engine
import decoy_engine.sdk
from tests.sentry.layout import map_paths, section
from tests.sentry.release import _census

ROOT = Path(__file__).resolve().parents[3]
MAP = ROOT / "docs" / "frozen-surfaces.md"
CONTRACT = ROOT / "docs" / "compatibility-contract.md"
TAGS_HEADING = "## Format tags (contract 3.1, 3.2)"
NAMES_HEADING = "## Public names (contract 3.4)"
EXPERIMENTAL_HEADING = "## Experimental surfaces (contract 3.6)"
OTHER_HEADING = "## Other frozen surfaces"
LIMITS_HEADING = "## Known limits"
_TAG = re.compile(r"[a-z0-9-]+/v\d+")
_SPAN = re.compile(r"`([^`]+)`")
_LIMIT = re.compile(r"accepted-known-limit: ([^\s`]+)`")
# Design note 1 sources with no list to read from code: each must keep its one row.
OTHER_SURFACES = (
    "Pipeline YAML schema",
    "Run-result schema",
    "Determinism",
    "Disguise registry",
    "Reason registry",
    "Engine version literal",
)


def contract_tags(contract: str) -> list[str]:
    """The literal tags in the first code block of 3.1; `...` and the parenthetical carry none."""
    block = section(contract, "### 3.1 Persisted artifact formats (the biggest surface)").split(
        "```"
    )[1]
    return _TAG.findall(block)


def surface_counts(table: str) -> collections.Counter[str]:
    return collections.Counter(span for row in rows(table) for span in _SPAN.findall(row[0]))


def public_names() -> set[str]:
    return set(decoy_engine.__all__) | {f"sdk.{name}" for name in decoy_engine.sdk.__all__}


def registry_tiers() -> dict[tuple[str, str], str]:
    exports, _ = _census.load([])
    return _census.classify(exports)


def experimental_names() -> set[str]:
    """The registry's experimental set, spelled like the map (root bare, `sdk.` prefixed)."""
    return _census.experimental_public_names(registry_tiers())


def once_problems(expected: set[str], counts: collections.Counter[str]) -> list[str]:
    """Each expected item in exactly one row, and no row naming an item that is not expected."""
    problems = [f"{item}: {counts[item]} rows" for item in sorted(expected) if counts[item] != 1]
    return problems + [f"{item}: not a frozen item" for item in sorted(set(counts) - expected)]


def _map() -> str:
    return MAP.read_text(encoding="utf-8")


def test_every_contract_tag_has_a_row() -> None:
    tags = contract_tags(CONTRACT.read_text(encoding="utf-8"))
    assert len(tags) == len(set(tags)) >= 34, "the contract 3.1 tag block lost its tags"
    problems = once_problems(set(tags), surface_counts(section(_map(), TAGS_HEADING)))
    assert not problems, f"docs/frozen-surfaces.md format-tag rows: {problems}"


def test_every_public_name_has_a_row() -> None:
    """AT-X0c, frozen side: the registry's frozen set equals the frozen table, both ways.

    The frozen set is the root and `sdk` names that are not experimental, plus one name per
    frozen exception row. Experimental names have their own table.
    """
    tiers = registry_tiers()
    expected = _census.frozen_public_names(tiers)
    assert public_names() - experimental_names() <= expected, "a public name has no tier"
    problems = once_problems(expected, surface_counts(section(_map(), NAMES_HEADING)))
    assert not problems, f"docs/frozen-surfaces.md public-name rows: {problems}"


def test_the_experimental_table_equals_the_registry() -> None:
    """AT-X0c: both ways; a name in the table only, or in the registry only, fails."""
    names = experimental_names()
    assert len(names) >= 20, "the experimental registry lost its names"
    counts = surface_counts(section(_map(), EXPERIMENTAL_HEADING))
    problems = once_problems(names, counts)
    assert not problems, f"docs/frozen-surfaces.md experimental rows: {problems}"


def test_contract_3_6_lists_the_registry_experimental_names() -> None:
    """AT-X0d: the code block of section 3.6 names the same objects, one per line."""
    text = section(CONTRACT.read_text(encoding="utf-8"), "### 3.6 Experimental surfaces")
    block = text.split("```")[1].split("\n", 1)[1]
    listed = {line.strip() for line in block.splitlines() if line.strip()}
    registry = _census.experimental_names(registry_tiers())
    assert listed == registry, f"contract 3.6 vs registry: {sorted(listed ^ registry)}"


def row_problems(table: str, limits: set[str]) -> list[str]:
    """Each row names owning code under `src/` and a test file or a listed known limit."""
    problems = []
    for row in rows(table):
        if len(row) != 4 or not any(s.startswith("src/") for s in _SPAN.findall(row[2])):
            problems.append(f"{row[0]}: no owning code")
            continue
        tests = [s for s in _SPAN.findall(row[3]) if s.startswith("tests/") and s.endswith(".py")]
        cited = set(_LIMIT.findall(row[3]))
        if not (tests or cited):
            problems.append(f"{row[0]}: no test file and no known limit")
        problems += [f"{row[0]}: unknown limit {limit}" for limit in sorted(cited - limits)]
    return problems + [f"missing path {path}" for path in map_paths(table, ROOT, (2, 3))]


def _limits(text: str) -> set[str]:
    return {row[0].strip("`") for row in rows(section(text, LIMITS_HEADING))}


def test_every_row_names_owning_code_and_an_existing_test() -> None:
    text = _map()
    cited: set[str] = set()
    for heading in (TAGS_HEADING, NAMES_HEADING, EXPERIMENTAL_HEADING, OTHER_HEADING):
        table = section(text, heading)
        assert rows(table), f"{heading} has no rows"
        problems = row_problems(table, _limits(text))
        assert not problems, f"docs/frozen-surfaces.md {heading}: {problems}"
        cited |= set(_LIMIT.findall(table))
    assert _limits(text) == cited, f"known limits no row cites: {_limits(text) - cited}"


def test_every_other_surface_keeps_its_row() -> None:
    surfaces = [row[0] for row in rows(section(_map(), OTHER_HEADING))]
    counts = {name: sum(s.startswith(name) for s in surfaces) for name in OTHER_SURFACES}
    assert all(n == 1 for n in counts.values()), f"other-surface rows: {counts}"


# Seeded strings prove the parsers see each case the sentry relies on.

_SEEDED = "| Surface | Source | Code | Test |\n|---|---|---|---|\n| `a/v1` | x | `c` | `t` |\n| `b/v2`, `a/v1` | x | `c` | `t` |\n"


def test_contract_tags_skip_the_ellipsis_and_the_parenthetical() -> None:
    contract = "### 3.1 Persisted artifact formats (the biggest surface)\n\n```\nx/v1  y-z/v2\nq/v1   ... (every disguise spec)\n```\n"
    assert contract_tags(contract) == ["x/v1", "y-z/v2", "q/v1"]


def test_once_problems_reports_a_missing_a_doubled_and_a_stray_item() -> None:
    problems = once_problems({"a/v1", "c/v1"}, surface_counts(_SEEDED))
    assert problems == ["a/v1: 2 rows", "c/v1: 0 rows", "b/v2: not a frozen item"]


def test_row_problems_reports_each_bad_cell() -> None:
    table = (
        "| S | C | Code | Test |\n|---|---|---|---|\n"
        "| `a` | x | `pkg` | `tests/unit/test_public_api.py` |\n"
        "| `b` | x | `src/decoy_engine/unmask.py` | `tests/unit/` |\n"
        "| `c` | x | `src/decoy_engine/unmask.py` | `accepted-known-limit: KL-9` |\n"
        "| `d` | x | `src/decoy_engine/gone.py` | `tests/unit/test_vault.py` |\n"
    )
    assert row_problems(table, {"KL-1"}) == [
        "`a`: no owning code",
        "`b`: no test file and no known limit",
        "`c`: unknown limit KL-9",
        "missing path src/decoy_engine/gone.py -> src/decoy_engine/gone.py",
    ]
