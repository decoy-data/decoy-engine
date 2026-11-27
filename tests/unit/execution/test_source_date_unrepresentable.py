"""AT-V1 (DATE-RANGE-SENTINEL S5): a source date outside calendar years 1 to 9999 is refused on
every route with `runtime/source_date_unrepresentable`, naming table, column and count, and never
quoting the year. The bad cell sits in a later Parquet row group, past the profile sample."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import reasons
from decoy_engine.config import PipelineConfig
from decoy_engine.errors import SourceDateUnrepresentableError
from decoy_engine.execution import run_pipeline, run_pipeline_isolated
from decoy_engine.execution._chunked import run_mask_pipeline_chunked
from decoy_engine.execution.native._chunked_entry import run_mask_chunked as run_native_chunked
from decoy_engine.execution.out_of_core import run_fk_out_of_core
from decoy_engine.profile._readers import LazySource
from tests.native._chunked_entry_support import key_provider
from tests.unit.execution import _auto_chunk_support as support
from tests.unit.execution import _b6a_support as b6a

TABLE = support.TABLE
ROWS, GROUP, BAD_ROW = 12_000, 5_000, 10_000
FAR_DAY = 3_000_000  # a date32 in year 10183
CODE = reasons.runtime.SOURCE_DATE_UNREPRESENTABLE


def _source(bad_row: int | None = BAD_ROW) -> pa.Table:
    days = [i % 20_000 for i in range(ROWS)]
    if bad_row is not None:
        days[bad_row] = FAR_DAY
    return pa.table({"id": pa.array(range(ROWS)), "d": pa.array(days, pa.date32())})


def _setup(
    tmp_path: Path, bad_row: int | None = BAD_ROW, *, config_reads_bad: bool = False
) -> tuple[dict[str, Any], Path, pa.Table]:
    """The bad source file and table, and a config that declares a clean copy, so the profile
    never meets the bad cell and each read hook is tested on its own."""
    table = _source(bad_row)
    path = tmp_path / "t.parquet"
    pq.write_table(table, str(path), row_group_size=GROUP)
    declared = path
    if not config_reads_bad:
        declared = tmp_path / "clean.parquet"
        pq.write_table(_source(None), str(declared), row_group_size=GROUP)
    cfg = support.make_cfg([support.pass_col("id"), support.pass_col("d")], path=str(declared))
    return cfg, path, table


def _assert_value_free(exc: BaseException) -> None:
    assert isinstance(exc, SourceDateUnrepresentableError)
    assert (exc.table, exc.column, exc.count) == (TABLE, "d", 1)
    assert exc.code == CODE
    text = str(exc) + repr(exc)
    assert "10183" not in text and str(FAR_DAY) not in text
    assert exc.__cause__ is None and exc.__context__ is None


def _kwargs(**extra: Any) -> dict[str, Any]:
    return support.run_kwargs(**extra)


ROUTES = {
    "FF": {"execution_mode": "full_frame", "auto_chunk": False},
    "AUTO": {},
}


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("shape", ["lazy", "resident", "loader"])
def test_every_run_pipeline_route_refuses_the_far_date(
    route: str, shape: str, tmp_path: Path
) -> None:
    cfg, path, table = _setup(tmp_path)
    extra = dict(ROUTES[route])
    if shape == "lazy":
        extra["sources"] = {TABLE: LazySource(path, table=TABLE)}
    elif shape == "resident":
        extra["sources"] = {TABLE: table}
    else:
        extra.update(source_loader=lambda name: table, source_loader_schemas={TABLE: table.schema})
        extra["sources"] = None
    sources = extra.pop("sources")
    with pytest.raises(SourceDateUnrepresentableError) as caught:
        run_pipeline(cfg, sources=sources, **_kwargs(**extra))
    _assert_value_free(caught.value)


@pytest.mark.parametrize("shape", ["lazy", "resident", "loader"])
@pytest.mark.parametrize("mode", ["sequential", "out_of_core"])
def test_the_relationship_routes_refuse_the_far_date(shape: str, mode: str, tmp_path: Path) -> None:
    child = _source()
    parent = pa.table({"id": pa.array([f"r{i}" for i in range(3)])})
    child = child.append_column("ref", pa.array([f"r{i % 3}" for i in range(ROWS)]))
    paths = {}
    for name, table in (("parent", parent), ("t", child)):
        paths[name] = tmp_path / f"{name}.parquet"
        pq.write_table(table, str(paths[name]), row_group_size=GROUP)
    raw = {
        "version": 2,
        "global_settings": {"seed": 7, "post_validation": False},
        "sources": {
            n: {"type": "file", "format": "parquet", "path": str(p)} for n, p in paths.items()
        },
        "targets": {n: {"type": "file", "format": "csv", "path": f"/dev/null.{n}"} for n in paths},
        "tables": [
            {"name": "parent", "columns": [{"name": "id", "strategy": "hash", "namespace": "ns"}]},
            {
                "name": "t",
                "columns": [
                    {"name": "ref", "strategy": "hash", "namespace": "ns"},
                    support.pass_col("d"),
                    support.pass_col("id"),
                ],
            },
        ],
        "relationships": [
            {
                "parent": {"table": "parent", "columns": ["id"]},
                "children": [{"table": "t", "columns": ["ref"]}],
                "orphan_policy": "preserve",
                "namespace": "ns",
            }
        ],
    }
    cfg = PipelineConfig.model_validate(raw).model_dump()
    tables = {"parent": parent, "t": child}
    kwargs: dict[str, Any] = {"execution_mode": mode, "key_provider": key_provider()}
    if shape == "lazy":
        sources: dict[str, Any] | None = {n: LazySource(p, table=n) for n, p in paths.items()}
    elif shape == "resident":
        sources = tables
    else:
        sources = None
        kwargs.update(
            source_loader=lambda name: tables[name],
            source_loader_schemas={n: t.schema for n, t in tables.items()},
        )
    with pytest.raises(SourceDateUnrepresentableError) as caught:
        run_pipeline(cfg, sources=sources, engine_version=support.ENGINE_VERSION, **kwargs)
    assert caught.value.table == "t" and caught.value.column == "d"
    assert "10183" not in str(caught.value)


def test_a_first_batch_profile_failure_is_the_same_coded_refusal(tmp_path: Path) -> None:
    cfg, path, _ = _setup(tmp_path, bad_row=3, config_reads_bad=True)
    with pytest.raises(SourceDateUnrepresentableError) as caught:
        run_pipeline(cfg, sources={TABLE: LazySource(path, table=TABLE)}, **_kwargs())
    _assert_value_free(caught.value)


def test_a_refused_run_publishes_nothing(tmp_path: Path) -> None:
    cfg, path, _ = _setup(tmp_path)
    sink, target = b6a.real_sink(tmp_path, "out")
    with pytest.raises(SourceDateUnrepresentableError):
        run_pipeline(cfg, sources={TABLE: LazySource(path, table=TABLE)}, sink=sink, **_kwargs())
    assert not Path(target).exists()


def _chunks(table: pa.Table) -> list[pa.Table]:
    return [table.slice(i, GROUP) for i in range(0, table.num_rows, GROUP)]


def test_the_chunked_oracle_refuses_the_far_date_in_a_later_chunk(tmp_path: Path) -> None:
    cfg, _, table = _setup(tmp_path)
    with pytest.raises(SourceDateUnrepresentableError) as caught:
        list(
            run_mask_pipeline_chunked(
                cfg,
                iter(_chunks(table)),
                table=TABLE,
                engine_version=support.ENGINE_VERSION,
                source_schema=table.schema,
            )
        )
    _assert_value_free(caught.value)


def test_the_native_chunked_entry_refuses_the_far_date_in_a_later_chunk(tmp_path: Path) -> None:
    cfg, _, table = _setup(tmp_path)
    with pytest.raises(SourceDateUnrepresentableError) as caught:
        list(
            run_native_chunked(
                cfg,
                iter(_chunks(table)),
                table=TABLE,
                engine_version=support.ENGINE_VERSION,
            )
        )
    _assert_value_free(caught.value)


def test_the_direct_out_of_core_entry_checks_resident_sources_first(tmp_path: Path) -> None:
    _, _, table = _setup(tmp_path)
    with pytest.raises(SourceDateUnrepresentableError) as caught:
        run_fk_out_of_core(
            None,  # type: ignore[arg-type]
            {TABLE: table},
            registry=None,  # type: ignore[arg-type]
            relationship_graph=None,  # type: ignore[arg-type]
            config={},
        )
    _assert_value_free(caught.value)


def test_opened_row_group_batches_are_checked(tmp_path: Path) -> None:
    _, path, _ = _setup(tmp_path)
    opened = LazySource(path, table=TABLE).open_batches(GROUP)
    try:
        with pytest.raises(SourceDateUnrepresentableError) as caught:
            list(opened.batches)
    finally:
        opened.close()
    _assert_value_free(caught.value)


def test_the_isolated_route_reports_the_code_without_the_year(tmp_path: Path) -> None:
    cfg, _, table = _setup(tmp_path)
    result = run_pipeline_isolated(
        cfg,
        {TABLE: table},
        engine_version=support.ENGINE_VERSION,
    )
    assert result.outcome == "crashed"
    assert result.outputs is None
    assert "SourceDateUnrepresentableError" in (result.error or "")
    assert "10183" not in (result.error or "")


def test_a_clean_source_still_runs(tmp_path: Path) -> None:
    cfg, path, _ = _setup(tmp_path, bad_row=None)
    result = run_pipeline(cfg, sources={TABLE: LazySource(path, table=TABLE)}, **_kwargs())
    assert result.outputs[TABLE].num_rows == ROWS
