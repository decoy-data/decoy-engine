"""OUTPUT-METADATA-LEAK E0: a canary placed in every source metadata carrier must not reach any
published output Parquet file, on any route.

Each cell publishes through the entry named in the plan (a `ParquetTransactionalSink`,
`publish_tables`, the isolated commit, or `run_subset`), checks from the engine's own result that
the named route ran, and reads only files that result binds (the commit receipt, the sink's
committed paths, `output_paths`, the isolated commit dir).

`test_route_is_clean` is the guarantee: no canary in any file the route's entry committed. E0
marked the red cells strict xfail and pinned each leak set; E1 fixed them at the output writers and
removed the markers and the pins. A failure of the route evidence (the wrong route ran) is a plain
assertion failure.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import run_pipeline
from decoy_engine.execution._isolated_run import run_pipeline_isolated
from decoy_engine.execution._transactional_sink import ParquetTransactionalSink
from decoy_engine.profile._readers import LazySource
from tests.acceptance._f06_support import ISO_DATE
from tests.native._chunked_entry_support import NEEDS_COMPANION
from tests.security import _metadata_canary as mc
from tests.unit.execution._transform_testkit import (
    base_table,
    fk_config,
    fk_tables,
    hash_col,
    single_table_config,
    validated,
)

ENGINE_VERSION = "metadata-canary-test"

Route = Callable[[Path], list[Path]]


class LeakFoundError(AssertionError):
    """A canary reached an output file. The only failure the strict xfail accepts."""


def _canary(table: pa.Table, **kwargs: Any) -> pa.Table:
    return mc.canary_table({n: table[n].combine_chunks() for n in table.column_names}, **kwargs)


def _exec(result: Any) -> dict[str, Any]:
    return result.quality_metrics["execution"]


def _expect_route(result: Any, mode: str, reason: str, *, streamed: bool) -> None:
    ex = _exec(result)
    assert ex["execution_mode"] == mode, ex
    assert ex["route_reason"] == reason, ex
    assert ex["outputs_streamed"] is streamed, ex


def _expect_chunked(result: Any) -> None:
    """The auto-chunk dispatcher lane ran, admitted by the native companion, and streamed."""
    qm = result.quality_metrics
    assert qm["auto_chunk"]["mode"] == "chunked", qm["auto_chunk"]
    assert qm["auto_chunk"]["lane"] == "dispatcher", qm["auto_chunk"]
    assert qm["auto_chunk"]["output"]["mode"] == "streamed", qm["auto_chunk"]
    assert qm["chunked_route"]["native_admitted"] is True, qm["chunked_route"]


def _sink_run(
    tmp_path: Path, cfg: dict[str, Any], sources: Any, mode: str, reason: str, **kwargs: Any
) -> list[Path]:
    sink = ParquetTransactionalSink(tmp_path / "published")
    result = run_pipeline(cfg, sources, engine_version=ENGINE_VERSION, sink=sink, **kwargs)
    _expect_route(result, mode, reason, streamed=True)
    if "auto_chunk" in kwargs:
        _expect_chunked(result)
    paths = [sink.committed_table_path(n) for n in cfg["targets"]]
    mc.assert_bound_by_receipt(paths, sink.receipt)
    return paths


def _publish_resident(tmp_path: Path, outputs: dict[str, pa.Table]) -> list[Path]:
    """Publish tables the way the engine's resident publisher does (F22)."""
    from decoy_engine import fileaccess
    from decoy_engine.fileaccess import FileRequest, FileRole
    from decoy_engine.publication import PublicationRequest
    from decoy_engine.publication._publish import publish_tables

    out = fileaccess.capture().output_dir(
        FileRequest(FileRole.TARGET_OUTPUT, "write", str(tmp_path / "pub"), "targets.path")
    )
    receipt = publish_tables(out, outputs, PublicationRequest(uuid.uuid4().hex), suffix=".parquet")
    paths = [tmp_path / "pub" / f"{n}.parquet" for n in outputs]
    mc.assert_bound_by_receipt(paths, receipt)
    return paths


def _resident_run(
    tmp_path: Path, cfg: dict[str, Any], sources: Any, mode: str, reason: str, **kwargs: Any
) -> list[Path]:
    """A resident route returns tables in memory (the sink is inert for it), so the results are
    published through `publish_tables`."""
    result = run_pipeline(cfg, sources, engine_version=ENGINE_VERSION, **kwargs)
    _expect_route(result, mode, reason, streamed=False)
    return _publish_resident(tmp_path, dict(result.outputs))


