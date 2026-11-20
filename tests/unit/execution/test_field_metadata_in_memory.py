"""OUTPUT-METADATA-LEAK E2: an in-memory output carries no source field metadata on a column a
strategy rewrote (the metadata can describe the original values), and keeps it on a carried
column at the one choke point, `attach_output_metadata`. The writers strip field metadata
separately; this pins the schema the caller holds before any write.

The run cells cover the resident routes that return tables (sequential, full_frame, out_of_core).
Those routes drop passthrough field metadata on ingest today, so the keep side is pinned at the
schema builders every sink route shares (fixed schema, payload schema, FK rewrite)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import run_pipeline
from decoy_engine.execution.out_of_core import _mask, _rewrite_pass, _stream_driver_support
from decoy_engine.profile._readers import LazySource
from decoy_engine.safe_output import attach_output_metadata, output_table
from tests.security import _metadata_canary as mc
from tests.unit.execution._transform_testkit import fk_config, fk_tables

MASKED = {"parent": ("id", "note"), "child": ("cid", "parent_id")}
FIELD_KEY = b"comment"
CHILD_KEY = b"k"


def _canary_source(table: pa.Table) -> pa.Table:
    return mc.canary_table({n: table[n].combine_chunks() for n in table.column_names})


def _run_fk(tmp_path: Path, mode: str, *, lazy: bool) -> dict[str, pa.Table]:
    parent, child = fk_tables()
    cfg = fk_config(tmp_path, parent, child)
    paths = {n: Path(cfg["sources"][n]["path"]) for n in ("parent", "child")}
    pq.write_table(_canary_source(parent), paths["parent"])
    pq.write_table(_canary_source(child), paths["child"])
    sources: dict[str, Any] = (
        {n: LazySource(path=p) for n, p in paths.items()}
        if lazy
        else {n: pq.read_table(p) for n, p in paths.items()}
    )
    result = run_pipeline(cfg, sources, engine_version="field-meta-test", execution_mode=mode)
    assert result.quality_metrics["execution"]["execution_mode"] == mode
    return dict(result.outputs)


ROUTES: dict[str, Callable[[Path], dict[str, pa.Table]]] = {
    "sequential": lambda p: _run_fk(p, "sequential", lazy=False),
    "full_frame": lambda p: _run_fk(p, "full_frame", lazy=False),
    "out_of_core": lambda p: _run_fk(p, "out_of_core", lazy=True),
}


def _texts(schema: pa.Schema) -> bytes:
    return b"".join(mc.schema_texts(schema))


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_a_rewritten_column_carries_no_source_field_metadata(route: str, tmp_path: Path) -> None:
    outputs = ROUTES[route](tmp_path)
    for table, names in MASKED.items():
        for name in names:
            field = outputs[table].schema.field(name)
            assert not field.metadata, (route, table, name, field.metadata)


def test_publish_tables_input_drops_every_field_metadata() -> None:
    """The publisher's in-memory entry: `output_table` keeps no field metadata at any depth."""
    child = pa.field("c", pa.string(), metadata={b"k": mc.NESTED.encode()})
    nested = pa.array([{"c": "v"}] * 2, pa.struct([child]))
    table = mc.canary_table({"a": pa.array(["x", "y"]), "st": nested})
    out = output_table(table)
    assert mc.FIELD.encode() not in _texts(out.schema)
    assert mc.NESTED.encode() not in _texts(out.schema)


# -- the choke point: carried columns keep field metadata, every other column loses it ------------


def _source_schema() -> pa.Schema:
    child = pa.field("c", pa.string(), metadata={CHILD_KEY: mc.NESTED.encode()})
    return pa.schema(
        [
            pa.field("kept", pa.int64(), metadata={FIELD_KEY: b"keep"}),
            pa.field("kept_nested", pa.struct([child]), metadata={FIELD_KEY: b"keep"}),
            pa.field("masked", pa.string(), metadata={FIELD_KEY: mc.FIELD.encode()}),
            pa.field("masked_nested", pa.struct([child]), metadata={FIELD_KEY: mc.FIELD.encode()}),
        ]
    )


def test_attach_keeps_a_carried_field_and_drops_every_other() -> None:
    src = _source_schema()
    out = attach_output_metadata(src, None, carried=("kept", "kept_nested"))
    assert out.field("kept").metadata == {FIELD_KEY: b"keep"}
    assert out.field("kept_nested").metadata == {FIELD_KEY: b"keep"}
    assert out.field("kept_nested").type.field(0).metadata == {CHILD_KEY: mc.NESTED.encode()}
    assert not out.field("masked").metadata
    assert not out.field("masked_nested").metadata
    assert not out.field("masked_nested").type.field(0).metadata


def test_attach_with_no_carried_columns_is_bare() -> None:
    out = attach_output_metadata(_source_schema(), None, carried=())
    assert mc.FIELD.encode() not in _texts(out)
    assert mc.NESTED.encode() not in _texts(out)
    assert b"keep" not in _texts(out)


class _Seed:
    def __init__(self, names: tuple[str, ...]) -> None:
        self.per_column = tuple((n, object()) for n in names)


@pytest.mark.parametrize(
    "module", [_rewrite_pass, _stream_driver_support], ids=["rewrite_pass", "stream_support"]
)
def test_the_fixed_output_schema_keeps_passthrough_and_drops_masked(
    module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _source_schema()
    monkeypatch.setattr(module, "table_seed", lambda plan, name: _Seed(("masked", "masked_nested")))
    monkeypatch.setattr(module, "masked_output_type", lambda column_seed, typ: typ)
    out = module._fixed_output_schema(None, "t", src, {})
    assert out.field("kept").metadata == {FIELD_KEY: b"keep"}
    assert out.field("kept_nested").type.field(0).metadata == {CHILD_KEY: mc.NESTED.encode()}
    assert not out.field("masked").metadata
    assert not out.field("masked_nested").type.field(0).metadata


def test_the_stream_payload_schema_drops_a_skipped_fk_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = _source_schema()
    monkeypatch.setattr(_stream_driver_support, "table_seed", lambda plan, name: None)
    out = _stream_driver_support._payload_schema(None, "t", src, frozenset({"kept"}))
    assert not out.field("kept").metadata
    assert out.field("kept_nested").metadata == {FIELD_KEY: b"keep"}


def test_a_replaced_fk_column_loses_its_field_metadata_in_the_stream_rewrite() -> None:
    src = _source_schema()
    batch = pa.record_batch(
        [
            pa.array([1]),
            pa.array([{"c": "v"}], src.field("kept_nested").type),
            pa.array(["a"]),
            pa.array([{"c": "v"}], src.field("masked_nested").type),
        ],
        schema=src,
    )
    out = _stream_driver_support._replace_fk_columns(
        batch, ("masked",), (pa.array(["z"]),), (pa.string(),)
    )
    assert not out.schema.field("masked").metadata
    assert out.schema.field("kept").metadata == {FIELD_KEY: b"keep"}


def test_mask_batch_without_a_plan_for_the_table_keeps_every_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_mask, "table_seed", lambda plan, name: None)
    batch = pa.record_batch([pa.array(["a"])], schema=pa.schema([_source_schema().field("masked")]))
    assert _mask.mask_batch(None, "t", batch).schema.field("masked").metadata  # type: ignore[arg-type]
