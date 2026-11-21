"""`build_column_shapes`: the one assembler, and where each fact in its order comes from."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pyarrow as pa

from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.plan.checks._column_shapes import build_column_shapes
from decoy_engine.profile import ColumnProfile, Profile, TableProfile

S = ColumnShape


def _col(name: str, shape: ColumnShape) -> ColumnProfile:
    return ColumnProfile(
        name=name,
        dtype="object",
        row_count=1,
        null_count=0,
        distinct_count=1,
        sampled=False,
        is_candidate_key_sampled=False,
        declared_pk=False,
        is_fk=False,
        fk_target=None,
        pii_class=None,
        shape=shape,
    )


def _profile(table: str = "t", **shapes: ColumnShape) -> Profile:
    return Profile(
        schema_version=1,
        tables=(
            TableProfile(
                name=table, row_count=1, columns=tuple(_col(n, s) for n, s in shapes.items())
            ),
        ),
        relationships=(),
        profiled_at=datetime(2026, 1, 1),
        decoy_engine_version="0.1.0",
    )


def _cfg(*columns: dict[str, Any], fmt: str | None = None) -> dict[str, Any]:
    cfg: dict[str, Any] = {"tables": [{"name": "t", "columns": list(columns)}]}
    if fmt is not None:
        cfg["sources"] = {"t": {"type": "file", "format": fmt, "path": "/dev/null"}}
    return cfg


def _shift(name: str = "d", **extra: Any) -> dict[str, Any]:
    return {"name": name, "strategy": "date_shift", "namespace": "ns", **extra}


def test_only_columns_under_a_shape_reading_strategy_get_a_shape() -> None:
    cfg = _cfg(_shift(), {"name": "h", "strategy": "hash", "namespace": "n"})
    assert set(build_column_shapes(cfg)) == {("t", "d")}


def test_config_only_with_no_facts_is_unknown() -> None:
    assert build_column_shapes(_cfg(_shift())) == {("t", "d"): S.UNKNOWN}


def test_config_facts_override_observed_shape() -> None:
    # An F06 declaration on a column the profile saw as text.
    declared = _shift(logical_type="date", parse_format={"id": "date/iso8601/v1"})
    nested = {
        "name": "doc",
        "strategy": "nested",
        "provider_config": {"strategy": "date_shift", "target": "$.a"},
    }
    got = build_column_shapes(_cfg(declared, nested), profile=_profile(d=S.TEXT, doc=S.DATE))
    assert got == {("t", "d"): S.DATE, ("t", "doc"): S.TEXT}


def test_text_format_beats_a_stale_profile() -> None:
    got = build_column_shapes(_cfg(_shift(), fmt="csv"), profile=_profile(d=S.DATE))
    assert got == {("t", "d"): S.TEXT}


def test_observed_shape_used_directly() -> None:
    # The profile's value is already a shape: it is not passed back through the Arrow classifier,
    # which would call it `other`.
    got = build_column_shapes(_cfg(_shift()), profile=_profile(d=S.DATE))
    assert got == {("t", "d"): S.DATE}


def test_loader_table_shape_from_loader_schema() -> None:
    # A source-loader table has no descriptor and no profile entry.
    schemas = {"t": pa.schema([("d", pa.date32())])}
    got = build_column_shapes(
        _cfg(_shift()), profile=_profile(table="other"), source_schemas=schemas
    )
    assert got == {("t", "d"): S.DATE}


def test_profile_unknown_falls_through_to_the_schema() -> None:
    schemas = {"t": pa.schema([("d", pa.timestamp("us"))])}
    got = build_column_shapes(_cfg(_shift()), profile=_profile(d=S.UNKNOWN), source_schemas=schemas)
    assert got == {("t", "d"): S.TIMESTAMP_NAIVE}


def test_schema_without_the_column_is_unknown() -> None:
    schemas = {"t": pa.schema([("x", pa.date32())])}
    assert build_column_shapes(_cfg(_shift()), source_schemas=schemas) == {("t", "d"): S.UNKNOWN}


def test_result_is_sorted_by_table_then_column() -> None:
    cfg = {
        "tables": [
            {"name": "b", "columns": [_shift("z"), _shift("a")]},
            {"name": "a", "columns": [_shift("m")]},
        ]
    }
    assert list(build_column_shapes(cfg)) == [("a", "m"), ("b", "a"), ("b", "z")]


def test_odd_config_shapes_are_skipped() -> None:
    assert build_column_shapes({}) == {}
    assert build_column_shapes({"tables": "x"}) == {}
    assert (
        build_column_shapes({"tables": [1, {"columns": [None]}, {"name": "t", "columns": [3]}]})
        == {}
    )
