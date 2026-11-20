"""Sentry: the platform census (Windows plan D9, finding M4).

Every read of `os.name`, `sys.platform`, `platform.system` or the engine's one `_osflags.WINDOWS`
(by attribute or by `from` import, under any alias) is counted per module. A module's count must
equal its committed entry, and a module not in the table must read none. The count moves in
both directions: a new read fails until the entry is raised in review, a removed read fails
until the entry shrinks. After the build each entry is shrink-only. The table is not a place to
park a read: raising an entry past the plan's budget stops for plan review.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.sentry._platform_ast import (
    OSFLAGS,
    SRC,
    WINDOWS_NAME,
    engine_trees,
    import_map,
    resolve,
)

PLATFORM_READS = frozenset({"os.name", "sys.platform", "platform.system", WINDOWS_NAME})
DIR_FD_NAME = f"{OSFLAGS}.DIR_FD"
# `_osflags.DIR_FD` is a capability probe (does this `os` take `dir_fd=`?), not a platform
# test, so it sits outside D9 and is not counted in CENSUS. Reading it is still a platform
# switch in effect, so only these modules may read it; a new reader is a review decision.
DIR_FD_ALLOWLIST = frozenset({"decoy_engine/fileaccess/_rooted.py"})

# Exact per-module counts, measured after slice EW1. Keys are paths under `src/`. Registered as
# the shrink-only `platform-census` baseline: the ratchet never lets an entry's `max` rise.
CENSUS: dict[str, int] = {
    "decoy_engine/execution/_isolated_commit.py": 1,
    "decoy_engine/execution/_isolated_common.py": 1,
    "decoy_engine/fileaccess/_fdtree.py": 4,
    "decoy_engine/fileaccess/_reclaim.py": 2,
    "decoy_engine/fileaccess/_local.py": 11,
    "decoy_engine/fileaccess/_openat2.py": 2,
    "decoy_engine/fileaccess/_osflags.py": 1,
    "decoy_engine/fileaccess/_output.py": 1,
    "decoy_engine/fileaccess/_protected_dir.py": 4,
    "decoy_engine/fileaccess/_rooted.py": 1,
    "decoy_engine/fileaccess/_scratch.py": 2,
    "decoy_engine/quality/dp_provenance.py": 1,
    "decoy_engine/secret_providers/_local.py": 1,
    "decoy_engine/signed_evidence/_artifacts.py": 1,
}


def count_reads(
    tree: ast.AST, rel: str | None = None, names: frozenset[str] = PLATFORM_READS
) -> int:
    imap = import_map(tree, rel)
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.Attribute, ast.Name)) and resolve(node, imap) in names
    )


def observed(
    trees: dict[str, ast.Module], names: frozenset[str] = PLATFORM_READS
) -> dict[str, int]:
    counts = {rel: count_reads(tree, rel, names) for rel, tree in trees.items()}
    return {rel: n for rel, n in counts.items() if n}


def drift(found: dict[str, int], table: dict[str, int]) -> list[str]:
    out = []
    for rel in sorted(found.keys() | table.keys()):
        if found.get(rel, 0) != table.get(rel, 0):
            out.append(f"{rel}: table {table.get(rel, 0)}, observed {found.get(rel, 0)}")
    return out


def test_engine_platform_reads_match_the_census() -> None:
    bad = drift(observed(engine_trees(SRC)), CENSUS)
    assert not bad, "platform reads differ from the committed census (D9):\n" + "\n".join(bad)


def test_only_allow_listed_modules_read_the_dir_fd_probe() -> None:
    readers = set(observed(engine_trees(SRC), frozenset({DIR_FD_NAME})))
    assert readers == DIR_FD_ALLOWLIST, sorted(readers ^ DIR_FD_ALLOWLIST)


def test_a_seeded_dir_fd_read_is_caught(tmp_path: Path) -> None:
    text = (
        "from decoy_engine.fileaccess import _osflags\n\n\ndef f():\n    return _osflags.DIR_FD\n"
    )
    readers = observed(_seed(tmp_path, "seeded", text), frozenset({DIR_FD_NAME}))
    assert set(readers) == {"decoy_engine/seeded/seeded.py"}


def _seed(tmp_path: Path, name: str, text: str) -> dict[str, ast.Module]:
    package = tmp_path / "src" / "decoy_engine" / "seeded"
    package.mkdir(parents=True)
    (package / f"{name}.py").write_text(text, encoding="utf-8")
    return engine_trees(tmp_path / "src")


SEEDS = {
    "sys_platform": "import sys\n\n\ndef f():\n    return sys.platform\n",
    "os_name": "import os\n\n\ndef f():\n    return os.name\n",
    "platform_system": "import platform\n\n\ndef f():\n    return platform.system()\n",
    "attribute": (
        "from decoy_engine.fileaccess import _osflags\n\n\ndef f():\n    return _osflags.WINDOWS\n"
    ),
    "from_import": (
        "from decoy_engine.fileaccess._osflags import WINDOWS as W\n\n\ndef f():\n    return W\n"
    ),
    "aliased_module": "import sys as s\n\n\ndef f():\n    return s.platform\n",
    "from_sys": "from sys import platform\n\n\ndef f():\n    return platform\n",
}

RELATIVE_SEEDS = {
    "relative_from_import": (
        "decoy_engine/fileaccess/seeded.py",
        "from ._osflags import WINDOWS\n\n\ndef f():\n    return WINDOWS\n",
    ),
    "relative_module_import": (
        "decoy_engine/fileaccess/seeded.py",
        "from . import _osflags\n\n\ndef f():\n    return _osflags.WINDOWS\n",
    ),
    "relative_from_parent_package": (
        "decoy_engine/execution/seeded.py",
        "from ..fileaccess import _osflags\n\n\ndef f():\n    return _osflags.WINDOWS\n",
    ),
    "relative_in_package_init": (
        "decoy_engine/fileaccess/__init__.py",
        "from ._osflags import WINDOWS as W\n\n\ndef f():\n    return W\n",
    ),
}


@pytest.mark.parametrize("seed", sorted(RELATIVE_SEEDS))
def test_census_counts_a_relative_import_of_the_flag(seed: str) -> None:
    rel, text = RELATIVE_SEEDS[seed]
    assert count_reads(ast.parse(text), rel) == 1
    assert count_reads(ast.parse(text)) == 0  # no path, no resolution: why the sentry passes rel


@pytest.mark.parametrize("seed", sorted(SEEDS))
def test_census_catches_a_seeded_read_outside_the_table(tmp_path: Path, seed: str) -> None:
    bad = drift(observed(_seed(tmp_path, "seeded", SEEDS[seed])), {})
    assert bad == ["decoy_engine/seeded/seeded.py: table 0, observed 1"]


def test_census_fails_in_both_directions() -> None:
    assert drift({"a.py": 2}, {"a.py": 3}) == ["a.py: table 3, observed 2"]
    assert drift({"a.py": 3}, {"a.py": 2}) == ["a.py: table 2, observed 3"]
    assert drift({"a.py": 1}, {"a.py": 1}) == []


def test_census_is_not_vacuous() -> None:
    assert sum(observed(engine_trees(SRC)).values()) >= 25
