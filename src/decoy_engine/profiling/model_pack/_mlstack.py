"""The one place that imports the ML stack, in the order it needs.

scikit-learn loads first and lightgbm second. On Windows both ship an OpenMP runtime
(`vcomp140.dll`), and the copy that loads first wins: lightgbm first can bind the wrong one and
break scikit-learn's threaded code. A single owner keeps the order from drifting between the
trainer and the status probe. The imports are plain statements so a test can
patch `builtins.__import__`; `isort: skip` keeps the sorter from re-ordering the pair.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any


def import_ml_stack() -> ModuleType:
    """Import scikit-learn, then lightgbm, and return lightgbm. Raises what the imports raise."""
    import sklearn  # noqa: F401  # isort: skip

    import lightgbm  # isort: skip

    return lightgbm


def lgbm_classifier() -> Any:
    """Return `lightgbm.LGBMClassifier`, importing the stack on first call.

    This is a function and not a module-level name so importing `_mlstack` has no side effect.
    A module-level `LGBMClassifier` made every importer pay for lightgbm and fail with
    AttributeError when a test stubbed `lightgbm` without the class.
    """
    return import_ml_stack().LGBMClassifier
