"""The layer contract holds with ``_value_family`` in the bottom tier and no new ignore line.

``anonymize`` sits above ``quality`` (it imports ``kernel``), so ``quality.anonymity`` reads
``type_family`` from the bottom-tier ``_value_family`` module, never from ``anonymize``. The
``lint-imports`` run itself is ``scripts/dev/gates.sh --steps layers``; this file checks the
config in the certified venv, where import-linter is not installed.
"""

from __future__ import annotations

import configparser
import json
from pathlib import Path

from tests.sentry.layout.test_import_layers import LAYERS

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / ".importlinter"
BASELINE = ROOT / "tests" / "sentry" / "baselines" / "import-layers.json"
WATCHED = ("decoy_engine._value_family", "decoy_engine.anonymize", "decoy_engine.quality.anonymity")


def _contract() -> tuple[list[str], list[str]]:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.read_string(CONFIG.read_text(encoding="utf-8"))
    section = parser["importlinter:contract:layers"]
    tiers = [line.strip() for line in section["layers"].splitlines() if line.strip()]
    ignores = [line.strip() for line in section["ignore_imports"].splitlines() if line.strip()]
    return tiers, ignores


def _names(tier: str) -> set[str]:
    return {name.strip() for name in tier.split(":")}


def test_value_family_is_in_the_bottom_tier_only() -> None:
    tiers, _ = _contract()
    assert "_value_family" in _names(tiers[-1])
    assert all("_value_family" not in _names(tier) for tier in tiers[:-1])


def test_the_reviewed_snapshot_agrees() -> None:
    assert "_value_family" in _names(LAYERS[-1])


def test_anonymize_sits_above_quality() -> None:
    tiers, _ = _contract()
    tier_of = {name: index for index, tier in enumerate(tiers) for name in _names(tier)}
    assert tier_of["anonymize"] < tier_of["quality"] < tier_of["_value_family"]


def test_no_ignore_line_bridges_quality_and_anonymize() -> None:
    _, ignores = _contract()
    assert [line for line in ignores if any(name in line for name in WATCHED)] == []


def test_every_ignore_line_is_in_the_shrink_only_baseline() -> None:
    _, ignores = _contract()
    known = set(json.loads(BASELINE.read_text(encoding="utf-8"))["entries"])
    assert {f"layers::{line}" for line in ignores} <= known
