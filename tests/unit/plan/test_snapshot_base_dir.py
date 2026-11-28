"""GEN-CLI E1: a relative path in a pipeline YAML resolves from the config's folder.

AT-1 (engine half), AT-2, AT-3, AT-4, AT-6, AT-7 (engine half), AT-24, AT-27, AT-31, AT-32.
The checked-in golden holds the config hash captured on engine 86a28222 (`_gen_cli_golden`).
"""

from __future__ import annotations

import copy
import dataclasses
import json
import os
import shutil
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from decoy_engine import fileaccess
from decoy_engine.config import PipelineConfig
from decoy_engine.contracts.column_shape import NO_SOURCES
from decoy_engine.execution import run_pipeline_isolated
from decoy_engine.execution._pipeline_context import with_quarantine_path
from decoy_engine.execution.capacity import _resolved_config_copy
from decoy_engine.execution.physical import capture_physical_plan_inputs
from decoy_engine.fileaccess import FileRole, Root, RootedFileAccess
from decoy_engine.fileaccess._openat2 import openat2_usable
from decoy_engine.generation.pinned import (
    compile_pinned_plan,
    compile_pinned_plan_with_generation,
    fingerprint,
)
from decoy_engine.generation.statistical import _spec
from decoy_engine.plan import PlanCompileError, compile_plan, run_config_only_checks
from decoy_engine.plan._compile import _hash_config
from decoy_engine.plan.validate import validate_plan
from tests.unit._dps_helpers import empty_profile
from tests.unit._gen_cli_golden import FIXTURES, graph_config, stat_config

REF = datetime(2026, 10, 22, 9, 30, 0, tzinfo=timezone.utc)
GOLDEN = json.loads((FIXTURES / "golden.json").read_text(encoding="utf-8"))
UNREADABLE = "statistical_snapshot_unreadable"


@pytest.fixture
def folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Config folder A holding `snap.json`, and a working directory B that does not."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    shutil.copy(FIXTURES / "snap.json", a / "snap.json")
    monkeypatch.chdir(b)
    return a, b


def _compile(config: dict[str, Any], **kwargs: Any) -> Any:
    return compile_plan(
        config, empty_profile(), decoy_engine_version="test", sources=NO_SOURCES, **kwargs
    )


def _error(config: dict[str, Any], **kwargs: Any) -> tuple[str, str]:
    with pytest.raises(Exception) as exc:
        _compile(config, **kwargs)
    return exc.value.code, str(exc.value)


# AT-3


def test_config_relative_joins_lexically_and_keeps_absolute_and_none(tmp_path: Path) -> None:
    assert fileaccess.config_relative("snap.json", tmp_path) == str(tmp_path / "snap.json")
    assert fileaccess.config_relative("snap.json", str(tmp_path)) == str(tmp_path / "snap.json")
    assert fileaccess.config_relative("../x/snap.json", tmp_path / "a") == str(
        tmp_path / "x" / "snap.json"
    )
    absolute = str(tmp_path / "elsewhere" / "snap.json")
    assert fileaccess.config_relative(absolute, tmp_path / "a") == absolute
    relative = "sub/snap.json"
    assert fileaccess.config_relative(relative, None) is relative


def test_a_relative_base_dir_means_the_working_directory(
    folders: tuple[Path, Path],
) -> None:
    _, b = folders
    assert fileaccess.config_relative("snap.json", ".") == str(b / "snap.json")


# AT-1 (engine half), AT-2


def test_without_base_dir_a_relative_snapshot_reads_from_the_working_directory(
    folders: tuple[Path, Path],
) -> None:
    code, _ = _error(stat_config())
    assert code == UNREADABLE


