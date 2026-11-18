"""Freeze batch S1: the two unused base modules are gone and FormulaStrategy stays put.

AT-S1a: `internal/base` and `transforms/base` do not import, `transforms.__all__` is empty,
and `pyproject.toml` no longer lists `internal/base`.
AT-S1b: the draw-site label and both secret-material census rows still name a live
`FormulaStrategy.apply`, and the formula output is byte-identical to the pre-S1 output.
"""

from __future__ import annotations

import ast
import importlib
import json
import logging
from pathlib import Path

import pandas as pd
import pytest

import decoy_engine
import decoy_engine.transforms as transforms_pkg
from decoy_engine.execution.native._draw_sites_mask import MASK_FORMULA_DRAW_SITE
from decoy_engine.transforms.formula import FormulaStrategy

_ROOT = Path(__file__).resolve().parents[3]
_PKG = Path(decoy_engine.__file__).resolve().parent


@pytest.mark.parametrize("sub", ["internal.base", "transforms.base"])
def test_base_modules_do_not_import(sub: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(f"{decoy_engine.__name__}.{sub}")


def test_transforms_all_is_empty() -> None:
    assert transforms_pkg.__all__ == []
    assert not hasattr(transforms_pkg, "BaseMaskingStrategy")


def test_pyproject_has_no_internal_base_entry() -> None:
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "internal/base" not in text
    assert "internal.base" not in text


def test_formula_strategy_is_a_plain_class() -> None:
    assert FormulaStrategy.__mro__ == (FormulaStrategy, object)
    FormulaStrategy()


def _class_defines(path: Path, cls: str, method: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return any(isinstance(n, ast.FunctionDef) and n.name == method for n in node.body)
    return False


def test_draw_site_label_resolves_to_live_apply() -> None:
    rel, _, qual = MASK_FORMULA_DRAW_SITE.call_site.partition("::")
    assert qual == "FormulaStrategy.apply"
    cls, _, method = qual.partition(".")
    assert _class_defines(_PKG / rel, cls, method)
    assert callable(FormulaStrategy.apply)


def test_secret_census_rows_resolve_to_live_apply() -> None:
    sentry = _ROOT / "tests" / "sentry"
    rows = json.loads((sentry / "secret_material_census.json").read_text(encoding="utf-8"))
    entries = rows["entries"] if isinstance(rows, dict) else rows
    census = [e for e in entries if e.get("function") == "FormulaStrategy.apply"]
    assert census, "census row for FormulaStrategy.apply is missing"
    for row in census:
        assert row["file"] == "decoy_engine/transforms/formula.py"
        assert _class_defines(_PKG.parent / row["file"], "FormulaStrategy", "apply")
    baseline = json.loads(
        (sentry / "baselines" / "secret-material-census.json").read_text(encoding="utf-8")
    )
    keys = [k for k in json.dumps(baseline).split('"') if "FormulaStrategy.apply" in k]
    assert keys == ["decoy_engine/transforms/formula.py::FormulaStrategy.apply::seed_material"]


def test_formula_golden_output_unchanged() -> None:
    s = FormulaStrategy()
    upper = s.apply(pd.Series(["ab", None, "cd"]), {"formula": "value.upper()+'!'", "column": "c"})
    assert upper.tolist() == ["AB!", None, "CD!"]
    drawn = s.apply(pd.Series([1, 2, 3, 4, 5, 6]), {"formula": "randint(0,10**6)", "column": "c"})
    assert drawn.tolist() == [481873, 840937, 688685, 736277, 548342, 184269]
    assert s.apply(pd.Series([1, 2]), {"column": "c"}).tolist() == [1, 2]


def test_missing_formula_warns_on_module_logger(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="decoy_engine.transforms.formula"):
        FormulaStrategy().apply(pd.Series([1]), {"column": "c"})
    assert [r.name for r in caplog.records] == ["decoy_engine.transforms.formula"]
