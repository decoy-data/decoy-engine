"""AT-E6: the gated PR's suites came over byte-identical, except exactly the OQ-4 retirements.

``_pr335_manifest.json`` records the SHA-256 of every test file at the gated head ``06877527b``. The
fold may not edit, skip or delete any of them, and may retire only the three standalone cases and
the two excluded-writer files the plan names (docs/plans/2026-11-17-f33-v1.md, design note 1).
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = json.loads((Path(__file__).with_name("_pr335_manifest.json")).read_text("utf-8"))


def test_every_gated_test_file_is_byte_identical() -> None:
    bad = [
        path
        for path, digest in MANIFEST["unchanged"].items()
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest
    ]
    assert not bad, f"a gated test file changed: {bad}"


def test_the_package_test_directory_gained_only_new_files() -> None:
    known = set(MANIFEST["unchanged"]) | set(MANIFEST["retired_cases"])
    on_disk = {
        p.relative_to(ROOT).as_posix() for p in (ROOT / "tests/unit/signed_evidence").glob("*.py")
    }
    assert known <= on_disk


def test_only_the_three_standalone_cases_were_retired() -> None:
    for path, retired in MANIFEST["retired_cases"].items():
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        funcs = {n.name: ast.unparse(n) for n in tree.body if isinstance(n, ast.FunctionDef)}
        assert not set(retired) & set(funcs)
        for name, source in MANIFEST["kept_cases"][path].items():
            assert funcs.get(name) == source, f"{name} was edited"
        assert set(funcs) - set(MANIFEST["kept_cases"][path]) == set()


def test_the_excluded_writer_is_not_brought_over() -> None:
    for path in MANIFEST["retired_files"]:
        assert not (ROOT / path).exists(), path
    assert not (ROOT / "src/decoy_engine/evidence_release").exists()
    assert not (ROOT / "tests/unit/evidence_release").exists()
    for path in (ROOT / "src/decoy_engine").rglob("*.py"):
        assert "hash_file_under" not in path.read_text(encoding="utf-8"), path.name