def _write_job(
    tmp_path: Path,
    tables: dict[str, pa.Table],
    columns: dict[str, list[dict[str, Any]]],
    relationships: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Path]]:
    """A pure-mask job over canary-bearing Parquet sources, with the given relationships."""
    paths = {n: tmp_path / f"{n}_in.parquet" for n in tables}
    for name, tbl in tables.items():
        pq.write_table(tbl, paths[name])
    cfg = validated(
        {
            "version": 2,
            "global_settings": {"seed": 7},
            "sources": {
                n: {"type": "file", "format": "parquet", "path": str(p)} for n, p in paths.items()
            },
            "tables": [{"name": n, "columns": columns[n]} for n in tables],
            "relationships": relationships,
            "targets": {
                n: {
                    "type": "file",
                    "format": "parquet",
                    "path": str(tmp_path / f"{n}_out.parquet"),
                }
                for n in tables
            },
        }
    )
    return cfg, paths


def _rel(parent: str, pcols: list[str], child: str, ccols: list[str]) -> dict[str, Any]:
    return {
        "parent": {"table": parent, "columns": pcols},
        "children": [{"table": child, "columns": ccols}],
        "orphan_policy": "preserve",
        "namespace": "ns",
    }


def _lazy(paths: dict[str, Path]) -> dict[str, Any]:
    return {n: LazySource(path=p) for n, p in paths.items()}


def _fk_job(
    tmp_path: Path, *, rows: int | None = None, extension: bool = False, declared: bool = False
) -> tuple[dict[str, Any], dict[str, Path]]:
    parent, child = fk_tables()
    if declared:
        child = child.append_column("start", pa.array(["2026-02-01"] * child.num_rows))
    if rows is not None:
        parent, child = parent.slice(0, rows), child.slice(0, rows)
    cfg = fk_config(tmp_path, parent, child)
    if declared:
        # fk_config already declared `start` as plain passthrough (it is in the source);
        # replace that entry with the typed one instead of listing the column twice.
        typed = {
            "name": "start",
            "strategy": "passthrough",
            "logical_type": "date",
            "parse_format": ISO_DATE,
            "error_policy": "null",
        }
        columns = cfg["tables"][1]["columns"]
        columns[:] = [typed if c["name"] == "start" else c for c in columns]
        cfg = validated(cfg)
    paths = {n: Path(cfg["sources"][n]["path"]) for n in ("parent", "child")}
    # fk_config wrote metadata-free sources; rewrite them with the canaries.
    pq.write_table(_canary(parent, extension_column="note" if extension else None), paths["parent"])
    pq.write_table(_canary(child), paths["child"])
    return cfg, paths


def _fk_route(
    mode: str,
    reason: str,
    *,
    ran: str | None = None,
    lazy: bool,
    sink: bool,
    rows: int | None = None,
    extension: bool = False,
    declared: bool = False,
) -> Route:
    def run(tmp_path: Path) -> list[Path]:
        cfg, paths = _fk_job(tmp_path, rows=rows, extension=extension, declared=declared)
        sources = _lazy(paths) if lazy else {n: pq.read_table(p) for n, p in paths.items()}
        runner = _sink_run if sink else _resident_run
        return runner(tmp_path, cfg, sources, ran or mode, reason, execution_mode=mode)

    return run


def _multi_parent_route(tmp_path: Path) -> list[Path]:
    keys = pa.array(["a", "b", "c", "d"])
    tables = {
        "p1": mc.canary_table({"k": keys, "n": pa.array([1, 2, 3, 4])}),
        "p2": mc.canary_table({"k": pa.array(["c", "d", "e", "f"]), "n": pa.array([1, 2, 3, 4])}),
        "x": mc.canary_table({"xid": pa.array(["1", "2", "3"]), "ref": pa.array(["a", "c", "e"])}),
    }
    columns = {
        "p1": [hash_col("k", "ns")],
        "p2": [hash_col("k", "ns")],
        "x": [hash_col("ref", "ns")],
    }
    cfg, paths = _write_job(
        tmp_path,
        tables,
        columns,
        [_rel("p1", ["k"], "x", ["ref"]), _rel("p2", ["k"], "x", ["ref"])],
    )
    return _sink_run(
        tmp_path,
        cfg,
        _lazy(paths),
        "out_of_core",
        "override_out_of_core",
        execution_mode="out_of_core",
    )


