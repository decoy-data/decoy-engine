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
from decoy_engine.execution import PandasExecutionAdapter, run_pipeline, run_pipeline_isolated
from decoy_engine.execution._chunked import run_mask_pipeline_chunked
from decoy_engine.execution.native._chunked_entry import run_mask_chunked as run_native_chunked
from decoy_engine.execution.out_of_core import run_fk_out_of_core
from decoy_engine.io import SourceDateTypeUnsupportedError, SourceDateUnrepresentableError
from decoy_engine.profile._readers import LazySource
from decoy_engine.relationships._graph import OrphanPolicy
from tests.native._chunked_entry_support import key_provider
from tests.perf_fixtures.fk_relational import build_fk_relational
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
    # Names only: no year, no count of cells (the count is on the exception object).
    assert str(exc) == (
        f"[{CODE}] {reasons.get('runtime', CODE).summary} Table {TABLE!r}, column 'd'."
    )


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
        extra["sources"] = {TABLE: LazySource(path)}
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
        sources: dict[str, Any] | None = {n: LazySource(p) for n, p in paths.items()}
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
        run_pipeline(cfg, sources={TABLE: LazySource(path)}, **_kwargs())
    _assert_value_free(caught.value)


def test_a_refused_run_publishes_nothing(tmp_path: Path) -> None:
    cfg, path, _ = _setup(tmp_path)
    sink, target = b6a.real_sink(tmp_path, "out")
    with pytest.raises(SourceDateUnrepresentableError):
        run_pipeline(cfg, sources={TABLE: LazySource(path)}, sink=sink, **_kwargs())
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
    opened = LazySource(path).open_batches(GROUP)
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
    result = run_pipeline(cfg, sources={TABLE: LazySource(path)}, **_kwargs())
    assert result.outputs[TABLE].num_rows == ROWS


def test_the_adapter_run_sequential_checks_its_own_loader() -> None:
    """`run_sequential` is also a public adapter entry that does not go through `run_pipeline`."""
    fx = build_fk_relational(rows=50, width=2, orphan_frac=0.0)

    def load(name: str) -> pa.Table:
        table = fx.sources[name]
        return table.append_column("far", pa.array([FAR_DAY] * table.num_rows, pa.date32()))

    with pytest.raises(SourceDateUnrepresentableError) as caught:
        PandasExecutionAdapter().run_sequential(
            fx.plan,
            load,
            config={},
            registry=fx.registry,
            relationship_graph=fx.graph(OrphanPolicy.PRESERVE),
            namespace_registry=fx.namespace_registry,
        )
    assert caught.value.column == "far" and caught.value.code == CODE
    assert "10183" not in str(caught.value)


def _outcome(call: Any) -> BaseException | None:
    """What `call` raised, or `None`. Lets a test fail on an assertion about the outcome instead
    of on whatever exception the unchecked code path happens to raise."""
    try:
        call()
    except Exception as exc:
        return exc
    return None


def _assert_refused(exc: BaseException | None, *, column: str) -> None:
    assert isinstance(exc, SourceDateUnrepresentableError), repr(type(exc))
    assert (exc.table, exc.column, exc.count) == (TABLE, column, 1)
    assert exc.code == CODE
    assert exc.__cause__ is None and exc.__context__ is None
    text = str(exc) + repr(exc)
    assert "10183" not in text and "12921" not in text and str(FAR_DAY) not in text


def _far_chunks(bad_at: tuple[int, ...]) -> list[pa.Table]:
    """Three small chunks; each index in `bad_at` carries one far date."""
    out = []
    for i in range(3):
        days = [1, 2, FAR_DAY if i in bad_at else 3]
        ids = pa.array([i * 3, i * 3 + 1, i * 3 + 2])
        out.append(pa.table({"id": ids, "d": pa.array(days, pa.date32())}))
    return out


@pytest.mark.parametrize("bad_at", [(0,), (2,)])
def test_the_exported_native_or_oracle_entry_refuses_the_far_date(
    bad_at: tuple[int, ...], tmp_path: Path
) -> None:
    from decoy_engine.execution.native import run_native_or_oracle_chunked

    cfg, _, _ = _setup(tmp_path)
    chunks = iter(_far_chunks(bad_at))
    exc = _outcome(
        lambda: list(
            run_native_or_oracle_chunked(
                cfg, chunks, table=TABLE, engine_version=support.ENGINE_VERSION
            )
        )
    )
    _assert_refused(exc, column="d")


@pytest.mark.parametrize("entry", ["run", "run_single"])
def test_the_adapter_resident_entries_refuse_the_far_date(entry: str) -> None:
    fx = build_fk_relational(rows=50, width=2, orphan_frac=0.0)
    rows = next(iter(fx.sources.values())).num_rows
    name = next(iter(fx.sources))
    far = pa.array([FAR_DAY] * rows, pa.date32())
    sources = {name: fx.sources[name].append_column("far", far)}
    kwargs: dict[str, Any] = {
        "registry": fx.registry,
        "relationship_graph": fx.graph(OrphanPolicy.PRESERVE),
        "namespace_registry": fx.namespace_registry,
    }
    adapter = PandasExecutionAdapter()
    if entry == "run":
        exc = _outcome(lambda: adapter.run(fx.plan, sources, **kwargs))
    else:
        exc = _outcome(lambda: adapter.run_single(fx.plan, sources[name], table=name, **kwargs))
    assert isinstance(exc, SourceDateUnrepresentableError), repr(type(exc))
    assert exc.column == "far" and exc.code == CODE
    assert "10183" not in str(exc)


