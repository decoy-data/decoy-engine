"""SCAN-MULTI S3-engine.2: `starter_config` turns a `ScanSet` into one valid starter pipeline.

T3-valid .. T3-cloud-note, T3-key-hash, T3-placeholder (builder half) from the S3-engine plan.
Every real-file case runs the validated config through `profile_source` and `compile_plan`, so a
provider or namespace the compiler refuses fails here and not in the CLI.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

from decoy_engine import reasons, write_fixed_width
from decoy_engine.config import PipelineConfig, PipelineConfigError
from decoy_engine.plan import PlanCompileError, compile_plan
from decoy_engine.plan.checks import REQUIREMENTS_BY_STRATEGY, check_required_strategy_settings
from decoy_engine.profile import profile_source
from decoy_engine.profiling import scan_sources
from decoy_engine.profiling._starter_config import (
    ColumnSuggestion,
    StarterConfig,
    _entry,
    _needs_namespace,
    starter_config,
)

CANARY = "CANARY-5d2b83"
PLACEHOLDER_CODE = str(reasons.config.NAMESPACE_PLACEHOLDER_UNSET)
LAYOUT = {
    "columns": [
        {"name": "acct", "start": 0, "width": 6},
        {"name": "amt", "start": 6, "width": 4, "type": "int", "align": "right"},
    ]
}


def _compile(config: dict[str, Any]) -> Any:
    dumped = PipelineConfig.model_validate(config).model_dump()
    profile = profile_source(dumped, seed=1)
    return compile_plan(dumped, profile, decoy_engine_version="test")


def _write_sources(root: Path) -> dict[str, dict[str, Any]]:
    customers = pd.DataFrame(
        {
            "customer_id": range(1, 31),
            "email": [f"user{i}@example.com" for i in range(1, 31)],
            "memo": [f"{CANARY}-{i}" for i in range(1, 31)],
            "zip5": ["01234" if i % 3 == 0 else f"{i + 10000}" for i in range(1, 31)],
        }
    )
    customers.to_csv(root / "customers.csv", index=False)
    orders = pd.DataFrame(
        {
            "order_id": range(1, 41),
            "customer_email": [f"user{(i % 30) + 1}@example.com" for i in range(40)],
            "amount": [i * 3 for i in range(40)],
        }
    )
    orders.to_csv(root / "orders.csv", index=False, header=False)
    pd.DataFrame({"id": range(1, 21), "label": [f"label-{i}-text" for i in range(20)]}).to_parquet(
        root / "events.parquet"
    )
    ledger = pd.DataFrame({"acct": [f"AC{i:04d}" for i in range(20)], "amt": range(20)})
    write_fixed_width(ledger, LAYOUT, root / "ledger.fwf")
    file = {"type": "file"}
    return {
        "customers": {
            **file,
            "format": "csv",
            "path": str(root / "customers.csv"),
            "has_header": True,
        },
        "orders": {
            **file,
            "format": "csv",
            "path": str(root / "orders.csv"),
            "has_header": False,
            "column_names": ["order_id", "customer_email", "amount"],
        },
        "events": {**file, "format": "parquet", "path": str(root / "events.parquet")},
        "ledger": {
            **file,
            "format": "fixed_width",
            "path": str(root / "ledger.fwf"),
            "layout": LAYOUT,
        },
    }


@pytest.fixture
def sources(tmp_path: Path) -> dict[str, dict[str, Any]]:
    return _write_sources(tmp_path)


def _relationship(namespace: str | None) -> dict[str, Any]:
    rel: dict[str, Any] = {
        "parent": {"table": "customers", "columns": ["email"]},
        "children": [{"table": "orders", "columns": ["customer_email"]}],
        "orphan_policy": "warn",
    }
    if namespace is not None:
        rel["namespace"] = namespace
    return rel


def _build(
    sources: dict[str, dict[str, Any]],
    *,
    relationships: list[dict[str, Any]] | None = None,
    **kw: Any,
) -> StarterConfig:
    return starter_config(scan_sources(sources), relationships=relationships or (), **kw)


def _columns(result: StarterConfig, table: str) -> dict[str, dict[str, Any]]:
    entry = next(t for t in result.config["tables"] if t["name"] == table)
    return {c["name"]: c for c in entry["columns"]}


def test_valid_and_compiles_for_four_source_kinds(sources: dict[str, dict[str, Any]]) -> None:
    result = _build(sources)
    _compile(result.config)
    assert list(result.config["sources"]) == ["customers", "orders", "events", "ledger"]


def test_every_column_has_exactly_one_entry(sources: dict[str, dict[str, Any]]) -> None:
    result = _build(sources)
    expected = {
        "customers": ["customer_id", "email", "memo", "zip5"],
        "orders": ["order_id", "customer_email", "amount"],
        "events": ["id", "label"],
        "ledger": ["acct", "amt"],
    }
    for table, names in expected.items():
        entry = next(t for t in result.config["tables"] if t["name"] == table)
        assert [c["name"] for c in entry["columns"]] == names


def test_unflagged_column_is_redacted_with_a_review_note(
    sources: dict[str, dict[str, Any]],
) -> None:
    result = _build(sources)
    label = _columns(result, "events")["label"]
    assert label["strategy"] == "redact"
    assert "did not flag" in result.notes[("events", "label")]


def test_namespaced_strategy_gets_the_column_name(sources: dict[str, dict[str, Any]]) -> None:
    result = _build(sources)
    ident = _columns(result, "customers")["customer_id"]
    assert ident["strategy"] == "hash"
    assert ident["namespace"] == "customer_id"


def test_source_dialect_is_explicit(sources: dict[str, dict[str, Any]]) -> None:
    declared = _build(sources).config["sources"]
    assert declared["customers"]["has_header"] is True
    assert declared["orders"]["has_header"] is False
    assert declared["orders"]["column_names"] == ["order_id", "customer_email", "amount"]
    assert "has_header" not in declared["events"]


def test_headerless_file_names_keep_the_names_file(tmp_path: Path) -> None:
    (tmp_path / "names.csv").write_text("a,b\n")
    (tmp_path / "h.csv").write_text("1,x\n2,y\n")
    source = {
        "type": "file",
        "format": "csv",
        "path": str(tmp_path / "h.csv"),
        "has_header": False,
        "column_names_file": str(tmp_path / "names.csv"),
    }
    declared = _build({"h": source}).config["sources"]["h"]
    assert declared["column_names_file"] == str(tmp_path / "names.csv")
    assert "column_names" not in declared


def test_targets_sit_beside_the_input(sources: dict[str, dict[str, Any]], tmp_path: Path) -> None:
    targets = _build(sources).config["targets"]
    assert targets["customers"] == {
        "type": "file",
        "format": "csv",
        "path": str(tmp_path / "customers.masked.csv"),
    }
    assert targets["ledger"]["layout"] == _build(sources).config["sources"]["ledger"]["layout"]
    assert targets["events"]["path"] == str(tmp_path / "events.masked.parquet")


def test_given_target_replaces_the_default(
    sources: dict[str, dict[str, Any]], tmp_path: Path
) -> None:
    mine = {"type": "file", "format": "csv", "path": str(tmp_path / "out" / "c.csv")}
    result = _build(sources, targets={"customers": mine})
    assert result.config["targets"]["customers"] == mine
    assert result.config["targets"]["orders"]["path"].endswith("orders.masked.csv")


def test_no_inferred_relationships(sources: dict[str, dict[str, Any]]) -> None:
    # `customer_id` / `order_id` style names and a shared email column are present on purpose.
    assert _build(sources).config["relationships"] == []


def test_declared_relationship_is_copied_unchanged(sources: dict[str, dict[str, Any]]) -> None:
    declared = [_relationship("cust")]
    before = copy.deepcopy(declared)
    result = _build(sources, relationships=declared)
    assert result.config["relationships"] == before
    assert declared == before


def test_baseline_path_is_set_only_when_given(sources: dict[str, dict[str, Any]]) -> None:
    given = _build(sources, baseline_path=".decoy/library/x.json").config
    assert given["scan_baseline"] == {"path": ".decoy/library/x.json", "schema": "scan-set/v1"}
    assert "scan_baseline" not in _build(sources).config


def test_seed_goes_to_global_settings(sources: dict[str, dict[str, Any]]) -> None:
    assert _build(sources, seed=7).config["global_settings"] == {"seed": 7}
    assert _build(sources).config["global_settings"] == {"seed": 42}


def test_value_free_config_and_notes(sources: dict[str, dict[str, Any]]) -> None:
    result = _build(sources, relationships=[_relationship("cust")])
    blob = json.dumps(result.config) + json.dumps([[*k, v] for k, v in result.notes.items()])
    assert CANARY not in blob
    assert "user1@example.com" not in blob
    assert "01234" not in blob


def test_leading_zero_note_gives_the_count_not_a_value(
    sources: dict[str, dict[str, Any]],
) -> None:
    note = _build(sources).notes[("customers", "zip5")]
    assert "10 sampled values" in note
    assert "01234" not in note


def test_a_column_without_leading_zeros_has_no_such_note(
    sources: dict[str, dict[str, Any]],
) -> None:
    assert "start with 0" not in _build(sources).notes[("customers", "customer_id")]


def test_cloud_source_gets_the_cloud_note(sources: dict[str, dict[str, Any]]) -> None:
    scan = scan_sources({"customers": sources["customers"]})
    cloud = {"type": "s3", "format": "csv", "bucket": "b", "key": "in/customers.csv"}
    swapped = dataclasses.replace(
        scan, tables=(dataclasses.replace(scan.tables[0], descriptor=cloud),)
    )
    result = starter_config(swapped)
    assert result.config["targets"]["customers"] == {
        "type": "file",
        "format": "csv",
        "path": "masked/customers.csv",
    }
    assert "CLI-CLOUD" in result.notes[("customers", "")]


def test_a_local_source_has_no_cloud_note(sources: dict[str, dict[str, Any]]) -> None:
    assert ("customers", "") not in _build(sources).notes


def test_relationship_template_lists_scanned_tables(sources: dict[str, dict[str, Any]]) -> None:
    result = _build(sources)
    assert result.relationship_template == ("customers", "orders", "events", "ledger")


def test_only_selected_tables_are_written(sources: dict[str, dict[str, Any]]) -> None:
    result = starter_config(scan_sources(sources, tables=["events"]))
    assert [t["name"] for t in result.config["tables"]] == ["events"]
    assert list(result.config["sources"]) == ["events"]
    assert list(result.config["targets"]) == ["events"]


def test_key_columns_hash_under_the_declared_namespace(
    sources: dict[str, dict[str, Any]],
) -> None:
    scan = scan_sources(sources)
    emails = next(t for t in scan.tables if t.name == "customers").profile.fields[1]
    assert any(m.detector_id == "email" for m in emails.detector_matches)
    result = starter_config(scan, relationships=[_relationship("cust")])
    parent = _columns(result, "customers")["email"]
    child = _columns(result, "orders")["customer_email"]
    for column in (parent, child):
        assert column["strategy"] == "hash"
        assert column["namespace"] == "cust"
        assert "provider" not in column
    for key in (("customers", "email"), ("orders", "customer_email")):
        assert "faker" in result.notes[key]
        assert "Key column of a declared relationship" in result.notes[key]
    _compile(result.config)


def test_placeholder_namespace_is_shared_and_refused(sources: dict[str, dict[str, Any]]) -> None:
    result = _build(sources, relationships=[_relationship(None)])
    parent = _columns(result, "customers")["email"]
    child = _columns(result, "orders")["customer_email"]
    assert parent["namespace"] == child["namespace"] == "decoy-set-namespace-1"
    assert "Set the same namespace on the relationship" in result.notes[("customers", "email")]
    with pytest.raises(ValidationError) as info:
        PipelineConfig.model_validate(result.config)
    errors = info.value.errors(include_input=False)
    assert {e["type"] for e in errors} == {PLACEHOLDER_CODE}
    assert {e["loc"] for e in errors} == {
        ("tables", 0, "columns", 1, "namespace"),
        ("tables", 1, "columns", 1, "namespace"),
    }
    fixed = copy.deepcopy(result.config)
    # The compiler resolves a relationship's namespace from the relationship, not its columns.
    fixed["relationships"][0]["namespace"] = "cust"
    for table in fixed["tables"]:
        for column in table["columns"]:
            if column.get("namespace") == "decoy-set-namespace-1":
                column["namespace"] = "cust"
    _compile(fixed)


def test_placeholder_counts_from_one_per_relationship(
    sources: dict[str, dict[str, Any]],
) -> None:
    second = {
        "parent": {"table": "events", "columns": ["id"]},
        "children": [{"table": "ledger", "columns": ["amt"]}],
        "orphan_policy": "warn",
    }
    result = _build(sources, relationships=[_relationship("cust"), second])
    assert _columns(result, "events")["id"]["namespace"] == "decoy-set-namespace-2"
    assert _columns(result, "ledger")["amt"]["namespace"] == "decoy-set-namespace-2"


def test_two_namespaces_on_one_key_column_is_refused(sources: dict[str, dict[str, Any]]) -> None:
    other = {
        "parent": {"table": "customers", "columns": ["email"]},
        "children": [{"table": "events", "columns": ["label"]}],
        "orphan_policy": "warn",
        "namespace": "different",
    }
    with pytest.raises(PipelineConfigError) as info:
        _build(sources, relationships=[_relationship("cust"), other])
    assert [p.code for p in info.value.problems] == ["namespace_ambiguity"]
    assert "cust" not in str(info.value) and "email" not in str(info.value)


def test_same_namespace_on_two_relationships_is_one_namespace(
    sources: dict[str, dict[str, Any]],
) -> None:
    other = {
        "parent": {"table": "customers", "columns": ["email"]},
        "children": [{"table": "events", "columns": ["label"]}],
        "orphan_policy": "warn",
        "namespace": "cust",
    }
    result = _build(sources, relationships=[_relationship("cust"), other])
    assert _columns(result, "customers")["email"]["namespace"] == "cust"


def _two_tables_one_file(sources: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {"customers": sources["customers"], "customers_copy": dict(sources["customers"])}


def test_two_tables_from_one_file_get_two_targets(sources: dict[str, dict[str, Any]]) -> None:
    result = _build(_two_tables_one_file(sources))
    paths = [t["path"] for t in result.config["targets"].values()]
    assert len(set(paths)) == 2
    assert paths[0].endswith("customers.customers.masked.csv")
    assert paths[1].endswith("customers.customers_copy.masked.csv")
    _compile(result.config)


def test_one_table_per_file_keeps_the_plain_default(sources: dict[str, dict[str, Any]]) -> None:
    assert _build(sources).config["targets"]["customers"]["path"].endswith("customers.masked.csv")


def test_two_equal_explicit_targets_are_refused(
    sources: dict[str, dict[str, Any]], tmp_path: Path
) -> None:
    same = {"type": "file", "format": "csv", "path": str(tmp_path / "out.csv")}
    with pytest.raises(ValueError, match="customers.*orders") as err:
        _build(sources, targets={"customers": same, "orders": dict(same)})
    assert str(tmp_path) not in str(err.value)


def test_an_explicit_target_equal_to_another_default_is_refused(
    sources: dict[str, dict[str, Any]], tmp_path: Path
) -> None:
    clash = {"type": "file", "format": "csv", "path": str(tmp_path / "orders.masked.csv")}
    with pytest.raises(ValueError, match="share one target path"):
        _build(sources, targets={"customers": clash})


@pytest.mark.parametrize("empty", [{}, None, "", []])
def test_an_explicit_empty_target_is_refused_not_defaulted(
    sources: dict[str, dict[str, Any]], empty: Any
) -> None:
    with pytest.raises(ValueError, match="customers"):
        _build(sources, targets={"customers": empty})


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda r: r["parent"].update(table="nope"),
            str(reasons.config.FK_UNKNOWN_NODE),
        ),
        (
            lambda r: r["children"][0].update(table="nope"),
            str(reasons.config.FK_UNKNOWN_NODE),
        ),
        (
            lambda r: r["children"][0].update(columns=["customer_email", "amount"]),
            str(reasons.plan.COMPOSITE_COLUMNS_LENGTH_MISMATCH),
        ),
        (
            lambda r: r["parent"].update(columns=["no_such_column"]),
            str(reasons.config.FK_UNKNOWN_COLUMN),
        ),
    ],
)
def test_a_misshapen_relationship_is_refused_before_output(
    sources: dict[str, dict[str, Any]], mutate: Any, code: str
) -> None:
    rel = _relationship("ns")
    mutate(rel)
    with pytest.raises(PipelineConfigError) as err:
        _build(sources, relationships=[rel])
    assert [p.code for p in err.value.problems] == [code]
    assert "user1@example.com" not in str(err.value)


@pytest.mark.parametrize(
    ("strategy", "extra"),
    [
        ("hash", {}),
        ("fpe", {}),
        ("date_shift", {}),
        ("bucket_perturb", {}),
        ("categorical", {}),
        ("tokenize", {}),
        ("redact", {}),
        ("shuffle", {}),
        ("shuffle", {"deterministic": True}),
        ("code_set", {"provider_config": {"mode": "gen"}}),
        ("code_set", {"provider_config": {"mode": "mask"}}),
        ("code_set", {}),
    ],
)
def test_namespace_is_set_exactly_when_the_registry_requires_it(
    strategy: str, extra: dict[str, Any]
) -> None:
    assert strategy in REQUIREMENTS_BY_STRATEGY or strategy == "redact"
    suggestion = ColumnSuggestion("t", "c", strategy, **extra)
    entry = _entry(suggestion)
    try:
        check_required_strategy_settings({"tables": [{"name": "t", "columns": [entry]}]})
    except PlanCompileError:
        required = True
    else:
        required = False
    assert _needs_namespace(suggestion) is required
    if required:
        check_required_strategy_settings(
            {"tables": [{"name": "t", "columns": [{**entry, "namespace": "c"}]}]}
        )


def _inherited_env() -> dict[str, str]:
    keep = ("HOME", "VIRTUAL_ENV", "PYTHONPATH", "SYSTEMROOT", "TMPDIR", "LD_LIBRARY_PATH", "PATH")
    return {k: v for k, v in os.environ.items() if k in keep}


def test_the_same_scan_renders_the_same_bytes_under_any_hash_seed(tmp_path: Path) -> None:
    script = textwrap.dedent(
        """
        import json, sys
        from pathlib import Path
        sys.path.insert(0, sys.argv[2])
        from test_starter_config import _relationship, _write_sources
        from decoy_engine.profiling import scan_sources
        from decoy_engine.profiling._starter_config import starter_config
        scan = scan_sources(_write_sources(Path(sys.argv[1])))
        r = starter_config(scan, relationships=[_relationship(None)])
        notes = [[*k, v] for k, v in r.notes.items()]
        print(json.dumps([r.config, notes, list(r.relationship_template)], sort_keys=True))
        """
    )
    outputs = []
    for hash_seed in ("1", "2"):
        done = subprocess.run(  # noqa: S603 - fixed argv, interpreter and script are ours
            [sys.executable, "-c", script, str(tmp_path), str(Path(__file__).parent)],
            env={**_inherited_env(), "PYTHONHASHSEED": hash_seed},
            capture_output=True,
            text=True,
            check=True,
        )
        outputs.append(done.stdout)
    assert outputs[0] == outputs[1]
    assert outputs[0].strip()