def _composite_route(tmp_path: Path) -> list[Path]:
    tables = {
        "r": mc.canary_table(
            {"a": pa.array(["a1", "a2", "a3"]), "b": pa.array(["b1", "b2", "b3"])}
        ),
        "c": mc.canary_table(
            {
                "cid": pa.array(["1", "2", "3"]),
                "ra": pa.array(["a1", "a2", "a3"]),
                "rb": pa.array(["b1", "b2", "b3"]),
            }
        ),
    }
    columns = {
        "r": [hash_col("a", "ns"), hash_col("b", "ns")],
        "c": [hash_col("ra", "ns"), hash_col("rb", "ns")],
    }
    cfg, paths = _write_job(tmp_path, tables, columns, [_rel("r", ["a", "b"], "c", ["ra", "rb"])])
    return _sink_run(
        tmp_path,
        cfg,
        _lazy(paths),
        "out_of_core",
        "override_out_of_core",
        execution_mode="out_of_core",
    )


def _single_job(tmp_path: Path, rows: int | None = None) -> tuple[dict[str, Any], Path]:
    base = base_table()
    if rows is not None:
        base = base.slice(0, rows)
    cfg = single_table_config(tmp_path, base, columns=[{"name": "grp", "strategy": "redact"}])
    path = Path(cfg["sources"]["t"]["path"])
    pq.write_table(_canary(base), path)
    return cfg, path


def _chunked_route() -> Route:
    """Auto-chunk dispatcher (native companion lane) into a sink: an all-string job, which is
    what the chunk-stable dtype gate admits."""

    def run(tmp_path: Path) -> list[Path]:
        n = 12
        base = pa.table({"s": [f"v{i}" for i in range(n)], "u": [f"w{i}" for i in range(n)]})
        cfg = single_table_config(tmp_path, base)
        path = Path(cfg["sources"]["t"]["path"])
        pq.write_table(_canary(base), path)
        return _sink_run(
            tmp_path,
            cfg,
            {"t": pq.read_table(path)},
            "full_frame",
            "no_relationships",
            auto_chunk=True,
            auto_chunk_threshold_rows=1,
            chunk_size_rows=4,
        )

    return run


def _transforms_route(tmp_path: Path) -> list[Path]:
    base = base_table()
    cfg = single_table_config(
        tmp_path,
        base,
        transforms=[{"op": "limit", "n": 4}],
        columns=[{"name": "grp", "strategy": "redact"}],
    )
    path = Path(cfg["sources"]["t"]["path"])
    pq.write_table(_canary(base), path)
    return _resident_run(
        tmp_path, cfg, {"t": pq.read_table(path)}, "full_frame", "no_relationships"
    )


def _generate_mask_route(tmp_path: Path) -> list[Path]:
    cfg, path = _single_job(tmp_path)
    cfg["tables"].append(
        {
            "name": "gen",
            "row_count": 5,
            "generate_columns": [{"name": "seq", "type": "sequence", "start": 1, "step": 1}],
        }
    )
    cfg["targets"]["gen"] = dict(cfg["targets"]["t"], path=str(tmp_path / "gen_out.parquet"))
    cfg = validated(cfg)
    return _resident_run(
        tmp_path, cfg, {"t": pq.read_table(path)}, "full_frame", "no_relationships"
    )


def _isolated_route(tmp_path: Path) -> list[Path]:
    cfg, path = _single_job(tmp_path)
    out = tmp_path / "isolated_out"
    result = run_pipeline_isolated(
        cfg, {"t": pq.read_table(path)}, engine_version=ENGINE_VERSION, output_dir=out
    )
    assert result.isolated is True
    assert result.outcome == "completed"
    assert result.committed_output_dir == str(out)
    return [out / "t.parquet"]


def _publish_unit_route(tmp_path: Path) -> list[Path]:
    child = pa.field("c", pa.string(), metadata={b"k": mc.NESTED.encode()})
    nested = pa.array([{"c": "v"}] * 2, pa.struct([child]))
    return _publish_resident(
        tmp_path, {"t": mc.canary_table({"a": pa.array(["x", "y"]), "st": nested})}
    )


