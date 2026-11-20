"""OUTPUT-METADATA-LEAK E2: the sanitized pandas blob is built once per table, and the schema the
out-of-core emit reconciles onto is already sanitized."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.execution.out_of_core import (
    _budget,
    _emit,
    _rewrite_pass,
    _stream_driver_support,
)
from decoy_engine.safe_output import _file_metadata, attach_output_metadata
from tests.security import _metadata_canary as mc

CARRIERS = (mc.SCHEMA, mc.ATTRS, mc.SKEY, mc.CREATOR, mc.PDVER, mc.RIDX, mc.COLIDX)


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    _file_metadata._kept_metadata.cache_clear()
    yield
    _file_metadata._kept_metadata.cache_clear()


def _source() -> pa.Table:
    return mc.canary_table({"a": pa.array(["x", "y"]), "n": pa.array([1, 2])})


def _count_sanitizer(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    real = _file_metadata._ALLOWED_SCHEMA_KEYS[b"pandas"]

    def counting(raw: bytes, schema: pa.Schema) -> bytes | None:
        calls.append(1)
        return real(raw, schema)

    monkeypatch.setitem(_file_metadata._ALLOWED_SCHEMA_KEYS, b"pandas", counting)
    return calls


def test_the_blob_is_computed_once_per_table(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _count_sanitizer(monkeypatch)
    src = _source()
    bare = pa.schema([pa.field(f.name, f.type) for f in src.schema])
    for _ in range(50):  # one call per batch of one table
        attach_output_metadata(bare, src.schema.metadata)
    assert len(calls) == 1


def test_a_different_output_schema_is_computed_again(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _count_sanitizer(monkeypatch)
    src = _source()
    attach_output_metadata(pa.schema([pa.field("a", pa.string())]), src.schema.metadata)
    attach_output_metadata(pa.schema([pa.field("a", pa.int64())]), src.schema.metadata)
    assert len(calls) == 2


def test_a_cached_result_still_carries_no_source_text() -> None:
    src = _source()
    bare = pa.schema([pa.field(f.name, f.type) for f in src.schema])
    first = attach_output_metadata(bare, src.schema.metadata)
    again = attach_output_metadata(bare, src.schema.metadata)
    assert first.metadata == again.metadata
    assert set(again.metadata or {}) == {b"pandas"}
    assert not [c for c in CARRIERS if c.encode() in b"".join(again.metadata.values())]


@pytest.mark.parametrize(
    "builder",
    [_rewrite_pass._fixed_output_schema, _stream_driver_support._fixed_output_schema],
    ids=["rewrite_pass", "stream_driver_support"],
)
def test_the_fixed_output_schema_is_sanitized_before_emit(
    builder: Callable[..., pa.Schema], monkeypatch: pytest.MonkeyPatch
) -> None:
    for module in (_rewrite_pass, _stream_driver_support):
        monkeypatch.setattr(module, "table_seed", lambda plan, name: None)
    fixed = builder(None, "t", _source().schema, {})
    assert set(fixed.metadata or {}) <= {b"pandas"}
    assert not [c for c in CARRIERS if c.encode() in b"".join((fixed.metadata or {}).values())]


def test_reconcile_batch_takes_its_metadata_from_the_fixed_schema() -> None:
    """`reconcile_batch` rebuilds the batch on `fixed_schema` as given, so what that schema
    carries is what the emitted batch carries: the builders above must sanitize it."""
    src = _source()
    fixed: Any = attach_output_metadata(
        pa.schema([pa.field(f.name, f.type) for f in src.schema]), src.schema.metadata
    )
    batch = src.combine_chunks().to_batches()[0]  # carries every source canary
    out = _emit.reconcile_batch(batch, fixed)
    assert out.schema.metadata == fixed.metadata
    assert set(out.schema.metadata or {}) <= {b"pandas"}


# -- a real multi-batch out-of-core run ----------------------------------------------------------


def _ooc_run(tmp_path: Any) -> None:
    import pyarrow.parquet as pq

    from decoy_engine import run_pipeline
    from decoy_engine.execution._transactional_sink import ParquetTransactionalSink
    from decoy_engine.profile._readers import LazySource
    from tests.unit.execution._transform_testkit import fk_config, fk_tables

    parent, child = fk_tables()
    cfg = fk_config(tmp_path, parent, child)
    paths = {n: tmp_path / f"{n}_in.parquet" for n in ("parent", "child")}
    for name, tbl in (("parent", parent), ("child", child)):
        canary = mc.canary_table({n: tbl[n].combine_chunks() for n in tbl.column_names})
        pq.write_table(canary, paths[name])
    sink = ParquetTransactionalSink(tmp_path / "published")
    result = run_pipeline(
        cfg,
        {n: LazySource(path=p) for n, p in paths.items()},
        engine_version="metadata-carriers-test",
        sink=sink,
        execution_mode="out_of_core",
    )
    assert result.quality_metrics["execution"]["execution_mode"] == "out_of_core"


def _sanitizer_calls_and_hits(
    tmp_path: Any, batch_rows: int, mp: pytest.MonkeyPatch
) -> tuple[int, int]:
    _file_metadata._kept_metadata.cache_clear()
    mp.setattr(_budget, "_MIN_BATCH_ROWS", batch_rows)
    mp.setattr(_budget, "_MAX_BATCH_ROWS", batch_rows)
    _ooc_run(tmp_path)
    info = _file_metadata._kept_metadata.cache_info()
    return info.misses, info.hits


def test_a_multi_batch_run_sanitizes_once_per_table(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanitizer calls do not grow with the batch count: a 2-row batch size and a one-batch run
    pay the same, and the extra batches are served from the per-table result."""
    calls = _count_sanitizer(monkeypatch)
    (tmp_path / "one").mkdir()
    (tmp_path / "many").mkdir()
    one_misses, _ = _sanitizer_calls_and_hits(tmp_path / "one", 10_000, monkeypatch)
    one_calls = len(calls)
    calls.clear()
    many_misses, many_hits = _sanitizer_calls_and_hits(tmp_path / "many", 2, monkeypatch)
    assert many_hits > one_misses, "the run must really have more than one batch per table"
    assert (len(calls), many_misses) == (one_calls, one_misses)
    assert one_calls <= 2 * 3, "a few output schemas per table at most, never one per batch"