def test_base_dir_reads_the_snapshot_from_the_config_folder_on_every_compile_route(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, _ = folders
    config = stat_config()
    reads: list[str] = []
    real = fileaccess.read_all

    def spy(role: Any, locator: str, *args: Any, **kwargs: Any) -> bytes:
        if role == FileRole.SNAPSHOT:
            reads.append(locator)
        return real(role, locator, *args, **kwargs)

    monkeypatch.setattr(fileaccess, "read_all", spy)
    expected = str(a / "snap.json")
    for run in (
        lambda: _compile(config, base_dir=a),
        lambda: _compile(config, base_dir=str(a)),
        lambda: run_config_only_checks(config, base_dir=a),
        lambda: (
            validate_plan(config, empty_profile(), decoy_engine_version="test", base_dir=a).ok
            or pytest.fail("validate_plan refused")
        ),
    ):
        reads.clear()
        run()
        assert reads == [expected]


def test_the_config_hash_and_plan_bytes_do_not_see_the_folder(
    folders: tuple[Path, Path],
) -> None:
    a, b = folders
    config = stat_config()
    before = copy.deepcopy(config)
    from_other_folder = _compile(config, base_dir=a)
    os.chdir(a)
    from_own_folder = _compile(config)
    assert config == before
    assert from_other_folder.pipeline_config_hash == from_own_folder.pipeline_config_hash
    assert _hash_config(config) == GOLDEN["statistical"]["config_hash"]
    assert from_other_folder.generation == from_own_folder.generation
    assert [s.sha256 for s in from_other_folder.generation.snapshots] == [
        s.sha256 for s in from_own_folder.generation.snapshots
    ]
    os.chdir(b)


# AT-4


def test_no_base_dir_hands_the_declared_locator_to_the_policy_unchanged(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    real = fileaccess.read_all

    def spy(role: Any, locator: str, *args: Any, **kwargs: Any) -> bytes:
        seen.append(locator)
        return real(role, locator, *args, **kwargs)

    monkeypatch.setattr(fileaccess, "read_all", spy)
    _error(stat_config())
    assert seen == ["snap.json"]


def test_snapshot_grant_uses_the_declared_column_name() -> None:
    config = stat_config()
    column = config["tables"][0]["generate_columns"][0]
    column.update(name="sales@region", source_column="amount")
    grant = (FileRole.SNAPSHOT, "tables.synthetic.generate_columns.sales@region.snapshot_file")
    with (FIXTURES / "snap.json").open("rb") as snapshot:
        policy = fileaccess.PreopenedFileAccess(files={grant: snapshot.fileno()})
        plan = _compile(config, file_access=policy)
    assert [pin.source_path for pin in plan.generation.snapshots] == ["snap.json"]
    assert [spec.column_name for spec in plan.generation.statistical_specs] == ["sales@region"]


def test_denied_snapshot_grant_reports_the_display_position() -> None:
    config = stat_config()
    column = config["tables"][0]["generate_columns"][0]
    column.update(name="https://user:PRIVATEPW@host/x", source_column="amount")
    with pytest.raises(fileaccess.FileAccessDenied) as info:
        _compile(config, file_access=fileaccess.PreopenedFileAccess())
    assert info.value.field_key == "tables.synthetic.generate_columns.<name>.snapshot_file"
    assert "PRIVATEPW" not in str(info.value)
    assert info.value.__context__ is None


@pytest.mark.parametrize(
    ("section", "field", "value", "code", "hint"),
    [
        (
            "dp",
            "schema",
            None,
            "dp_snapshot_not_dp_fit",
            "Fit the snapshot with fit_dp_snapshot, or drop global_settings.dp",
        ),
        (
            "dp",
            "provenance",
            {},
            "dp_snapshot_provenance_uncertified",
            "The recorded proof stack is not certified",
        ),
        (
            "dp",
            "codec",
            {},
            "dp_snapshot_codec_unsupported",
            "The snapshot must use the supported DP codec and version",
        ),
        (
            "dp",
            "scope",
            None,
            "dp_snapshot_release_shape_unsupported",
            "The snapshot must use the supported DP scope, adjacency and boundary",
        ),
        (
            "dp",
            "categorical_columns",
            None,
            "dp_snapshot_not_dp_fit",
            "The DP block must declare categorical_columns and numeric_domains",
        ),
        (
            "dp",
            "column_schema",
            {},
            "dp_snapshot_query_count_mismatch",
            "The column_schema carriers do not match the declared query schedule",
        ),
        (
            "dp",
            "query_count",
            8,
            "dp_snapshot_query_count_mismatch",
            "The query_count does not match the declared columns",
        ),
        (
            "dp",
            "numeric_domains",
            {"other": [0, 120]},
            "dp_snapshot_column_schema_mismatch",
            "The column_schema does not match categorical_columns and numeric_domains",
        ),
        (
            "column",
            "carrier",
            "text",
            "dp_snapshot_carrier_invalid",
            "The column kind and carrier must be numeric/number or categorical/text or flag",
        ),
        (
            "eligibility",
            "column",
            None,
            "dp_snapshot_kind_not_dp_eligible",
            "The snapshot must declare the source column as DP-eligible",
        ),
        (
            "extra",
            "column",
            None,
            "dp_snapshot_column_block_schema_mismatch",
            "The column kind and carrier must match the DP column_schema entry",
        ),
        (
            "column",
            "stats",
            {},
            "dp_snapshot_numeric_shape_mismatch",
            "The numeric domain or histogram shape does not match a DP release",
        ),
        (
            "dp",
            "numeric_bins",
            0,
            "dp_snapshot_numeric_shape_mismatch",
            "The numeric domain or histogram shape does not match a DP release",
        ),
        (
            "stats",
            "bin_edges",
            [2, 3],
            "dp_snapshot_numeric_edges_mismatch",
            "The histogram bin_edges must match the declared domain and numeric_bins",
        ),
        (
            "flag",
            "top_values",
            [{"value": "invalid"}],
            "dp_flag_token_invalid",
            "Flag top_values must contain only the canonical true and false tokens",
        ),
        (
            "dp",
            "release_id",
            None,
            "dp_snapshot_missing_release_id",
            "The DP block must declare a release_id",
        ),
        (
            "dp",
            "delta_total",
            -1,
            "dp_snapshot_budget_malformed",
            "The composed epsilon_total and delta_total must be finite and nonnegative",
        ),
        (
            "conflict",
            "_marker",
            1,
            "dp_release_id_conflict",
            "Each distinct artifact must have a distinct release_id",
        ),
    ],
)
def test_dp_snapshot_refusal_reports_only_the_display_position(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    field: str,
    value: Any,
    code: str,
    hint: str,
) -> None:
    from tests.unit.generation.test_generate_dp_contract import (
        _flag_dp_artifact,
        _numeric_dp_artifact,
    )

    name = "https://user:PRIVATEPW@host/x"
    config = stat_config()
    config["targets"] = {"synthetic": {"type": "file", "format": "csv", "path": "out.csv"}}
    config["global_settings"]["dp"] = {"epsilon": 1, "delta": 1e-6}
    columns = config["tables"][0]["generate_columns"]
    source = "flag" if section == "flag" else "age"
    columns[0].update(name=name, source_column=source)
    artifact = _flag_dp_artifact() if section == "flag" else _numeric_dp_artifact(epsilon_total=0.5)
    inputs = [(name, artifact)]
    if field == "schema":
        artifact = json.loads((FIXTURES / "snap.json").read_text(encoding="utf-8"))
        columns[0]["source_column"] = "amount"
        inputs = [(name, artifact)]
    elif section == "conflict":
        columns.insert(0, {**columns[0], "name": "first", "snapshot_file": "first.json"})
        inputs.insert(0, ("first", copy.deepcopy(artifact)))
        artifact["dp"][field] = value
    elif section in ("extra", "eligibility"):
        if section == "eligibility":
            # Isolate the eligibility check: the earlier schema check also rejects this artifact.
            monkeypatch.setattr(
                "decoy_engine.plan._checks_dp.column_block_matches_schema", lambda *args: True
            )
        artifact["columns"]["extra"] = artifact["columns"][source]
        columns[0]["source_column"] = "extra"
    else:
        sections = {
            "dp": artifact["dp"],
            "column": artifact["columns"][source],
            "stats": artifact["columns"][source]["stats"],
            "flag": artifact["columns"][source]["stats"],
        }
        sections[section][field] = value
    config = PipelineConfig.model_validate(config).model_dump()
    with ExitStack() as stack:
        grants = {}
        for index, (column, snapshot) in enumerate(inputs):
            path = tmp_path / f"{index}.json"
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            stream = stack.enter_context(path.open("rb"))
            grants[
                FileRole.SNAPSHOT, f"tables.synthetic.generate_columns.{column}.snapshot_file"
            ] = stream.fileno()
        policy = fileaccess.PreopenedFileAccess(files=grants)
        with pytest.raises(PlanCompileError) as info:
            _compile(config, file_access=policy)
        result = validate_plan(
            config, empty_profile(), decoy_engine_version="test", file_access=policy
        )
    position = "tables.synthetic.generate_columns.<name>.snapshot_file"
    message = f"not allowed. {hint}"
    assert str(info.value) == f"[{code}] {position}: {message}"
    assert info.value.__context__ is None
    assert result.error is not None
    assert (result.error.code, result.error.path, result.error.message) == (code, position, message)


@pytest.mark.parametrize(
    ("settings", "field", "code", "message"),
    [
        (
            {"type": "reference", "distribution": "fitted"},
            "distribution",
            "dp_generate_fitted_fanout_unsupported",
            "not allowed. Use distribution: random for a DP pipeline",
        ),
        (
            {"condition_on": "age"},
            "condition_on",
            "dp_joint_unsupported",
            "not allowed. Remove condition_on or drop global_settings.dp",
        ),
        (
            {"high_cardinality": True},
            "high_cardinality",
            "dp_generate_high_cardinality_unsupported",
            "not allowed. Remove high_cardinality or drop global_settings.dp",
        ),
        (
            {"allow_real_categories": True},
            "allow_real_categories",
            "dp_generate_allow_real_categories_unsupported",
            "not allowed. Remove allow_real_categories or drop global_settings.dp",
        ),
    ],
)
def test_dp_generate_contract_reports_the_display_position(
    settings: dict[str, Any], field: str, code: str, message: str
) -> None:
    from decoy_engine.plan._checks_dp import check_dp_generate_contract

    config = stat_config()
    config["global_settings"]["dp"] = {"epsilon": 1}
    config["tables"][0]["generate_columns"][0].update(
        settings, name="https://user:PRIVATEPW@host/x"
    )
    with pytest.raises(PlanCompileError) as info:
        check_dp_generate_contract(config)
    position = f"tables.synthetic.generate_columns.<name>.{field}"
    assert str(info.value) == f"[{code}] {position}: {message}"
    assert (info.value.path, info.value.message) == (position, message)


@pytest.mark.parametrize(
    ("column", "field", "code", "message"),
    [
        (
            {"type": "sequence", "high_cardinality": True},
            "high_cardinality",
            "statistical_high_cardinality_wrong_type",
            "not allowed. Only statistical columns may set high_cardinality",
        ),
        (
            {"type": "statistical"},
            "snapshot_file",
            "statistical_snapshot_file_required",
            "missing. A statistical column requires snapshot_file",
        ),
    ],
)
def test_statistical_config_refusal_reports_the_display_position(
    column: dict[str, Any], field: str, code: str, message: str
) -> None:
    config = stat_config()
    config["tables"][0]["generate_columns"] = [{**column, "name": "https://user:PRIVATEPW@host/x"}]
    with pytest.raises(PlanCompileError) as info:
        run_config_only_checks(config)
    position = f"tables.synthetic.generate_columns.<name>.{field}"
    assert str(info.value) == f"[{code}] {position}: {message}"
    assert (info.value.path, info.value.message) == (position, message)


def test_a_rooted_policy_still_reads_a_root_relative_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not openat2_usable():
        pytest.skip("rooted file access needs Linux openat2")
    root = tmp_path / "root"
    root.mkdir()
    shutil.copy(FIXTURES / "snap.json", root / "snap.json")
    monkeypatch.chdir(tmp_path)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        roots = [Root("main", fd, frozenset({FileRole.SNAPSHOT}), frozenset({"read", "stat"}))]
        plan = _compile(stat_config(), file_access=RootedFileAccess(roots))
    finally:
        os.close(fd)
    assert plan.generation is not None


# AT-6


def test_an_unreadable_relative_snapshot_names_the_path_tried_and_the_rule(
    folders: tuple[Path, Path],
) -> None:
    a, _ = folders
    (a / "snap.json").unlink()
    code, message = _error(stat_config(), base_dir=a)
    assert code == UNREADABLE
    # The declared value and the resolved path are config-derived, so neither is in the text.
    assert "snap.json" not in message
    assert str(a / "snap.json") not in message
    assert "config file's folder" in message


def test_an_absolute_snapshot_keeps_the_plain_message(folders: tuple[Path, Path]) -> None:
    a, _ = folders
    config = stat_config()
    absolute = str(a / "missing.json")
    config["tables"][0]["generate_columns"][0]["snapshot_file"] = absolute
    _, message = _error(config, base_dir=a)
    assert "config file's folder" not in message


# AT-7 (engine half)


@dataclasses.dataclass
class _Ctx:
    config: dict[str, Any]


def test_quarantine_output_path_resolves_from_base_dir_and_an_argument_wins(
    tmp_path: Path,
) -> None:
    ctx = _Ctx({"quarantine": {"enabled": True, "output_path": "q/rows.jsonl"}})
    resolved = with_quarantine_path(ctx, None, tmp_path)  # type: ignore[arg-type]
    assert resolved.config["quarantine"]["output_path"] == str(tmp_path / "q" / "rows.jsonl")
    assert ctx.config["quarantine"]["output_path"] == "q/rows.jsonl"
    given = with_quarantine_path(ctx, "mine.jsonl", tmp_path)  # type: ignore[arg-type]
    assert given.config["quarantine"]["output_path"] == "mine.jsonl"
    assert with_quarantine_path(ctx, None, None) is ctx  # type: ignore[arg-type]
    absolute = _Ctx({"quarantine": {"output_path": str(tmp_path / "abs.jsonl")}})
    assert with_quarantine_path(absolute, None, tmp_path) is absolute  # type: ignore[arg-type]
    assert with_quarantine_path(_Ctx({}), None, tmp_path).config == {}  # type: ignore[arg-type]


def test_the_capacity_copy_resolves_every_file_source_path_field(tmp_path: Path) -> None:
    config = {
        "sources": {
            "s": {
                "type": "file",
                "format": "csv",
                "path": "in/data.csv",
                "column_names_file": "in/names.csv",
            }
        }
    }
    copy_ = _resolved_config_copy(config, tmp_path)
    assert copy_["sources"]["s"]["path"] == str(tmp_path / "in" / "data.csv")
    assert copy_["sources"]["s"]["column_names_file"] == str(tmp_path / "in" / "names.csv")
    assert config["sources"]["s"]["path"] == "in/data.csv"


# AT-31


def test_both_pinned_compiles_take_base_dir_and_the_fingerprint_ignores_it(
    folders: tuple[Path, Path],
) -> None:
    a, _ = folders
    config = stat_config()
    config["global_settings"]["reference_date"] = "2026-10-22T09:30:00Z"
    wrapper = compile_pinned_plan(config, REF, base_dir=a)
    with_generation = compile_pinned_plan_with_generation(config, REF, base_dir=a)
    assert fingerprint(wrapper) == fingerprint(with_generation.pinned)
    os.chdir(a)
    assert fingerprint(compile_pinned_plan(config, REF)) == fingerprint(wrapper)
    os.chdir(folders[1])
    with pytest.raises(Exception) as exc:
        compile_pinned_plan(config, REF)
    assert exc.value.code == UNREADABLE


# AT-27


def test_physical_capture_reads_the_snapshot_from_base_dir(folders: tuple[Path, Path]) -> None:
    a, _ = folders
    config = stat_config()
    inputs = capture_physical_plan_inputs(config, None, engine_version="test", base_dir=a)
    assert inputs is not None
    with pytest.raises(Exception) as exc:
        capture_physical_plan_inputs(config, None, engine_version="test")
    assert exc.value.code == UNREADABLE


# AT-24


@pytest.mark.serial
def test_an_isolated_run_carries_base_dir_to_the_child(folders: tuple[Path, Path]) -> None:
    a, _ = folders
    config = stat_config()
    result = run_pipeline_isolated(config, None, engine_version="test", base_dir=str(a))
    assert result.outcome == "completed", result.error
    assert result.outputs is not None
    assert result.outputs["synthetic"].num_rows == 300
    os.chdir(a)
    in_process = run_pipeline_isolated(config, None, isolate=False, engine_version="test")
    os.chdir(folders[1])
    assert in_process.outputs is not None
    assert result.outputs["synthetic"].equals(in_process.outputs["synthetic"])
    with pytest.raises(ValueError, match="JSON"):
        run_pipeline_isolated(config, None, engine_version="test", base_dir=a)


# AT-32


def _bad_snapshot(folder: Path, kind: str) -> None:
    doc = json.loads((FIXTURES / "snap.json").read_text(encoding="utf-8"))
    if kind == "schema":
        doc["schema_version"] = "distribution-snapshot/v0"
    if kind == "missing":
        (folder / "snap.json").unlink()
        return
    (folder / "snap.json").write_text(json.dumps(doc), encoding="utf-8")


def _fitted_config() -> dict[str, Any]:
    config = graph_config()
    child = config["tables"][2]
    child["generate_columns"][1].update(distribution="fitted", snapshot_file="snap.json")
    return config


def test_a_fitted_reference_with_credentials_in_the_locator_keeps_them_out() -> None:
    """The fitted-reference route shares the unreadable-snapshot text: no locator in it."""
    canary = "DECOY_CANARY_F31_PW"
    config = _fitted_config()
    config["tables"][2]["generate_columns"][1]["snapshot_file"] = (
        f"https://user:{canary}@host/snap.json"
    )
    for run in (_compile, run_config_only_checks):
        with pytest.raises(PlanCompileError) as info:
            run(config)
        assert info.value.code == UNREADABLE
        assert canary not in str(info.value)
        assert all(canary not in repr(a) for a in info.value.args)
        assert "snapshot_file could not be read." in str(info.value)


_PW = "DECOY_CANARY_F31_PW"


def _assert_no_password(exc: BaseException) -> None:
    assert _PW not in str(exc)
    assert all(_PW not in repr(a) for a in exc.args)
    assert _PW not in getattr(exc, "path", "")


@pytest.mark.parametrize("kind", ["oversize", "schema", "not-object", "bad-json"])
def test_snapshot_read_messages_keep_a_locator_with_credentials_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Oversize, schema, not-an-object and bad-JSON refusals name the config position only."""
    from decoy_engine.generation.statistical._spec import StatisticalSpecError, _load_snapshot
    from decoy_engine.plan import _generation

    body = {
        "oversize": b'{"schema_version": "x", "pad": "' + b"a" * 64 + b'"}',
        "schema": b'{"schema_version": "zzz"}',
        "not-object": b"[1, 2]",
        "bad-json": b"{not json",
    }[kind]
    target = tmp_path / f"user:{_PW}@host.json"
    target.write_bytes(body)
    config = stat_config()
    config["tables"][0]["generate_columns"][0]["snapshot_file"] = str(target)
    if kind == "oversize":
        monkeypatch.setattr(_generation, "EMBEDDED_SNAPSHOT_MAX_BYTES", 8)
        with pytest.raises(PlanCompileError) as info:
            _generation.read_and_pin_snapshots(config)
        _assert_no_password(info.value)
        return
    _, failures = _generation.read_and_pin_snapshots(config)
    (failure,) = failures.values()
    _assert_no_password(failure)
    with pytest.raises(StatisticalSpecError) as second:
        _load_snapshot(str(target))
    _assert_no_password(second.value)


def test_the_fingerprint_digest_error_drops_the_locator() -> None:
    from decoy_engine.generators.derivation import _snapshot_content_digest

    canary = "DECOY_CANARY_F31_PW"
    with pytest.raises(RuntimeError) as info:
        _snapshot_content_digest(f"https://user:{canary}@host/snap.json")
    assert canary not in str(info.value)
    assert all(canary not in repr(a) for a in info.value.args)
    assert "snapshot_file is missing or unreadable" in str(info.value)


@pytest.mark.parametrize("kind", ["missing", "schema", "unknown-column", "fitted-no-fanout"])
def test_the_folded_pass_keeps_both_validations_on_both_compile_routes(
    folders: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    a, _ = folders
    config = stat_config()
    if kind == "unknown-column":
        config["tables"][0]["generate_columns"][0]["source_column"] = "nope"
    elif kind == "fitted-no-fanout":
        config = _fitted_config()
    else:
        _bad_snapshot(a, kind)
    calls: list[str] = []
    monkeypatch.setattr(
        _spec, "_load_snapshot", lambda *args, **kw: calls.append("load") or pytest.fail("reopened")
    )
    via_compile = _error(config, base_dir=a)
    with pytest.raises(PlanCompileError) as exc:
        run_config_only_checks(config, base_dir=a)
    via_config_only = (exc.value.code, str(exc.value))
    assert via_compile[0] == via_config_only[0]
    assert via_compile[0] != "", kind
    assert calls == []


def test_a_passing_config_yields_pins_specs_and_the_dp_receipt(
    folders: tuple[Path, Path],
) -> None:
    a, _ = folders
    plan = _compile(stat_config(), base_dir=a)
    assert plan.generation is not None
    assert len(plan.generation.snapshots) == 1
    assert [s.column_name for s in plan.generation.statistical_specs] == ["amount"]
    assert plan.generation.dp_verification is None


# AT-5 (engine path-choke guard)


def test_every_engine_path_rewrite_goes_through_the_one_helper() -> None:
    import inspect

    from decoy_engine.execution import _pipeline_context as context
    from decoy_engine.execution import capacity
    from decoy_engine.plan import _generation

    assert "config_relative" in inspect.getsource(_generation.read_and_pin_snapshots)
    assert "config_relative" in inspect.getsource(context.with_quarantine_path)
    assert "config_relative" in inspect.getsource(capacity._resolved_config_copy)
    assert not hasattr(capacity, "_resolve_source_path")


# DUP-DEFECTS E1 (A5): a snapshot with a byte that is not UTF-8 is the same refusal as a truncated one


def _bad_snapshot_config(tmp_path: Path, content: bytes) -> dict[str, Any]:
    (tmp_path / "snap.json").write_bytes(content)
    config = stat_config()
    config["tables"][0]["generate_columns"][0]["snapshot_file"] = str(tmp_path / "snap.json")
    return config


def test_at_e1_2_compile_wraps_a_non_utf8_snapshot_like_a_truncated_one(tmp_path: Path) -> None:
    config = _bad_snapshot_config(tmp_path, b'{"a": "\xff"}')
    with pytest.raises(PlanCompileError) as caught:
        _compile(config)
    code, text = caught.value.code, str(caught.value)
    assert code == UNREADABLE
    assert "snap.json" not in text
    assert not [leak for leak in ("\xff", "0xff", "\u00ff", "position", "codec") if leak in text]


def test_at_e1_5_compile_truncated_snapshot_unchanged(tmp_path: Path) -> None:
    code, text = _error(_bad_snapshot_config(tmp_path, b'{"a": '))
    assert code == UNREADABLE
    assert "snapshot_file could not be read." in text
    assert "snap.json" not in text


def test_at_e1_6_load_snapshot_second_site_raises_the_same_code(tmp_path: Path) -> None:
    config = _bad_snapshot_config(tmp_path, b'{"a": "\xff"}')
    with pytest.raises(_spec.StatisticalSpecError) as caught:
        _spec._load_snapshot(config["tables"][0]["generate_columns"][0]["snapshot_file"])
    assert caught.value.code == UNREADABLE
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_at_e1_9_plan_entry_decode_of_a_pinned_payload_is_closed(tmp_path: Path) -> None:
    import base64

    from decoy_engine.generation._plan_entry import generate_tables

    plan = _compile(_bad_snapshot_config(tmp_path, (FIXTURES / "snap.json").read_bytes()))
    bad = base64.b64encode(b'{"a": "\xff"}').decode("ascii")
    snaps = [dataclasses.replace(s, payload_b64=bad) for s in plan.generation.snapshots]
    plan = dataclasses.replace(
        plan, generation=dataclasses.replace(plan.generation, snapshots=snaps)
    )
    with pytest.raises(_spec.StatisticalSpecError) as caught:
        generate_tables(plan)
    assert caught.value.code == UNREADABLE
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "\xff" not in str(caught.value)