def _extension_publish_route(tmp_path: Path) -> list[Path]:
    """Extension columns whose type parameters hold source text: an opaque type over struct
    storage (names and a child with field metadata) and a fixed-shape tensor (dimension names)."""
    child = pa.field("c", pa.int64(), metadata={b"k": mc.NESTED.encode()})
    opaque = pa.opaque(pa.struct([child]), mc.EXT, mc.EXT)
    tensor = pa.fixed_shape_tensor(pa.float64(), (2,), dim_names=[mc.EXT])
    base = mc.canary_table({"a": pa.array(["x", "y"])})
    ext_o = pa.ExtensionArray.from_storage(
        opaque, pa.array([{"c": 1}, {"c": 2}], opaque.storage_type)
    )
    ext_t = pa.ExtensionArray.from_storage(
        tensor, pa.array([[1.0, 2.0], [3.0, 4.0]], tensor.storage_type)
    )
    table = base.append_column("o", ext_o).append_column("t", ext_t)
    return _publish_resident(tmp_path, {"t": table})


def _subset_route(tmp_path: Path) -> list[Path]:
    from decoy_engine.subset import FanOutPolicy, SeedSpec, SubsetSource, run_subset
    from tests.unit.subset.conftest import JOB_SEED, rel

    tables = {
        "parent": mc.canary_table({"id": pa.array(["a", "b", "c"]), "n": pa.array([1, 2, 3])}),
        "child": mc.canary_table(
            {"cid": pa.array(["1", "2", "3"]), "pid": pa.array(["a", "b", "c"])}
        ),
    }
    paths = {n: str(tmp_path / f"{n}.parquet") for n in tables}
    for name, tbl in tables.items():
        pq.write_table(tbl, paths[name])
    out = tmp_path / "subset_out"
    result = run_subset(
        sources={n: SubsetSource(path=p, format="parquet") for n, p in paths.items()},
        relationships=(rel("parent", ("id",), "child", ("pid",)),),
        seeds=(SeedSpec(table="parent", mode="keys", key_columns=("id",), keys=(("b",),)),),
        policy=FanOutPolicy(),
        job_seed=JOB_SEED,
        engine_version=ENGINE_VERSION,
        output_dir=out,
    )
    assert {t for t, _ in result.output_paths} == {"parent", "child"}
    return [Path(p) for _, p in result.output_paths]


OOC = "override_out_of_core"
FULL = "override_full_frame"

# route id -> route. `stream` on lazy sources runs as the out-of-core route, and says so in its
# evidence.
ROUTES: dict[str, Route] = {
    "out_of_core_fk": _fk_route("out_of_core", OOC, lazy=True, sink=True),
    "full_frame": _fk_route("full_frame", FULL, lazy=False, sink=False),
    "sequential": _fk_route("sequential", "pure_mask_fk", lazy=False, sink=True),
    "stream_with_sink": _fk_route("stream", OOC, ran="out_of_core", lazy=True, sink=True),
    "auto_chunk_native": _chunked_route(),
    "resident_transforms": _transforms_route,
    "generate_and_mask": _generate_mask_route,
    "isolated": _isolated_route,
    "publish_unit": _publish_unit_route,
    "extension_full_frame": _fk_route("full_frame", FULL, lazy=False, sink=False, extension=True),
    "extension_out_of_core": _fk_route("out_of_core", OOC, lazy=True, sink=True, extension=True),
    "zero_rows_stream": _fk_route("stream", OOC, ran="out_of_core", lazy=True, sink=True, rows=0),
    "zero_rows_out_of_core": _fk_route("out_of_core", OOC, lazy=True, sink=True, rows=0),
    "declared_casting": _fk_route("out_of_core", OOC, lazy=True, sink=True, declared=True),
    "multi_parent_fk": _multi_parent_route,
    "composite_fk": _composite_route,
    "extension_types_publish": _extension_publish_route,
    "subset": _subset_route,
}


# The auto-chunk route needs the native companion; without it the dispatcher falls back to the
# resident route and the sink publishes nothing, so these cells run in the companion lane only.
COMPANION_ROUTES = {"auto_chunk_native"}


