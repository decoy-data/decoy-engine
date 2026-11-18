"""F07 82-E2a: the scan-set core models moved to `profiling/_scan_core.py` without a change."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import decoy_engine
from decoy_engine import profiling

_ROOT = Path(__file__).resolve().parents[3]
_SNAPSHOT = _ROOT / "tests" / "fixtures" / "f07" / "scan-set-core-schema.json"

# Importer file -> the moved names it must take from `_scan_core`.
_IMPORTERS = {
    "src/decoy_engine/profiling/__init__.py": {"ScanSetCore", "ScanSetCoreRead"},
    "src/decoy_engine/profiling/scan_set_read.py": {"ScanSetCoreRead"},
    "src/decoy_engine/profiling/scan_diff.py": {"_relaxed"},
    "tests/unit/profiling/test_scan_set.py": {"TableCore"},
    "tests/unit/profiling/test_scan_integrity.py": {"RelationshipFactsCore"},
    "tests/unit/profiling/test_scanml_m3a_record.py": {
        "ModelHitCore",
        "ModelRefCore",
        "_DetectorRunCore",
    },
}


def _names_imported_from(path: str, module: str) -> set[str]:
    tree = ast.parse((_ROOT / path).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            found.update(a.name for a in node.names)
    return found


def test_schemas_equal_the_snapshot_taken_on_the_base() -> None:
    from decoy_engine.profiling._scan_core import ScanSetCore, ScanSetCoreRead

    snapshot = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    assert ScanSetCore.model_json_schema() == snapshot["ScanSetCore"]
    assert ScanSetCoreRead.model_json_schema() == snapshot["ScanSetCoreRead"]


def test_public_names_are_the_moved_classes() -> None:
    from decoy_engine.profiling import _scan_core

    assert profiling.ScanSetCore is _scan_core.ScanSetCore
    assert profiling.ScanSetCoreRead is _scan_core.ScanSetCoreRead
    assert decoy_engine.ScanSetCore is _scan_core.ScanSetCore
    assert decoy_engine.ScanSetCoreRead is _scan_core.ScanSetCoreRead


def test_importers_take_moved_names_from_scan_core() -> None:
    for path, names in _IMPORTERS.items():
        got = _names_imported_from(path, "decoy_engine.profiling._scan_core")
        assert names <= got, (path, sorted(names - got))


def test_scan_set_keeps_no_re_export_of_the_moved_names() -> None:
    moved = {
        "WarningRefCore", "ModelRefCore", "ModelHitCore", "RegexRunCore", "ModelRunCore",
        "FieldCore", "TableCore", "ChildFactsCore", "RelationshipFactsCore", "ScanSetCore",
        "ScanSetCoreRead", "_relaxed", "_Core", "_DetectorRunCore",
    }  # fmt: skip
    tree = ast.parse((_ROOT / "src/decoy_engine/profiling/scan_set.py").read_text(encoding="utf-8"))
    defined = {
        t.id
        for n in tree.body
        if isinstance(n, ast.Assign | ast.AnnAssign)
        for t in ([n.target] if isinstance(n, ast.AnnAssign) else n.targets)
        if isinstance(t, ast.Name)
    } | {n.name for n in tree.body if isinstance(n, ast.ClassDef | ast.FunctionDef)}
    assert not (moved & defined)
