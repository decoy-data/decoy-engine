"""AT-D9: `quality.dp_budget` no longer re-exports `OpenDpReleaseSession`.

The class lives in `quality.dp_session`; the lazy `__getattr__` that kept the old path alive is
deleted (pre-GA hard delete). The removal is recorded in the changelog fragment.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_the_old_import_path_is_gone() -> None:
    with pytest.raises(ImportError):
        exec("from decoy_engine.quality.dp_budget import OpenDpReleaseSession")  # noqa: S102


def test_the_module_has_no_dynamic_attribute_hook() -> None:
    mod = importlib.import_module("decoy_engine.quality.dp_budget")
    assert not hasattr(mod, "__getattr__")
    assert not hasattr(mod, "OpenDpReleaseSession")


def test_the_session_class_imports_from_its_own_module() -> None:
    from decoy_engine.quality.dp_session import OpenDpReleaseSession

    assert OpenDpReleaseSession.__name__ == "OpenDpReleaseSession"


def test_no_source_docstring_still_names_the_old_path() -> None:
    for rel in ("quality/dp.py", "quality/dp_session.py", "quality/dp_budget.py"):
        text = (ROOT / "src" / "decoy_engine" / rel).read_text(encoding="utf-8")
        assert "dp_budget.OpenDpReleaseSession" not in text, rel
