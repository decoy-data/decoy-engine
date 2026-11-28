"""AT-5: `fileaccess.shown` is the recognizer's display under the ambient policy and the
encoded config position under a strict one."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from decoy_engine._locator import scan_locator
from decoy_engine.fileaccess import RootedFileAccess, scope, shown
from decoy_engine.fileaccess._errors import encode_field_key

CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "locator_credentials" / "cases.json").read_text(
        encoding="utf-8"
    )
)
KEY = "tables.orders.source.path"


@pytest.mark.parametrize("row", CASES, ids=[r["id"] for r in CASES])
def test_ambient_shows_the_recognizer_display(row: dict[str, Any]) -> None:
    assert shown(row["input"], KEY) == scan_locator(row["input"]).shown == row["shown"]


@pytest.mark.parametrize("row", CASES, ids=[r["id"] for r in CASES])
def test_a_strict_policy_never_shows_a_locator(row: dict[str, Any]) -> None:
    with scope(RootedFileAccess([], allow_portable_fallback=True)):
        assert shown(row["input"], KEY) == encode_field_key(KEY)
