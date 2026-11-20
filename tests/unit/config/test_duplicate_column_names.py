"""A table lists each column once: a repeat would let the later entry win on every lane."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from decoy_engine import reasons, run_pipeline
from decoy_engine.config import PipelineConfig

COLUMN_DUPLICATE = str(reasons.config.COLUMN_DUPLICATE)
GENERATE_DUPLICATE = str(reasons.config.GENERATE_COLUMN_DUPLICATE)
CANARY = "CANARY-5519"


def _config(tmp_path: Path, columns: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": 2,
        "global_settings": {"seed": 1},
        "sources": {
            "t": {
                "type": "file",
                "format": "csv",
                "has_header": True,
                "path": str(tmp_path / "in.csv"),
            }
        },
        "tables": [{"name": "t", "columns": columns}],
        "targets": {"t": {"type": "file", "format": "csv", "path": str(tmp_path / "out.csv")}},
    }


def _errors(raw: dict[str, Any]) -> list[tuple[str, tuple[Any, ...]]]:
    with pytest.raises(ValidationError) as info:
        PipelineConfig.model_validate(raw)
    return [(e["type"], tuple(e["loc"])) for e in info.value.errors(include_url=False)]


@pytest.mark.parametrize(
    "columns",
    [
        [{"name": "s", "strategy": "redact"}, {"name": "s", "strategy": "passthrough"}],
        [{"name": "s", "strategy": "passthrough"}, {"name": "s", "strategy": "redact"}],
        [{"name": "s", "strategy": "redact"}, {"name": "s", "strategy": "redact"}],
    ],
)
def test_repeated_mask_column_is_refused_at_the_later_entry(
    tmp_path: Path, columns: list[dict[str, Any]]
) -> None:
    assert _errors(_config(tmp_path, columns)) == [
        (COLUMN_DUPLICATE, ("tables", 0, "columns", 1, "name"))
    ]


def test_every_later_repeat_is_reported(tmp_path: Path) -> None:
    cols = [{"name": "s", "strategy": "redact"}] * 3 + [{"name": "u", "strategy": "redact"}]
    errs = _errors(_config(tmp_path, cols))
    assert [loc[-2] for _, loc in errs] == [1, 2]


def test_same_name_in_two_tables_is_allowed(tmp_path: Path) -> None:
    raw = _config(tmp_path, [{"name": "s", "strategy": "redact"}])
    other = copy.deepcopy(raw["tables"][0])
    other["name"] = "u"
    raw["tables"].append(other)
    raw["sources"]["u"] = raw["sources"]["t"]
    raw["targets"]["u"] = {
        "type": "file",
        "format": "csv",
        "path": str(tmp_path / "out_u.csv"),
    }
    PipelineConfig.model_validate(raw)


def test_distinct_names_are_allowed(tmp_path: Path) -> None:
    PipelineConfig.model_validate(
        _config(
            tmp_path,
            [{"name": "s", "strategy": "redact"}, {"name": "t", "strategy": "passthrough"}],
        )
    )


def test_generate_duplicate_keeps_its_own_code() -> None:
    raw = {
        "version": 2,
        "global_settings": {"seed": 1},
        "sources": {},
        "targets": {"g": {"type": "file", "format": "csv", "path": "/o/g.csv"}},
        "tables": [
            {
                "name": "g",
                "row_count": 3,
                "generate_columns": [
                    {"name": "c", "type": "sequence", "start": 1},
                    {"name": "c", "type": "sequence", "start": 1},
                ],
            }
        ],
    }
    assert _errors(raw) == [(GENERATE_DUPLICATE, ("tables", 0, "generate_columns", 1, "name"))]


def test_message_carries_no_data_values(tmp_path: Path) -> None:
    raw = _config(
        tmp_path,
        [
            {"name": "s", "strategy": "redact", "replacement": CANARY},
            {"name": "s", "strategy": "passthrough"},
        ],
    )
    with pytest.raises(ValidationError) as info:
        PipelineConfig.model_validate(raw)
    assert CANARY not in str(info.value)


def test_redact_then_passthrough_never_reaches_a_run(tmp_path: Path) -> None:
    """The config that used to ship `s` unmasked is refused before a source is read."""
    reads: list[str] = []

    def loader(name: str) -> Any:
        reads.append(name)
        raise AssertionError("source read")

    raw = _config(
        tmp_path,
        [{"name": "s", "strategy": "redact"}, {"name": "s", "strategy": "passthrough"}],
    )
    with pytest.raises(ValidationError):
        run_pipeline(
            PipelineConfig.model_validate(raw).model_dump(),
            engine_version="dup-cols",
            source_loader=loader,
        )
    assert reads == []
    assert not (tmp_path / "out.csv").exists()
