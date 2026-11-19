"""The ML stack imports in one order, from one place (Windows plan EW1, finding M1).

scikit-learn loads before lightgbm so both pick the same OpenMP runtime on Windows. The order
lives in `model_pack/_mlstack.py`; the trainer and the status probe both go through it.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3] / "src" / "decoy_engine" / "profiling" / "model_pack"


def _mlstack() -> ModuleType:
    try:
        return importlib.import_module("decoy_engine.profiling.model_pack._mlstack")
    except Exception:  # lightgbm needs libomp on macOS; the order check needs a loadable stack
        pytest.skip("lightgbm does not load on this host")


def test_sklearn_is_imported_before_lightgbm(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _mlstack()
    seen: list[str] = []
    real = importlib.import_module

    def record(name: str, package: str | None = None) -> ModuleType:
        seen.append(name)
        return real(name, package)

    monkeypatch.setattr(mod.importlib, "import_module", record)
    mod.import_ml_stack()
    assert seen == ["sklearn", "lightgbm"]


@pytest.mark.parametrize("module", ["trainer.py", "_detectors.py"])
def test_both_import_sites_go_through_the_helper(module: str) -> None:
    tree = ast.parse((ROOT / module).read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0
    }
    assert "decoy_engine.profiling.model_pack._mlstack" in imported