def _nested(shape: str) -> pa.Array:
    far = pa.array([0, 1, FAR_DAY], pa.date32())
    if shape == "list":
        return pa.ListArray.from_arrays(pa.array([0, 1, 2, 3], pa.int32()), far)
    return pa.StructArray.from_arrays([far], names=["when"])


@pytest.mark.parametrize("shape", ["list", "struct"])
@pytest.mark.parametrize("route", ["oracle", "native"])
def test_a_date_in_a_list_or_struct_is_refused_by_type_on_both_chunked_routes(
    shape: str, route: str, tmp_path: Path
) -> None:
    """Owner question Q6 answer A: refused by type, whether the nested date is far or not."""
    ids, days = pa.array([0, 1, 2]), pa.array([0, 1, 2], pa.date32())
    chunk = pa.table({"id": ids, "d": days, "n": _nested(shape)})
    path = tmp_path / "nested.parquet"
    pq.write_table(
        chunk.set_column(2, "n", pa.array([None] * 3, chunk.schema.field("n").type)), str(path)
    )
    cols = [support.pass_col(name) for name in ("id", "d", "n")]
    cfg = support.make_cfg(cols, path=str(path))
    kwargs: dict[str, Any] = {"table": TABLE, "engine_version": support.ENGINE_VERSION}
    if route == "oracle":
        exc = _outcome(
            lambda: list(
                run_mask_pipeline_chunked(cfg, iter([chunk]), source_schema=chunk.schema, **kwargs)
            )
        )
    else:
        exc = _outcome(lambda: list(run_native_chunked(cfg, iter([chunk]), **kwargs)))
    assert isinstance(exc, SourceDateTypeUnsupportedError), repr(type(exc))
    assert (exc.table, exc.column, exc.kind) == (TABLE, "n", shape)
    assert exc.code == reasons.runtime.SOURCE_DATE_TYPE_UNSUPPORTED


@pytest.mark.parametrize("route", ["oracle", "native"])
def test_an_unused_far_dictionary_entry_does_not_refuse_the_job_or_reach_pandas(
    route: str, tmp_path: Path
) -> None:
    """Section 4.4 counts referenced rows. The entry no row uses is dropped by the checked read,
    so pandas never converts it."""
    cfg, _, _ = _setup(tmp_path)
    dictionary = pa.array([0, 1, FAR_DAY], pa.date32())
    column = pa.DictionaryArray.from_arrays(pa.array([0, 1, 1, None], pa.int8()), dictionary)
    chunk = pa.table({"id": pa.array([0, 1, 2, 3]), "d": column})
    kwargs: dict[str, Any] = {"table": TABLE, "engine_version": support.ENGINE_VERSION}
    out: list[pa.Table] = []
    if route == "oracle":
        exc = _outcome(
            lambda: out.extend(
                run_mask_pipeline_chunked(cfg, iter([chunk]), source_schema=chunk.schema, **kwargs)
            )
        )
    else:
        exc = _outcome(lambda: out.extend(run_native_chunked(cfg, iter([chunk]), **kwargs)))
    assert exc is None, repr(type(exc))
    assert [t.num_rows for t in out] == [4]


# --- AT-V7: the refusal names the table the caller gave -----------------------------------------


@pytest.mark.parametrize("route", ROUTES)
def test_a_stale_lazy_source_name_is_rebound_to_the_mapping_key(route: str, tmp_path: Path) -> None:
    cfg, path, _ = _setup(tmp_path)
    sources = {TABLE: LazySource(path, table="other")}
    with pytest.raises(SourceDateUnrepresentableError) as caught:
        run_pipeline(cfg, sources=sources, **_kwargs(**ROUTES[route]))
    _assert_value_free(caught.value)


def test_check_resident_sources_binds_a_copy_and_keeps_the_original_name(tmp_path: Path) -> None:
    from decoy_engine.io import check_resident_sources
    from decoy_engine.profile._lazy_csv import CsvLazySource

    _, path, _ = _setup(tmp_path)
    csv = tmp_path / "t.csv"
    csv.write_text("id,d\n1,2020-01-01\n")
    originals = {"parquet": LazySource(path, table="other"), "csv": CsvLazySource(csv)}
    bound = check_resident_sources({"a": originals["parquet"], "b": originals["csv"]})
    assert (bound["a"].table, bound["b"].table) == ("a", "b")
    assert type(bound["a"]) is LazySource and type(bound["b"]) is CsvLazySource
    assert bound["a"].path == path and bound["b"].path == csv
    assert bound["a"] is not originals["parquet"] and originals["parquet"].table == "other"
    assert originals["csv"].table == "source"


def test_an_object_that_is_not_a_lazy_dataclass_passes_through_unbound() -> None:
    from decoy_engine.io import check_resident_sources

    marker = object()
    assert check_resident_sources({"t": marker})["t"] is marker


def test_the_isolated_manifest_loader_names_the_mapping_key(tmp_path: Path) -> None:
    from decoy_engine.execution import _isolated_worker

    _, path, _ = _setup(tmp_path)
    loaded = _isolated_worker._load_sources(
        {"key": {"path": str(path), "format": "parquet"}}, lazy=True
    )
    source = loaded["key"]
    assert isinstance(source, LazySource) and source.table == "key"
    with pytest.raises(SourceDateUnrepresentableError) as caught:
        list(source.iter_batches(GROUP))
    assert caught.value.table == "key"
