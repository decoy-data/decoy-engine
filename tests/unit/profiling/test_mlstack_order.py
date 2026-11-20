"""The ML stack imports in one order, from one place (Windows plan EW1, finding M1).

scikit-learn loads before lightgbm so both pick the same OpenMP runtime on Windows. The order
lives in `model_pack/_mlstack.py`; the trainer and the status probe both go through it.
"""

from __future__ import annotations

import ast
import builtins
import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3] / "src" / "decoy_engine" / "profiling" / "model_pack"


def _mlstack() -> ModuleType:
    try:
        return importlib.import_module("decoy_engine.profiling.model_pack._mlstack")
    except Exception:  # lightgbm needs libomp on macOS; the order check needs a loadable stack
        pytest.skip("lightgbm does not load on this host")


def test_sklearn_is_imported_before_lightgbm(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _mlstack()
    mod.import_ml_stack()  # load the stack first so submodule imports do not add to `seen`
    seen: list[str] = []
    real = builtins.__import__

    def record(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in {"sklearn", "lightgbm"}:
            seen.append(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", record)
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


def test_importing_mlstack_has_no_side_effect_when_lightgbm_is_a_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Import must not touch lightgbm: a stub without `LGBMClassifier` is not an import error."""
    import sys

    stub = ModuleType("lightgbm")
    monkeypatch.setitem(sys.modules, "lightgbm", stub)
    monkeypatch.delitem(sys.modules, "decoy_engine.profiling.model_pack._mlstack", raising=False)
    mod = importlib.import_module("decoy_engine.profiling.model_pack._mlstack")
    assert not hasattr(mod, "LGBMClassifier")
    with pytest.raises(AttributeError):
        mod.lgbm_classifier()
    stub.LGBMClassifier = object  # type: ignore[attr-defined]
    assert mod.lgbm_classifier() is object
