"""One whole-table contract decides what a transactional writer is, on every route.

A callable object that carries only a `.write` attribute is a plain callable: sequential
execution and resident delivery both hand it every table through the call, not through `.write`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.execution import run_pipeline
from decoy_engine.execution._transactional_sink import has_whole_table_contract
from tests._declared_schema import declare_rest
from tests.acceptance._f06_support import column, text_table


class _WriteOnlyCallable:
    """Callable with a `.write` attribute and no commit or abort."""

    def __init__(self) -> None:
        self.received: list[str] = []

    def __call__(self, table: str, data: pa.Table) -> None:
        self.received.append(table)

    def write(self, table: str, data: pa.Table) -> None:  # pragma: no cover - must not be used
        raise AssertionError("a write-only callable is a plain callable")


def test_write_only_callable_is_not_a_whole_table_sink() -> None:
    assert not has_whole_table_contract(_WriteOnlyCallable())


def _two_table_job(tmp_path: Path) -> tuple[dict[str, Any], dict[str, pa.Table]]:
    parent = text_table(id=["1", "2"], v=["a", "b"])
    child = text_table(cid=["x", "y"], pid=["1", "2"])
    sources: dict[str, Any] = {}
    targets: dict[str, Any] = {}
    for name, data in (("parent", parent), ("child", child)):
        path = str(tmp_path / f"{name}.parquet")
        pq.write_table(data, path)
        sources[name] = {"type": "file", "format": "parquet", "path": path}
        targets[name] = {"type": "file", "format": "parquet", "path": path + ".out"}
    raw = {
        "version": 2,
        "global_settings": {"seed": 7},
        "sources": sources,
        "tables": [
            {"name": "parent", "columns": [column("id", "hash", namespace="ns"), column("v")]},
            {"name": "child", "columns": [column("cid"), column("pid", "hash", namespace="ns")]},
        ],
        "targets": targets,
        "relationships": [
            {
                "parent": {"table": "parent", "columns": ["id"]},
                "children": [{"table": "child", "columns": ["pid"]}],
                "orphan_policy": "fail",
                "namespace": "ns",
            }
        ],
        "namespaces": {},
    }
    return declare_rest(raw), {"parent": parent, "child": child}


@pytest.mark.parametrize("mode", ["full_frame", "sequential"])
def test_a_write_only_callable_receives_every_table_on_both_routes(
    tmp_path: Path, mode: str
) -> None:
    cfg, tables = _two_table_job(tmp_path)
    sink = _WriteOnlyCallable()
    run_pipeline(
        cfg,
        tables,
        engine_version="probe",
        sink=sink,  # type: ignore[arg-type]
        execution_mode=mode,  # type: ignore[arg-type]
    )
    assert sorted(sink.received) == ["child", "parent"]
