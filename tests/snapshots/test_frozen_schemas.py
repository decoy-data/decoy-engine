"""REL-GATE RG-F1 (plan 5.2): the committed JSON schemas match what the models generate today.

A failure here is a change to a frozen surface (the pipeline YAML or `decoy-run-result/v1`). If it
is meant, rerun `python scripts/release/frozen_schemas.py --write` and fill in the
compatibility-contract section-9 checklist; never refresh the file to turn a run green.
"""

from __future__ import annotations

from scripts.release import frozen_schemas


def _problems(name: str) -> list[str]:
    return [
        line
        for line in frozen_schemas.check(frozen_schemas.SNAPSHOT_DIR)
        if line.startswith(f"{name}:")
    ]


def test_pipeline_config_schema_matches_snapshot() -> None:
    assert _problems("pipeline-config.schema.json") == []


def test_run_result_schema_matches_snapshot() -> None:
    assert _problems("run-result.schema.json") == []
