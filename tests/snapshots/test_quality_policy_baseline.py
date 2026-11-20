"""Snapshot harness for quality policy verdicts (V2 Phase 3 D4).

Pins SHA-256 digests for the policy dict across canonical fixtures.
Any change to violation ordering, severity defaults, mode semantics,
or default strategy expectations fails CI with one fixture name.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.quality.policy import apply_quality_policy

GOLDEN = Path(__file__).parent / "golden" / "quality_policy"


def _report(
    *,
    overall: float = 0.9,
    marginal: float = 0.92,
    pairwise: float = 0.85,
    diagnostic_passed: bool = True,
    columns: list[dict] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "quality-report/v1",
        "diagnostic": {"passed": diagnostic_passed, "checks": []},
        "marginal": {
            "score": marginal,
            "columns": columns
            or [{"column": "age", "similarity": 0.92, "method": "tvd", "comparable": True}],
        },
        "pairwise": {"score": pairwise, "joints": []},
        "overall_score": overall,
        "grade": "B",
    }


def _empty_policy_pass() -> dict[str, Any]:
    return apply_quality_policy(_report())


def _overall_fail() -> dict[str, Any]:
    return apply_quality_policy(
        _report(overall=0.5),
        {"mode": "fail", "thresholds": {"overall": {"min": 0.95}}},
    )


def _per_column_strategy_violation() -> dict[str, Any]:
    # Uses shuffle (default expectation 0.85 under corrected D5a
    # defaults) to demonstrate the strategy-fallback violation path.
    # Hash dropped to 0.05 in D5a because TVD treats hashed values
    # as disjoint; an 0.80 actual easily passes hash's 0.05 floor.
    cols = [
        {"column": "name", "similarity": 0.50, "method": "tvd", "comparable": True},
    ]
    return apply_quality_policy(
        _report(columns=cols),
        {"mode": "fail"},
        strategy_map={"name": "shuffle"},
    )


def _all_checks_violate_warn_mode() -> dict[str, Any]:
    cols = [
        {"column": "age", "similarity": 0.50, "method": "tvd", "comparable": True},
    ]
    return apply_quality_policy(
        _report(diagnostic_passed=False, columns=cols),
        {
            "mode": "warn",
            "thresholds": {
                "diagnostic": {"required": True},
                "overall": {"min": 0.95},
                "marginal": {"min": 0.95},
                "pairwise": {"min": 0.95},
                "columns": [{"column": "age", "min": 0.95}],
            },
        },
    )


def _intended_hash_faker() -> dict[str, Any]:
    # Correct hash and faker masking scores 0.0 on value identity; both are intended, no violation.
    cols = [
        {"column": "patient_id", "similarity": 0.0, "method": "tvd", "comparable": True},
        {"column": "full_name", "similarity": 0.0, "method": "tvd", "comparable": True},
    ]
    return apply_quality_policy(
        _report(columns=cols),
        {"mode": "fail"},
        strategy_map={"patient_id": "hash", "full_name": "faker"},
    )


FIXTURES: dict[str, Callable[[], dict[str, Any]]] = {
    "intended_hash_faker": _intended_hash_faker,
    "empty_policy_pass": _empty_policy_pass,
    "overall_fail": _overall_fail,
    "per_column_strategy_violation": _per_column_strategy_violation,
    "all_checks_violate_warn_mode": _all_checks_violate_warn_mode,
}


# Digests pinned before E2 added `intended_columns`, `intended_joints` and `pairwise_skipped`.
# E2 re-pins the four goldens for those keys only: stripping them must give back the old digest.
_PRE_E2_DIGESTS = {
    "all_checks_violate_warn_mode": (
        "df94b66641eac90636711d03b858f61d2d68a6be1d6d639cd874a72c274a6ab6"
    ),
    "empty_policy_pass": "cda90a1b3e4c970d2e55a658db033153615250a5812d0a1392a5cc549ab51639",
    "overall_fail": "28cd6c281436680f4fc85f952c3c0dd659430bb53a3e1f4f7d07a490a2edb476",
    "per_column_strategy_violation": (
        "2688d53278a520d8b9bc7791d4f39e1cc91429ec2f162d771aa15d16a0944a30"
    ),
}
_E2_KEYS = ("intended_columns", "intended_joints", "pairwise_skipped")


@pytest.mark.parametrize("name", sorted(_PRE_E2_DIGESTS))
def test_e2_only_adds_keys_to_existing_fixtures(name: str) -> None:
    stripped = {k: v for k, v in FIXTURES[name]().items() if k not in _E2_KEYS}
    assert _digest(stripped) == _PRE_E2_DIGESTS[name]


def test_all_checks_violate_keeps_the_aggregate_pairwise_value() -> None:
    violations = FIXTURES["all_checks_violate_warn_mode"]()["violations"]
    pairwise = [v for v in violations if v["check"] == "pairwise"]
    assert [v["actual"] for v in pairwise] == [0.85]


def _digest(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _golden_path(name: str) -> Path:
    return GOLDEN / f"{name}.sha256"


@pytest.mark.parametrize("name", sorted(FIXTURES.keys()))
def test_quality_policy_baseline(name: str) -> None:
    verdict = FIXTURES[name]()
    digest = _digest(verdict)

    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        _golden_path(name).write_text(digest + "\n", encoding="utf-8")
        return

    path = _golden_path(name)
    if not path.exists():
        pytest.fail(
            f"Missing golden for fixture {name!r}. "
            f"Run with UPDATE_SNAPSHOTS=1 to create it, then inspect "
            f"{path} before committing."
        )
    expected = path.read_text(encoding="utf-8").strip()
    if expected != digest:
        pytest.fail(
            f"Quality policy drift on fixture {name!r}\n"
            f"  expected digest: {expected}\n"
            f"  actual digest:   {digest}\n"
            f"  actual payload:  {json.dumps(verdict, indent=2, sort_keys=True)[:2000]}"
        )
