"""G6-1: the temp-disk cap measures the directory the run spills under."""

from __future__ import annotations

import shutil
import sys
import tempfile
from collections import namedtuple
from contextlib import ExitStack
from pathlib import Path

import pyarrow as pa
import pytest

from decoy_engine.execution import _pipeline_route_exec as route_exec
from decoy_engine.execution import out_of_core as ooc_pkg
from decoy_engine.execution._pipeline_route_exec import resolve_temp_disk_budget
from decoy_engine.relationships._graph import OrphanPolicy, RelationshipEdge, RelationshipGraph

_Usage = namedtuple("_Usage", "total used free")


class _ReachedError(Exception):
    pass


@pytest.fixture
def measured(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []

    def usage(path: object) -> _Usage:
        calls.append(Path(str(path)))
        return _Usage(100, 0, 1000)

    monkeypatch.setattr(shutil, "disk_usage", usage)
    return calls


def test_budget_measures_arena_parent(tmp_path: Path, measured: list[Path]) -> None:
    assert resolve_temp_disk_budget(tmp_path) == 900
    assert measured == [tmp_path]


def test_budget_is_none_when_disk_usage_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(path: object) -> None:
        raise OSError("no")

    monkeypatch.setattr(shutil, "disk_usage", boom)
    assert resolve_temp_disk_budget(tmp_path) is None


def test_route_budget_follows_temp_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, measured: list[Path]
) -> None:
    # The route spills under the one scratch root, so a moved root moves the measured path.
    other = tmp_path / "other-root"
    other.mkdir()
    monkeypatch.setenv("TMPDIR", str(other))
    # The stdlib cache names another directory; the selected variable still wins.
    cached = tmp_path / "cached"
    cached.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(cached))
    seen: dict[str, object] = {}

    def spy(*args: object, **kwargs: object) -> None:
        seen.update(kwargs)
        raise _ReachedError

    monkeypatch.setattr(ooc_pkg, "run_fk_out_of_core", spy)
    edge = RelationshipEdge(
        parent_table="parent",
        parent_columns=("id",),
        child_table="child",
        child_columns=("parent_id",),
        namespace="ns",
        orphan_policy=OrphanPolicy.PRESERVE,
    )
    with pytest.raises(_ReachedError):
        route_exec.run_out_of_core_route(
            config={},
            plan=object(),  # type: ignore[arg-type]
            sources={"parent": pa.table({"id": ["a"]}), "child": pa.table({"parent_id": ["a"]})},
            registry=object(),  # type: ignore[arg-type]
            graph=RelationshipGraph(edges=(edge,), ordering=()),
            sink=None,
            route_reason="test",
            table_kinds={},
            source_loader=None,
            sources_resident=True,
            budget_bytes=512 * 1024 * 1024,
        )
    assert measured == [other]
    assert seen["temp_disk_budget_bytes"] == 900


@pytest.mark.skipif(sys.platform == "win32", reason="ScratchArena.fresh() is POSIX-only until S1w")
@pytest.mark.parametrize("supplied", [False, True])
def test_direct_runner_call_measures_the_arena_itself(
    tmp_path: Path, measured: list[Path], monkeypatch: pytest.MonkeyPatch, supplied: bool
) -> None:
    from decoy_engine.execution._errors import ExecutionError
    from decoy_engine.execution.out_of_core import run_fk_out_of_core
    from decoy_engine.fileaccess import ScratchArena
    from tests.unit.execution.test_pipeline_route_exec_ooc_memory_preflight import (
        _edge,
        _graph,
        _tiny_plan,
        _tiny_registry,
    )

    monkeypatch.setattr(
        shutil, "disk_usage", lambda path: (measured.append(Path(str(path))), _Usage(1, 1, 1))[1]
    )
    where = tmp_path / "explicit"
    where.mkdir()
    extra: dict[str, object] = {"temp_dir": where}
    arena = None
    with ExitStack() as stack:
        if supplied:
            # An adopted or private mount point: its parent may be on another device.
            arena = stack.enter_context(ScratchArena.fresh(under=where))
            extra = {"_arena": arena}
        with pytest.raises(ExecutionError):
            run_fk_out_of_core(
                _tiny_plan(),
                {
                    "parent": pa.table({"id": ["p1", "p2"]}),
                    "child": pa.table({"parent_id": ["p1"]}),
                },
                registry=_tiny_registry(),
                relationship_graph=_graph(_edge("parent", "child")),
                config={},
                **extra,  # type: ignore[arg-type]
            )
        assert len(measured) == 1 and measured[0] != where
        assert measured[0].parent == where, "the arena root, not its parent"
        if arena is not None:
            assert measured[0] == Path(arena.local_path())
