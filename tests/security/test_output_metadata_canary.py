"""OUTPUT-METADATA-LEAK E0: a canary placed in every source metadata carrier must not reach any
published output Parquet file, on any route.

Each cell publishes through the entry named in the plan (a `ParquetTransactionalSink`,
`publish_tables`, the isolated commit, or `run_subset`) and reads the file that entry committed.
A cell that is red on the base carries a strict xfail naming the canaries it leaks, so it fails the
suite the moment it turns green without the marker being removed (E1 removes them).
"""

from __future__ import annotations

import time
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
from tests.native._chunked_entry_support import NEEDS_COMPANION
from tests.security import _metadata_canary as mc
from tests.unit.execution._transform_testkit import (
    base_table,
    fk_config,
    fk_tables,
    single_table_config,
    validated,
)

ENGINE_VERSION = "metadata-canary-test"

Route = Callable[[Path], list[Path]]


def _canary(table: pa.Table, **kwargs: Any) -> pa.Table:
    return mc.canary_table({n: table[n].combine_chunks() for n in table.column_names}, **kwargs)


def _fk_job(
    tmp_path: Path, *, rows: int | None = None, extension: bool = False
) -> tuple[dict[str, Any], dict[str, Path]]:
    parent, child = fk_tables()
    if rows is not None:
        parent, child = parent.slice(0, rows), child.slice(0, rows)
    cfg = fk_config(tmp_path, parent, child)
    paths = {n: Path(cfg["sources"][n]["path"]) for n in ("parent", "child")}
    # fk_config wrote metadata-free sources; rewrite them with the canaries.
    pq.write_table(_canary(parent, extension_column="note" if extension else None), paths["parent"])
    pq.write_table(_canary(child), paths["child"])
    return cfg, paths


def _sink_run(tmp_path: Path, cfg: dict[str, Any], sources: Any, **kwargs: Any) -> list[Path]:
    sink = ParquetTransactionalSink(tmp_path / "published")
    run_pipeline(cfg, sources, engine_version=ENGINE_VERSION, sink=sink, **kwargs)
    return [sink.committed_table_path(n) for n in cfg["targets"]]


def _publish_resident(tmp_path: Path, outputs: dict[str, pa.Table]) -> list[Path]:
    """Publish resident results the way the engine's resident publisher does (F22)."""
    from decoy_engine import fileaccess
    from decoy_engine.fileaccess import FileRequest, FileRole
    from decoy_engine.publication import PublicationRequest
    from decoy_engine.publication._publish import publish_tables

    out = fileaccess.capture().output_dir(
        FileRequest(FileRole.TARGET_OUTPUT, "write", str(tmp_path / "pub"), "targets.path")
    )
    publish_tables(out, outputs, PublicationRequest(uuid.uuid4().hex), suffix=".parquet")
    return [tmp_path / "pub" / f"{n}.parquet" for n in outputs]


def _resident_run(tmp_path: Path, cfg: dict[str, Any], sources: Any, **kwargs: Any) -> list[Path]:
    """A resident route returns tables in memory; the sink is inert for it, so the results are
    published through `publish_tables`."""
    result = run_pipeline(cfg, sources, engine_version=ENGINE_VERSION, **kwargs)
    return _publish_resident(tmp_path, dict(result.outputs))


def _fk_route(
    mode: str, *, lazy: bool, sink: bool, rows: int | None = None, extension: bool = False
) -> Route:
    def run(tmp_path: Path) -> list[Path]:
        cfg, paths = _fk_job(tmp_path, rows=rows, extension=extension)
        if lazy:
            sources: Any = {n: LazySource(path=p) for n, p in paths.items()}
        else:
            sources = {n: pq.read_table(p) for n, p in paths.items()}
        runner = _sink_run if sink else _resident_run
        return runner(tmp_path, cfg, sources, execution_mode=mode)

    return run


def _single_job(
    tmp_path: Path, rows: int | None = None, **canary: Any
) -> tuple[dict[str, Any], Path]:
    base = base_table()
    if rows is not None:
        base = base.slice(0, rows)
    cfg = single_table_config(tmp_path, base, columns=[{"name": "grp", "strategy": "redact"}])
    path = Path(cfg["sources"]["t"]["path"])
    pq.write_table(_canary(base, **canary), path)
    return cfg, path