def _marks(route_id: str) -> list[Any]:
    return [NEEDS_COMPANION] if route_id in COMPANION_ROUTES else []


def _leaks(route_id: str, tmp_path: Path) -> set[str]:
    found: set[str] = set()
    for path in ROUTES[route_id](tmp_path):
        found |= mc.canaries_in(path)
    return found


@pytest.mark.parametrize("route_id", [pytest.param(r, id=r, marks=_marks(r)) for r in ROUTES])
def test_route_is_clean(route_id: str, tmp_path: Path) -> None:
    found = _leaks(route_id, tmp_path)
    if found:
        raise LeakFoundError(sorted(c.removeprefix("DCY-CANARY-") for c in found))


def _csv_write_calls(source: str) -> list[int]:
    import ast

    from tests.sentry._call_resolution import resolved_calls

    tree = ast.parse(source)
    return [c.lineno for name in ("write_csv", "to_csv") for c in resolved_calls(tree, name)]


def test_engine_has_no_csv_writer() -> None:
    """CE-10 standing guard: CSV targets are written by the CLI, never by the engine, so no
    engine route can put source Parquet metadata into a CSV file. Uses the repository's call
    resolver (import aliases, re-bindings, attribute calls)."""
    import decoy_engine

    root = Path(decoy_engine.__file__).parent
    hits = [
        f"{path.relative_to(root)}:{line}"
        for path in root.rglob("*.py")
        for line in _csv_write_calls(path.read_text(encoding="utf-8"))
    ]
    assert hits == []


@pytest.mark.parametrize(
    "source",
    [
        "import pyarrow.csv as pc\npc.write_csv(t, p)\n",
        "from pyarrow.csv import write_csv as w\nw(t, p)\n",
        "from pyarrow.csv import write_csv\nf = write_csv\nf(t, p)\n",
        "df.to_csv(p)\n",
    ],
)
def test_csv_guard_sees_every_spelling(source: str) -> None:
    assert _csv_write_calls(source)


# -- E2: tables the engine returns in memory carry no source schema metadata ----------------------

IN_MEMORY_CANARIES = (mc.SCHEMA, mc.ATTRS, mc.SKEY, mc.CREATOR, mc.PDVER, mc.RIDX, mc.COLIDX)


def _memory_leaks(table: pa.Table) -> set[str]:
    """Schema-level leaks of one returned table: a key other than `pandas`, or a canary in any
    key or value (the pandas blob included). Field metadata stays in memory by contract."""
    meta = table.schema.metadata or {}
    found = {f"key:{k!r}" for k in meta if k != b"pandas"}
    text = b"\n".join(k + v for k, v in meta.items())
    return found | {c for c in IN_MEMORY_CANARIES if c.encode() in text}


def _in_memory_tables(case: str, tmp_path: Path) -> dict[str, pa.Table]:
    if case == "degenerate_pin":
        from decoy_engine.execution._faker_degenerate_pin import pin_degenerate_to_string

        table = _canary(pa.table({"f": pa.array([None, None], pa.int64()), "g": ["a", "b"]}))
        return {"t": pin_degenerate_to_string(table, frozenset({"f"}))}
    if case == "resident_transforms":
        base = base_table()
        cfg = single_table_config(
            tmp_path,
            base,
            transforms=[{"op": "limit", "n": 4}],
            columns=[{"name": "grp", "strategy": "redact"}],
        )
        path = Path(cfg["sources"]["t"]["path"])
        pq.write_table(_canary(base), path)
        result = run_pipeline(cfg, {"t": pq.read_table(path)}, engine_version=ENGINE_VERSION)
        _expect_route(result, "full_frame", "no_relationships", streamed=False)
    else:
        cfg, paths = _fk_job(tmp_path)
        result = run_pipeline(
            cfg, _lazy(paths), engine_version=ENGINE_VERSION, execution_mode="out_of_core"
        )
        assert _exec(result)["execution_mode"] == "out_of_core", _exec(result)
    assert result.outputs, "the route returned no in-memory table"
    return dict(result.outputs)


@pytest.mark.parametrize("case", ["out_of_core_fk", "resident_transforms", "degenerate_pin"])
def test_in_memory(case: str, tmp_path: Path) -> None:
    for name, table in _in_memory_tables(case, tmp_path).items():
        assert _memory_leaks(table) == set(), name
