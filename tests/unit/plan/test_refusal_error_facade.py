"""B6: `refusal_error` is one function reachable from the `plan` facade in either import order.

The transforms import it from `decoy_engine.plan` while the package initializes, so a clean
interpreter must work whether the facade or a transform is imported first.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

_FIRST = [
    "decoy_engine.plan",
    "decoy_engine.transforms.joint_mask",
    "decoy_engine.transforms._codeset_config_checks",
    "decoy_engine.transforms._codeset_loader",
    "decoy_engine.transforms.corpus._checks",
]


@pytest.mark.parametrize("first", _FIRST)
def test_the_facade_exposes_one_factory_in_any_import_order(first: str) -> None:
    code = (
        f"import {first}\n"
        "from decoy_engine import plan\n"
        "from decoy_engine.plan import _errors\n"
        "assert plan.refusal_error is _errors.refusal_error\n"
        "assert plan.PlanCompileError is _errors.PlanCompileError\n"
    )
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr[-400:]
