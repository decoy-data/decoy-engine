"""A mask handler must return the rows it was given (same count, same index labels and order).

Without the guard the gated write-back is index-aligned, so a dropped row becomes a null and the
run reports success; the plain path assigns whatever the handler returned. One helper
(`_gated_string_guard.require_same_rows`) is called from `run_with_when_gate` (plain and gated)
and from the composite dispatch, and the chunked route reaches the same adapter once per chunk.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine import run_mask_pipeline_chunked
from decoy_engine.config import PipelineConfig
from decoy_engine.execution import PandasExecutionAdapter
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution._gated_string_guard import require_same_rows
from decoy_engine.execution._when_gate import run_with_when_gate
from decoy_engine.relationships._namespace import NamespaceRegistry
from tests._declared_schema import declared_schema
from tests.unit.execution import _c8_iii_c_support as sup
from tests.unit.execution import _multi_table_support as mt

_CODE = "handler_row_count_changed"
_Mutate = Callable[[pd.DataFrame], pd.DataFrame]


def _drop_row(df: pd.DataFrame) -> pd.DataFrame:
    return df.iloc[:-1]


def _add_row(df: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([df, df.iloc[[0]]], ignore_index=False)


def _reverse(df: pd.DataFrame) -> pd.DataFrame:
    return df.iloc[::-1]


def _relabel(df: pd.DataFrame) -> pd.DataFrame:
    return df.set_axis(df.index + 100)


_BAD: dict[str, _Mutate] = {
    "drop": _drop_row,
    "add": _add_row,
    "reorder": _reverse,
    "relabel": _relabel,
}


class _Stub:
    """Runs the real handler, then applies `mutate` to its output frame."""

    def __init__(self, inner: Any, mutate: _Mutate) -> None:
        self._inner = inner
        self._mutate = mutate

    def run(self, df: pd.DataFrame, column: str, plan: Any, ctx: Any) -> Any:
        out, warns = self._inner.run(df, column, plan, ctx)
        return self._mutate(out), warns


def _col(when: str | None) -> dict[str, Any]:
    col: dict[str, Any] = {"name": "c", "strategy": "redact"}
    if when is not None:
        col["when"] = when
    return col


def _table() -> pa.Table:
    return pa.table(
        {"c": pa.array([f"secret{i}" for i in range(6)]), "x": pa.array(range(6), pa.int64())}
    )


def _adapter(mutate: _Mutate | None) -> PandasExecutionAdapter:
    adapter = PandasExecutionAdapter()
    if mutate is not None:
        adapter._handlers["redact"] = _Stub(adapter._handlers["redact"], mutate)  # type: ignore[assignment]
    return adapter


def _run(tmp_path: Path, mutate: _Mutate | None, when: str | None) -> pa.Table:
    cols = [_col(when), {"name": "x", "strategy": "passthrough"}]
    cfg, sources = mt.build_job(tmp_path, {"t": (cols, _table())})
    plan, graph, _ns, registry = sup.compile_job(cfg)
    out = _adapter(mutate).run(
        plan,
        sources,
        registry=registry,
        relationship_graph=graph,
        namespace_registry=NamespaceRegistry(bindings=()),
    )
    return out.outputs["t"]


def _run_chunked(tmp_path: Path, mutate: _Mutate | None) -> list[pa.Table]:
    cfg, _sources = mt.build_job(tmp_path, {"t": ([_col(None)], _table().select(["c"]))})
    dump = PipelineConfig.model_validate(cfg).model_dump()
    chunks = [_table().select(["c"]).slice(i, 3) for i in (0, 3)]
    return list(
        run_mask_pipeline_chunked(
            dump,
            chunks,
            table="t",
            source_schema=declared_schema(dump, "t"),
            engine_version="handler-row-count-test",
            adapter=_adapter(mutate),
        )
    )


@pytest.mark.parametrize("kind", sorted(_BAD))
class TestChangedRowsRefused:
    def test_plain_path(self, tmp_path: Path, kind: str) -> None:
        with pytest.raises(ExecutionError) as exc:
            _run(tmp_path, _BAD[kind], None)
        assert exc.value.code == _CODE
        assert "'c'" in str(exc.value) and "'redact'" in str(exc.value)
        assert "secret" not in str(exc.value)

    def test_when_gated_path(self, tmp_path: Path, kind: str) -> None:
        with pytest.raises(ExecutionError) as exc:
            _run(tmp_path, _BAD[kind], "x > 1")
        assert exc.value.code == _CODE

    def test_chunked_route(self, tmp_path: Path, kind: str) -> None:
        with pytest.raises(ExecutionError) as exc:
            _run_chunked(tmp_path, _BAD[kind])
        assert exc.value.code == _CODE


class TestCorrectHandlerUnchanged:
    def test_plain_and_gated_output_match_the_unwrapped_adapter(self, tmp_path: Path) -> None:
        for when in (None, "x > 1"):
            (tmp_path / "a").mkdir(exist_ok=True)
            (tmp_path / "b").mkdir(exist_ok=True)
            plain = _run(tmp_path / "a", None, when)
            wrapped = _run(tmp_path / "b", lambda df: df, when)
            assert plain.equals(wrapped)
            assert plain.num_rows == 6

    def test_chunked_passes(self, tmp_path: Path) -> None:
        out = _run_chunked(tmp_path, lambda df: df)
        assert sum(t.num_rows for t in out) == 6


class _CompositeStub:
    """Wraps the real composite handler and applies `mutate` to its output frame."""

    def __init__(self, inner: Any, mutate: _Mutate) -> None:
        self._inner = inner
        self._mutate = mutate

    def run(self, df: pd.DataFrame, node: Any, ctx: Any) -> Any:
        out, warns = self._inner.run(df, node, ctx)
        return self._mutate(out), warns


def _composite_run(tmp_path: Path, mutate: _Mutate | None) -> pa.Table:
    def col(name: str, others: list[str]) -> dict[str, Any]:
        return {
            "name": name,
            "strategy": "faker",
            "provider": "composite_name_email",
            "deterministic": True,
            "namespace": "ne",
            "coherent_with": others,
            "cardinality_mode": "reuse",
            "provider_config": {"pool_size": 20},
        }

    names = ("first_name", "last_name", "email")
    cols = [col(n, [o for o in names if o != n]) for n in names]
    table = pa.table(
        {
            "first_name": pa.array([f"F{i}" for i in range(6)]),
            "last_name": pa.array([f"L{i}" for i in range(6)]),
            "email": pa.array([f"e{i}@x.com" for i in range(6)]),
        }
    )
    cfg, sources = mt.build_job(tmp_path, {"t": (cols, table)})
    plan, graph, ns, registry = sup.compile_job(cfg)
    adapter = PandasExecutionAdapter()
    if mutate is not None:
        adapter._composite_handler = _CompositeStub(adapter._composite_handler, mutate)  # type: ignore[assignment]
    out = adapter.run(
        plan,
        sources,
        registry=registry,
        relationship_graph=graph,
        namespace_registry=ns,
    )
    return out.outputs["t"]


class TestCompositeRoute:
    def test_correct_composite_passes(self, tmp_path: Path) -> None:
        assert _composite_run(tmp_path, None).num_rows == 6
        (tmp_path / "w").mkdir()
        assert _composite_run(tmp_path / "w", lambda df: df).num_rows == 6

    @pytest.mark.parametrize("kind", ["drop", "reorder"])
    def test_changed_rows_refused(self, tmp_path: Path, kind: str) -> None:
        with pytest.raises(ExecutionError) as exc:
            _composite_run(tmp_path, _BAD[kind])
        assert exc.value.code == _CODE
        assert "table 't'" in str(exc.value)


class _EchoHandler:
    def __init__(self, mutate: _Mutate) -> None:
        self._mutate = mutate

    def run(self, df: pd.DataFrame, column: str, plan: Any, ctx: Any) -> Any:
        return self._mutate(df), []


class TestNonZeroStartIndex:
    """A chunk sliced from a larger frame keeps its labels (here 1000..1002)."""

    @staticmethod
    def _call(mutate: _Mutate) -> pd.DataFrame:
        df = pd.DataFrame({"c": ["a", "b", "c"]}, index=[1000, 1001, 1002])
        plan = SimpleNamespace(when=None, strategy="redact")
        ctx = SimpleNamespace(current_table="t")
        out, _ = run_with_when_gate(_EchoHandler(mutate), df, "c", plan, ctx)  # type: ignore[arg-type]
        return out

    def test_correct_handler_passes(self) -> None:
        assert list(self._call(lambda df: df).index) == [1000, 1001, 1002]

    def test_dropping_handler_refused(self) -> None:
        with pytest.raises(ExecutionError) as exc:
            self._call(_drop_row)
        assert exc.value.code == _CODE

    def test_handler_that_resets_index_refused(self) -> None:
        with pytest.raises(ExecutionError) as exc:
            self._call(lambda df: df.reset_index(drop=True))
        assert exc.value.code == _CODE


class TestHelper:
    def test_counts_only_in_message(self) -> None:
        before = pd.RangeIndex(3)
        with pytest.raises(ExecutionError) as exc:
            require_same_rows(before, pd.DataFrame({"c": ["a"]}), column="c", strategy="s")
        assert "returned 1 rows for 3 given" in str(exc.value)

    def test_same_count_other_labels_named_as_index_change(self) -> None:
        before = pd.RangeIndex(2)
        after = pd.DataFrame({"c": ["a", "b"]}, index=[5, 6])
        with pytest.raises(ExecutionError) as exc:
            require_same_rows(before, after, column="c", strategy="s")
        assert "index labels or order" in str(exc.value)
