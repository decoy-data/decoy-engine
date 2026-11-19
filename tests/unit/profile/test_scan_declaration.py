"""SCAN-MULTI E-S1c: the scan declaration at the declaration boundary (TE-scan-*).

`DeclarationRequest.for_scan` turns a sources-only file or a full pipeline into the inputs of
`scan_sources`, through the one validator `validate_scan_inputs`, before any data row is read.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from decoy_engine import ScanDeclaration, scan_sources
from decoy_engine.config import PipelineConfig, PipelineConfigError
from decoy_engine.profile import DeclarationRequest, prepare_declared_sources
from decoy_engine.profile import _csv_reader as csv_reader
from decoy_engine.profiling import scan_set

CANARY = "zz_canary_value_71"
_SHAPE_KEYS = {"sources", "relationships", "version"}


def _csv(path: Path, **extra: Any) -> dict[str, Any]:
    return {"type": "file", "format": "csv", "path": str(path), "has_header": True, **extra}


def _file(tmp: Path, name: str, text: str) -> Path:
    path = tmp / name
    path.write_text(text, encoding="utf-8")
    return path


def _rel(parent: str, child: str) -> dict[str, Any]:
    return {
        "parent": {"table": parent, "columns": ["id"]},
        "children": [{"table": child, "columns": ["id"]}],
        "orphan_policy": "warn",
    }


def _declare(config: dict[str, Any], tables: list[str] | None = None) -> ScanDeclaration:
    request = DeclarationRequest.for_scan(config, tables)
    return prepare_declared_sources(request).scan_declaration


@pytest.fixture
def two(tmp_path: Path) -> dict[str, Any]:
    a = _file(tmp_path, "a.csv", "id,x\n1,u\n2,v\n")
    b = _file(tmp_path, "b.csv", "id,y\n1,p\n")
    return {"a": _csv(a), "b": _csv(b)}


def test_valid_sources_only_and_full_pipeline(two: dict[str, Any]) -> None:
    expected = scan_set.validate_scan_inputs(two, None, ()).descriptors
    only = _declare({"sources": two})
    full = _declare({"version": 2, "sources": two, "tables": [], "global_settings": {"seed": 1}})
    for decl in (only, full):
        assert {k: dict(v) for k, v in decl.descriptors.items()} == expected
        assert decl.tables == ("a", "b")
        assert decl.relationships == ()
        assert decl.unchecked_relationships == 0
    assert only.ignored_keys == ()
    assert full.ignored_keys == ("tables", "global_settings")


def test_csv_without_has_header_is_refused(tmp_path: Path) -> None:
    src = _csv(_file(tmp_path, "a.csv", "id\n1\n"))
    del src["has_header"]
    with pytest.raises(PipelineConfigError, match="'a'"):
        _declare({"sources": {"a": src}})


def test_shape_unknown_key_and_version(two: dict[str, Any]) -> None:
    with pytest.raises(PipelineConfigError, match="bogus"):
        _declare({"sources": two, "bogus": 1})
    assert _declare({"sources": two, "tables": [], "bogus": 1}).ignored_keys == ("tables",)
    assert _declare({"sources": two, "version": 2}).tables == ("a", "b")
    for version in (1, True, 2.0, "2"):
        with pytest.raises(PipelineConfigError, match="version"):
            _declare({"sources": two, "version": version})


@pytest.mark.parametrize(
    ("patch", "text"),
    [
        ({"sources": {"a": 5}}, "'a'"),
        ({"sources": {}}, "sources"),
        ({"sources": "x"}, "sources"),
        ({"relationships": {"x": 1}}, "relationships"),
        ({"relationships": [5]}, "relationship 1"),
    ],
)
def test_shape_values_are_coded_refusals(
    two: dict[str, Any], patch: dict[str, Any], text: str
) -> None:
    config = {"sources": two, **patch}
    with pytest.raises(PipelineConfigError, match=text) as caught:
        _declare(config)
    assert type(caught.value) is PipelineConfigError


@pytest.mark.parametrize("tables", [5, "x", ["a", 5, {"name": 3}, None]])
def test_unusable_tables_key_is_ignored_not_crashed(two: dict[str, Any], tables: Any) -> None:
    decl = _declare({"sources": two, "tables": tables})
    assert decl.ignored_keys == ("tables",)


@pytest.mark.parametrize("key", sorted(set(PipelineConfig.model_fields) - _SHAPE_KEYS))
def test_shape_is_derived_from_pipeline_config(two: dict[str, Any], key: str) -> None:
    decl = _declare({"sources": two, key: {}, "zz_unknown_key": 1})
    assert decl.ignored_keys == (key,)


def test_mixed_pipeline_sets_aside_generate_relationships(two: dict[str, Any]) -> None:
    kept = _rel("a", "b")
    to_generate = _rel("a", "g1")
    between_generate = _rel("g1", "g2")
    config = {"sources": two, "tables": [], "relationships": [to_generate, kept, between_generate]}
    decl = _declare(config)
    assert decl.unchecked_relationships == 2
    assert [dict(r) for r in decl.relationships] == [kept]
    lone = _declare({**config, "relationships": [to_generate]})
    assert lone.unchecked_relationships == 1
    assert lone.relationships == ()
    # The same relationship in a sources-only file names a table that is not a source.
    with pytest.raises(PipelineConfigError, match="not in sources"):
        _declare({"sources": two, "relationships": [to_generate]})
    # A malformed entry is a coded refusal, never an unchecked hint.
    broken = {"parnet": {"table": "g1", "columns": ["id"]}, "children": []}
    with pytest.raises(PipelineConfigError, match="relationship 1 is invalid"):
        _declare({"sources": two, "tables": [], "relationships": [broken]})


def test_relationship_positions_follow_the_file(two: dict[str, Any]) -> None:
    to_generate = _rel("a", "g1")
    wrong_column = {**_rel("a", "b"), "children": [{"table": "b", "columns": ["zz"]}]}
    decl = _declare({"sources": two, "tables": [], "relationships": [to_generate, wrong_column]})
    assert decl.relationship_positions == (2,)
    with pytest.raises(PipelineConfigError, match="relationship 2 "):
        scan_sources(
            decl.descriptors,
            relationships=decl.relationships,
            relationship_positions=decl.relationship_positions,
        )
    repeated = {**_rel("a", "b"), "parent": {"table": "a", "columns": ["id", "id"]}}
    with pytest.raises(PipelineConfigError, match="relationship 2 "):
        _declare({"sources": two, "tables": [], "relationships": [to_generate, repeated]})


@pytest.mark.parametrize(
    "positions", [[7, 7], [3, 2], [0, 1], [-1, 2], [True, 2], [1.0, 2], ["2", 3]]
)
def test_scan_sources_refuses_unusable_relationship_positions(
    two: dict[str, Any], positions: list[Any]
) -> None:
    rels = [_rel("a", "b"), _rel("b", "a")]
    with pytest.raises(PipelineConfigError, match="relationship_positions") as caught:
        scan_sources(two, relationships=rels, relationship_positions=positions)
    assert '"2"' not in str(caught.value) and "'2'" not in str(caught.value)
    assert caught.value.__context__ is None and caught.value.__cause__ is None


def test_scan_sources_accepts_increasing_relationship_positions(two: dict[str, Any]) -> None:
    rels = [_rel("a", "b"), _rel("b", "a")]
    scan = scan_sources(two, relationships=rels, relationship_positions=[2, 5])
    assert len(scan.relationships) == 2


def test_table_selection_is_refused_when_the_request_is_built(two: dict[str, Any]) -> None:
    with pytest.raises(PipelineConfigError, match="not in sources"):
        DeclarationRequest.for_scan({"sources": two}, ["zz"])
    with pytest.raises(PipelineConfigError, match="not in sources"):
        _declare({"sources": two}, ["a", "zz"])
    with pytest.raises(PipelineConfigError, match="more than once"):
        _declare({"sources": two}, ["a", "a"])
    assert _declare({"sources": two}, ["b", "a"]).tables == ("b", "a")


def test_column_names_file_is_read_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    names = _file(tmp_path, "names.csv", "id,name\n")
    data = _file(tmp_path, "d.csv", "1,ann\n2,bob\n")
    source = {
        "type": "file",
        "format": "csv",
        "path": str(data),
        "has_header": False,
        "column_names_file": str(names),
    }
    calls: list[str] = []
    real = csv_reader.resolve_column_names_file

    def spy(path: str, **kw: Any) -> tuple[str, ...]:
        calls.append(path)
        return real(path, **kw)

    monkeypatch.setattr(csv_reader, "resolve_column_names_file", spy)
    decl = _declare({"sources": {"d": source}})
    descriptor = dict(decl.descriptors["d"])
    assert descriptor["column_names"] == ["id", "name"]
    assert descriptor["has_header"] is False
    assert "column_names_file" not in descriptor
    result = scan_sources(decl.descriptors, tables=decl.tables)
    assert result.tables[0].profile.row_count == 2
    assert len(calls) == 1


def test_no_data_file_is_opened(tmp_path: Path) -> None:
    decl = _declare({"sources": {"gone": _csv(tmp_path / "missing.csv")}})
    assert decl.tables == ("gone",)


def test_one_validator(two: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    real = scan_set.validate_scan_inputs

    def spy(*args: Any, **kw: Any) -> Any:
        seen.append("call")
        return real(*args, **kw)

    monkeypatch.setattr(scan_set, "validate_scan_inputs", spy)
    scan_sources(two, tables=["a"])
    assert seen == ["call"]
    _declare({"sources": two})
    assert len(seen) >= 2
    declared = Path(__file__).parents[3] / "src/decoy_engine/profile/_declared_columns.py"
    assert "SourceDescriptor" not in declared.read_text()


def test_declaration_is_read_only(two: dict[str, Any]) -> None:
    decl = _declare({"sources": two})
    with pytest.raises(TypeError):
        decl.descriptors["a"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        decl.descriptors["a"]["path"] = "x"  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        decl.tables = ()  # type: ignore[misc]
    two["a"]["path"] = "changed"
    assert decl.descriptors["a"]["path"] != "changed"


def test_scan_declaration_needs_a_scan_request(two: dict[str, Any]) -> None:
    columns = [{"name": n, "strategy": "passthrough"} for n in ("id", "x")]
    config = {
        "version": 2,
        "sources": {"a": two["a"]},
        "tables": [{"name": "a", "columns": columns}],
    }
    prepared = prepare_declared_sources(DeclarationRequest.for_descriptors(config))
    with pytest.raises(TypeError):
        prepared.scan_declaration  # noqa: B018


def _assert_value_free(caught: pytest.ExceptionInfo[BaseException]) -> None:
    exc = caught.value
    assert CANARY not in str(exc)
    assert all(CANARY not in str(a) for a in exc.args)
    assert exc.__context__ is None
    assert exc.__cause__ is None


def test_refusals_are_value_free(tmp_path: Path, two: dict[str, Any]) -> None:
    bad = _csv(_file(tmp_path, "c.csv", "id\n1\n"), has_header=CANARY)
    with pytest.raises(PipelineConfigError) as caught:
        _declare({"sources": {"c": bad}})
    _assert_value_free(caught)
    bad_rel = {"parent": {"table": "a", "columns": CANARY}, "children": []}
    with pytest.raises(PipelineConfigError) as caught:
        _declare({"sources": two, "relationships": [bad_rel]})
    _assert_value_free(caught)
    names = _file(tmp_path, "names.csv", f"{CANARY}\n{CANARY}\n")
    path = str(tmp_path / "d.csv")
    src = {
        "type": "file",
        "format": "csv",
        "path": path,
        "has_header": False,
        "column_names_file": str(names),
    }
    with pytest.raises(Exception) as caught:
        _declare({"sources": {"d": src}})
    _assert_value_free(caught)
