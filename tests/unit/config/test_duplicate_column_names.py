"""A table lists each column once: a repeat would let the later entry win on every lane."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from decoy_engine import reasons
from decoy_engine.config import PipelineConfig, PipelineConfigError, parse_pipeline_config

COLUMN_DUPLICATE = str(reasons.config.COLUMN_DUPLICATE)
GENERATE_DUPLICATE = str(reasons.config.GENERATE_COLUMN_DUPLICATE)
TABLE_DUPLICATE = str(reasons.config.TABLE_DUPLICATE)
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
    """The canary sits in `provider_config`, a field the config accepts, so the duplicate is
    the only problem and the check has the value in hand when it builds its message."""
    raw = _config(
        tmp_path,
        [
            {"name": "s", "strategy": "redact", "provider_config": {"note": CANARY}},
            {"name": "s", "strategy": "passthrough", "when": f"s == '{CANARY}'"},
        ],
    )
    with pytest.raises(PipelineConfigError) as info:
        parse_pipeline_config(raw)
    assert [(p.code, p.location) for p in info.value.problems] == [
        (COLUMN_DUPLICATE, "tables[0].columns[1].name")
    ]
    assert CANARY not in str(info.value)


def test_redact_then_passthrough_is_refused_at_parse(tmp_path: Path) -> None:
    """The config that used to ship `s` unmasked never gets a `PipelineConfig`.

    `run_pipeline` takes an already validated dict, so the refusal point is the parse.
    """
    raw = _config(
        tmp_path,
        [{"name": "s", "strategy": "redact"}, {"name": "s", "strategy": "passthrough"}],
    )
    with pytest.raises(PipelineConfigError):
        parse_pipeline_config(raw)


def _two_tables(tmp_path: Path, first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    raw = _config(tmp_path, [{"name": "s", "strategy": "redact"}])
    raw["tables"] = [first, second]
    return raw


MASK_REDACT = {"name": "t", "columns": [{"name": "s", "strategy": "redact"}]}
MASK_PASS = {"name": "t", "columns": [{"name": "s", "strategy": "passthrough"}]}
GENERATE_T = {
    "name": "t",
    "row_count": 2,
    "generate_columns": [{"name": "c", "type": "sequence", "start": 1}],
}


@pytest.mark.parametrize(
    ("first", "second"),
    [(MASK_REDACT, MASK_PASS), (MASK_PASS, MASK_REDACT), (MASK_REDACT, GENERATE_T)],
    ids=["mask+mask", "mask+mask-reversed", "mask+generate"],
)
def test_repeated_table_name_is_refused_at_the_later_declaration(
    tmp_path: Path, first: dict[str, Any], second: dict[str, Any]
) -> None:
    assert _errors(_two_tables(tmp_path, first, second)) == [
        (TABLE_DUPLICATE, ("tables", 1, "name"))
    ]


def test_every_later_table_repeat_is_reported(tmp_path: Path) -> None:
    raw = _two_tables(tmp_path, MASK_REDACT, MASK_PASS)
    raw["tables"].append(copy.deepcopy(MASK_PASS))
    assert [loc for _, loc in _errors(raw)] == [("tables", 1, "name"), ("tables", 2, "name")]


def test_distinct_table_names_are_allowed(tmp_path: Path) -> None:
    other = {**MASK_PASS, "name": "u"}
    raw = _two_tables(tmp_path, MASK_REDACT, other)
    raw["sources"]["u"] = raw["sources"]["t"]
    raw["targets"]["u"] = {"type": "file", "format": "csv", "path": str(tmp_path / "out_u.csv")}
    PipelineConfig.model_validate(raw)


def test_table_duplicate_message_carries_no_data_values(tmp_path: Path) -> None:
    first = {
        "name": "t",
        "columns": [{"name": "s", "strategy": "redact", "provider_config": {"n": CANARY}}],
    }
    with pytest.raises(PipelineConfigError) as info:
        parse_pipeline_config(_two_tables(tmp_path, first, MASK_PASS))
    assert [(p.code, p.location) for p in info.value.problems] == [
        (TABLE_DUPLICATE, "tables[1].name")
    ]
    assert CANARY not in str(info.value)