def _chunked_route(*, rows: int | None = None) -> Route:
    """Auto-chunk dispatcher (native companion lane) into a sink."""

    def run(tmp_path: Path) -> list[Path]:
        cfg, path = _single_job(tmp_path, rows)
        return _sink_run(
            tmp_path,
            cfg,
            {"t": LazySource(path=path)},
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
    return _resident_run(tmp_path, cfg, {"t": pq.read_table(path)})


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
    return _resident_run(tmp_path, cfg, {"t": pq.read_table(path)})


def _isolated_route(tmp_path: Path) -> list[Path]:
    cfg, path = _single_job(tmp_path)
    out = tmp_path / "isolated_out"
    result = run_pipeline_isolated(
        cfg, {"t": pq.read_table(path)}, engine_version=ENGINE_VERSION, output_dir=out
    )
    assert result.committed_output_dir == str(out)
    return [out / "t.parquet"]


def _publish_unit_route(tmp_path: Path) -> list[Path]:
    child = pa.field("c", pa.string(), metadata={b"k": mc.NESTED.encode()})
    nested = pa.array([{"c": "v"}] * 2, pa.struct([child]))
    return _publish_resident(
        tmp_path, {"t": mc.canary_table({"a": pa.array(["x", "y"]), "st": nested})}
    )


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
    run_subset(
        sources={n: SubsetSource(path=p, format="parquet") for n, p in paths.items()},
        relationships=(rel("parent", ("id",), "child", ("pid",)),),
        seeds=(SeedSpec(table="parent", mode="keys", key_columns=("id",), keys=(("b",),)),),
        policy=FanOutPolicy(),
        job_seed=JOB_SEED,
        engine_version=ENGINE_VERSION,
        output_dir=out,
    )
    return [out / "parent.parquet", out / "child.parquet"]


# route id -> (route, the canaries it leaks on the base, or None when it is green on the base).
# The second element is filled from the E0 matrix run; see docs/records for the full table.
ROUTES: dict[str, tuple[Route, str | None]] = {
    "out_of_core_fk": (
        _fk_route("out_of_core", lazy=True, sink=True),
        "ATTRS, COLIDX, CREATOR, PDVER, RIDX, SCHEMA, SKEY",
    ),
    "full_frame": (_fk_route("full_frame", lazy=False, sink=False), "ATTRS"),
    "sequential": (_fk_route("sequential", lazy=False, sink=True), "ATTRS"),
    "stream_with_sink": (
        _fk_route("stream", lazy=True, sink=True),
        "ATTRS, COLIDX, CREATOR, PDVER, RIDX, SCHEMA, SKEY",
    ),
    "auto_chunk_native": (_chunked_route(), None),
    "resident_transforms": (_transforms_route, "ATTRS"),
    "generate_and_mask": (_generate_mask_route, "ATTRS"),
    "isolated": (_isolated_route, "ATTRS"),
    "publish_unit": (
        _publish_unit_route,
        "ATTRS, COLIDX, CREATOR, FIELD, FKEY, NESTED, PDVER, RIDX, SCHEMA, SKEY",
    ),
    "extension_full_frame": (
        _fk_route("full_frame", lazy=False, sink=False, extension=True),
        "ATTRS",
    ),
    "extension_out_of_core": (
        _fk_route("out_of_core", lazy=True, sink=True, extension=True),
        "ATTRS, COLIDX, CREATOR, PDVER, RIDX, SCHEMA, SKEY",
    ),
    "zero_rows_out_of_core": (
        _fk_route("out_of_core", lazy=True, sink=True, rows=0),
        "ATTRS, COLIDX, CREATOR, PDVER, RIDX, SCHEMA, SKEY",
    ),
    "zero_rows_chunked": (_chunked_route(rows=0), None),
    "subset": (_subset_route, None),
}


# The auto-chunk route needs the native companion; without it the dispatcher falls back to the
# resident route and the sink publishes nothing, so these cells run in the companion lane only.
COMPANION_ROUTES = {"auto_chunk_native", "zero_rows_chunked"}


def _param(route_id: str) -> Any:
    leaks = ROUTES[route_id][1]
    marks = [NEEDS_COMPANION] if route_id in COMPANION_ROUTES else []
    if leaks is not None:
        marks.append(pytest.mark.xfail(strict=True, reason=f"OUTPUT-METADATA-LEAK: {leaks}"))
    return pytest.param(route_id, id=route_id, marks=marks)


@pytest.mark.parametrize("route_id", [_param(r) for r in ROUTES])
def test_route(route_id: str, tmp_path: Path) -> None:
    run_start = time.time() - 1
    outputs = ROUTES[route_id][0](tmp_path)
    assert outputs
    sources = {p for p in tmp_path.glob("*.parquet")}
    for path in outputs:
        mc.assert_engine_wrote(path, run_start, not_written_by_test=sources)
        found = mc.canaries_in(path)
        assert not found, f"{path.name}: {sorted(c.removeprefix('DCY-CANARY-') for c in found)}"


def test_engine_has_no_csv_writer() -> None:
    """CE-10 standing guard: CSV targets are written by the CLI, never by the engine, so no
    engine route can put source Parquet metadata into a CSV file."""
    import ast

    import decoy_engine

    root = Path(decoy_engine.__file__).parent
    hits = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in {"write_csv", "to_csv"}:
                hits.append(f"{path.relative_to(root)}:{node.lineno}")
    assert hits == []
