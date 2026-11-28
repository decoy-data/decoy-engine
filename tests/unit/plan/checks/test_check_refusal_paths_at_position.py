"""The whole-config plan checks carry a refusal path from the config root.

A host that validates one column at a time wraps the call in `fileaccess.at_position`. These
checks already build the full `tables.<t>.columns.<c>...` path, so the active position must not
be prepended a second time.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from decoy_engine import fileaccess, reasons
from decoy_engine._config_text import Name, config_position
from decoy_engine.config._delivery import refuse_unreleased_delivery
from decoy_engine.errors import PipelineValidationError
from decoy_engine.plan._checks_bucketize import check_bucketize_config
from decoy_engine.plan._checks_fpe import check_fpe_charset_config, check_fpe_checksum_scheme
from decoy_engine.plan._checks_top_code import check_top_code_config
from decoy_engine.plan._checks_truncate import check_truncate_config
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.plan._generation import (
    ReadSnapshot,
    check_fitted_references,
    read_and_pin_snapshots,
    statistical_refusal,
)

_COLUMN = "tables.orders.columns.age"
_LABELS = {"over_label": "o"}

CASES: list[tuple[str, Callable[[dict[str, Any]], None], str, dict[str, Any], str]] = [
    ("cap_type", check_top_code_config, "top_code", {"cap": "5", **_LABELS}, "cap"),
    ("cap_nonfinite", check_top_code_config, "top_code", {"cap": float("inf"), **_LABELS}, "cap"),
    ("cap_range", check_top_code_config, "top_code", {"cap": 2**53, **_LABELS}, "cap"),
    ("preset", check_top_code_config, "top_code", {"preset": "nope"}, "preset"),
    ("over_label", check_top_code_config, "top_code", {"cap": 5}, "over_label"),
    (
        "floor_type",
        check_top_code_config,
        "top_code",
        {"cap": 50, **_LABELS, "floor": "1", "under_label": "u"},
        "floor",
    ),
    (
        "under_label",
        check_top_code_config,
        "top_code",
        {"cap": 50, **_LABELS, "floor": 1},
        "under_label",
    ),
    (
        "floor_ge_cap",
        check_top_code_config,
        "top_code",
        {"cap": 5, **_LABELS, "floor": 9, "under_label": "u"},
        "floor",
    ),
    ("width", check_bucketize_config, "bucketize", {"width": "5"}, "width"),
    ("mask_char", check_truncate_config, "truncate", {"length": 3, "mask_char": "ab"}, "mask_char"),
]


def _config(strategy: str, provider_config: dict[str, Any]) -> dict[str, Any]:
    column = {"name": "age", "strategy": strategy, "provider_config": provider_config}
    return {"tables": [{"name": "orders", "columns": [column]}]}


@pytest.mark.parametrize("active", ["", _COLUMN], ids=["no_position", "at_position"])
@pytest.mark.parametrize(
    ("name", "check", "strategy", "provider_config", "field"), CASES, ids=[c[0] for c in CASES]
)
def test_refusal_path_is_root_relative(
    name: str,
    check: Callable[[dict[str, Any]], None],
    strategy: str,
    provider_config: dict[str, Any],
    field: str,
    active: str,
) -> None:
    with fileaccess.at_position(active), pytest.raises(PlanCompileError) as caught:
        check(_config(strategy, provider_config))
    assert caught.value.path == f"{_COLUMN}.provider_config.{field}", name


_GENERATED = "tables.orders.generate_columns.parent_id"
_SNAPSHOT = "fanout.json"


def _fitted(**extra: Any) -> dict[str, Any]:
    column = {"name": "parent_id", "type": "reference", "distribution": "fitted", **extra}
    return {"tables": [{"name": "orders", "generate_columns": [column]}]}


def _pinned() -> dict[str, ReadSnapshot]:
    return {_SNAPSHOT: ReadSnapshot(path=_SNAPSHOT, sha256="0" * 64, parsed={}, raw=b"{}")}


FITTED_CASES: list[tuple[str, dict[str, Any], str]] = [
    ("snapshot_file_missing", _fitted(), f"{_GENERATED}.snapshot_file"),
    ("fitted_conflict", _fitted(snapshot_file=_SNAPSHOT, weights=[1]), f"{_GENERATED}.weights"),
]


@pytest.mark.parametrize("active", ["", _GENERATED], ids=["no_position", "at_position"])
@pytest.mark.parametrize(
    ("name", "config", "expected"), FITTED_CASES, ids=[c[0] for c in FITTED_CASES]
)
def test_fitted_reference_refusal_path_is_root_relative(
    name: str, config: dict[str, Any], expected: str, active: str
) -> None:
    with fileaccess.at_position(active), pytest.raises(PlanCompileError) as caught:
        check_fitted_references(config, _pinned(), {})
    assert caught.value.path == expected, name


@pytest.mark.parametrize("active", ["", _GENERATED], ids=["no_position", "at_position"])
def test_statistical_refusal_key_is_root_relative(active: str) -> None:
    with fileaccess.at_position(active):
        refusal = statistical_refusal(
            reasons.plan.REFERENCE_FANOUT_MISSING, _SNAPSHOT, "orders", "parent_id"
        )
    assert refusal.key == _GENERATED


@pytest.mark.parametrize(("table", "column"), [("orders", "parent_id"), ("t" * 50, "c" * 50)])
def test_oversized_snapshot_message_is_root_relative_under_a_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table: str, column: str
) -> None:
    (tmp_path / _SNAPSHOT).write_bytes(b"{" + b" " * 64 + b"}")
    monkeypatch.setattr("decoy_engine.plan._generation.EMBEDDED_SNAPSHOT_MAX_BYTES", 8)
    config = _fitted(snapshot_file=_SNAPSHOT)
    config["tables"][0]["name"] = table
    config["tables"][0]["generate_columns"][0]["name"] = column
    expected = f"tables.{table}.generate_columns.{column}.snapshot_file"
    with fileaccess.at_position(_GENERATED), pytest.raises(PlanCompileError) as caught:
        read_and_pin_snapshots(config, base_dir=tmp_path)
    assert caught.value.path == expected
    code = reasons.plan.DP_SNAPSHOT_EMBEDDED_ARTIFACT_TOO_LARGE
    assert str(caught.value).startswith(
        f"[{code}] {expected}: too large. The embedded-artifact cap is 16 MiB"
    )


@pytest.mark.parametrize("active", ["", _COLUMN], ids=["no_position", "at_position"])
def test_delivery_refusal_is_root_relative(active: str) -> None:
    with fileaccess.at_position(active), pytest.raises(PipelineValidationError) as caught:
        refuse_unreleased_delivery({"delivery": {"mode": "best_effort"}})
    assert caught.value.path == "delivery"
    assert str(caught.value).startswith("delivery: not allowed")


@pytest.mark.parametrize("active", ["", _COLUMN], ids=["no_position", "at_position"])
def test_fpe_charset_refusal_is_root_relative(active: str) -> None:
    config = _config("fpe", {"charset": "aab"})
    with fileaccess.at_position(active), pytest.raises(PlanCompileError) as caught:
        check_fpe_charset_config(config)
    assert caught.value.path == f"{_COLUMN}.provider_config.charset"
    assert str(caught.value).startswith(
        f"[{reasons.plan.FPE_CHARSET_DUPLICATE_SYMBOLS}] {_COLUMN}.provider_config.charset: "
        "not allowed. "
    )


FPE_CHECKSUM_CASES = [
    (
        "checksum_unknown",
        {"checksum": "nope"},
        "checksum",
        "fpe_checksum_unknown_scheme",
        "not allowed",
    ),
    (
        "checksum_iban",
        {"checksum": "iban"},
        "checksum",
        "fpe_checksum_iban_unsupported",
        "not allowed",
    ),
    (
        "checksum_charset",
        {"checksum": "vin", "charset": "digits"},
        "charset",
        "fpe_checksum_charset_incompatible",
        "does not match",
    ),
]


@pytest.mark.parametrize("active", ["", _COLUMN], ids=["no_position", "at_position"])
@pytest.mark.parametrize(
    ("name", "provider_config", "field", "code", "problem"),
    FPE_CHECKSUM_CASES,
    ids=[c[0] for c in FPE_CHECKSUM_CASES],
)
def test_fpe_checksum_refusal_is_root_relative(
    name: str,
    provider_config: dict[str, Any],
    field: str,
    code: str,
    problem: str,
    active: str,
) -> None:
    with fileaccess.at_position(active), pytest.raises(PlanCompileError) as caught:
        check_fpe_checksum_scheme(_config("fpe", provider_config))
    assert caught.value.path == f"{_COLUMN}.provider_config.{field}", name
    assert str(caught.value).startswith(f"[{code}] {_COLUMN}.provider_config.{field}: {problem}. ")


def test_a_relative_position_cannot_start_with_a_root_key_or_a_name() -> None:
    for first in ("tables", "delivery", "generation", Name("x")):
        with pytest.raises(TypeError):
            config_position(first)  # type: ignore[arg-type]
    assert config_position("snapshot_file").key == "snapshot_file"
    with fileaccess.at_position(_COLUMN):
        assert config_position("snapshot_file").key == f"{_COLUMN}.snapshot_file"


_URL = "https://user:pw@host/x"


@pytest.mark.parametrize("field", ["length", "keep"])
def test_truncate_refusal_never_echoes_the_submitted_value(field: str) -> None:
    provider_config: dict[str, Any] = {"length": 3}
    provider_config[field] = _URL
    with pytest.raises(PlanCompileError) as caught:
        check_truncate_config(_config("truncate", provider_config))
    assert _URL not in str(caught.value)
    assert caught.value.path == f"{_COLUMN}.provider_config.{field}"
    hint = (
        "length must be an integer >= 1. A masking strategy must never silently pass the source "
        "value through on a bad config; fix or remove this column's length."
        if field == "length"
        else "keep must be 'head' or 'tail' when set."
    )
    code = getattr(reasons.plan, f"TRUNCATE_{field.upper()}_INVALID")
    assert str(caught.value) == (
        f"[{code}] {_COLUMN}.provider_config.{field}: not allowed, got string. {hint}"
    )


def test_config_root_keys_match_the_schema_and_stored_plan_roots() -> None:
    from decoy_engine.config import CONFIG_ROOT_KEYS, PipelineConfig

    assert set(PipelineConfig.model_fields) | {"generation", "declared_casting"} == CONFIG_ROOT_KEYS
    for root in CONFIG_ROOT_KEYS:
        with pytest.raises(TypeError):
            config_position(root)
