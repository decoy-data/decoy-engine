"""CODE-SET-NATIVE S1: bounded per-distinct memo in ``CodeSetHandler.run``.

Plan: ``docs/plans/2026-11-22-code-set-native.md`` (rev 7). AT-1 (parity),
AT-2 (call counts), AT-5 (memory bound) and AT-6 (caps). ``_base_run`` is an
in-test copy of the pre-memo handler loop; the handler must match it value for
value, row error for row error, under and over the caps.
"""

from __future__ import annotations

import contextlib
import pathlib
import sys
import tracemalloc
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._strategies import _code_set as csm
from decoy_engine.execution._strategies._code_set import CodeSetHandler
from decoy_engine.generation.pool._cache import PoolCache
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.relationships._graph import RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceRegistry

_SEED = (0x77).to_bytes(8, "big")


def _ctx() -> StrategyContext:
    return StrategyContext(
        registry=None,  # type: ignore[arg-type]
        pool_cache=PoolCache(),
        relationship_graph=RelationshipGraph(edges=(), ordering=()),
        namespace_registry=NamespaceRegistry(bindings=()),
        job_seed=_SEED,
    )


def _seed(cfg: dict[str, Any], namespace: str | None = "cs") -> ColumnSeed:
    return ColumnSeed(
        namespace=namespace,
        strategy="code_set",
        provider="code_set",
        backend_type="faker",
        backend_version="v",
        cardinality_mode="reuse",
        deterministic=False,
        provider_config=tuple(cfg.items()),
        coherent_with=(),
    )


def _base_run(df: pd.DataFrame, column: str, plan: ColumnSeed, ctx: StrategyContext) -> Any:
    """The handler loop as it was before the memo (one scalar call per row)."""
    cfg = csm.provider_config_to_dict(plan.provider_config)
    mode = str(cfg.get("mode", "mask"))
    code_cfg = csm.CodeSetConfig.from_dict(cfg)
    if mode == "gen" and plan.namespace is None:
        raise csm.StrategyError(
            code=csm.reasons.runtime.CODE_SET_GEN_REQUIRES_NAMESPACE,
            strategy="code_set",
            message=(
                f"column {column!r} uses code_set gen mode but has no namespace. "
                "Set namespace on the ColumnSeed so gen-mode columns are "
                "decorrelated across namespaces via derive_index."
            ),
        )
    record_key = (ctx.current_table, ctx.nested_outer_column or column)
    record = ctx.code_set_records.get(record_key)
    if record is None:
        record = csm.resolve_corpus_record(code_cfg)
        ctx.code_set_records[record_key] = record
    evidence = csm.describe_loaded_corpus(code_cfg, record=record)
    source = df[column]
    na_mask = source.isna().to_numpy()
    out: list[object] = []
    masked_any = False
    for i, value in enumerate(source):
        if na_mask[i]:
            out.append(None)
            continue
        try:
            result = csm.apply_code_set(
                str(value),
                code_cfg,
                mode=mode,
                job_seed=ctx.mask_key,
                row_index=i,
                namespace=plan.namespace,
                corpus_record=record,
            )
        except csm.PlanCompileError as exc:
            if exc.code not in csm._PER_VALUE_CODE_SET_ERRORS:
                raise
            ctx.row_errors.append(
                csm.RowError(
                    column=column,
                    row_index=i,
                    trigger="mask_error",
                    reason=f"code_set could not mask this value ({exc.code})",
                )
            )
            out.append(value)
            continue
        out.append(result)
        masked_any = True
    if masked_any:
        ec = ctx.nested_outer_column or column
        ctx.code_set_corpora[(ctx.current_table, ec)] = {
            **evidence,
            "table": ctx.current_table,
            "column": ec,
        }
    if out:
        df[column] = out
    else:
        df[column] = pd.array([], dtype="string")
    return df, []


def _snapshot(fn: Any, df: pd.DataFrame, plan: ColumnSeed) -> tuple:
    ctx = _ctx()
    work = df.copy(deep=True)

    def errs() -> list[tuple]:
        return [(e.column, e.row_index, e.trigger, e.reason) for e in ctx.row_errors]

    try:
        out_df, _ = fn(work, "c", plan, ctx)
    except Exception as exc:
        return ("raise", type(exc).__name__, getattr(exc, "code", None), str(exc), errs())
    col = out_df["c"]
    cells = [(type(v).__name__, repr(v)) for v in col]
    try:
        schema = str(pa.Table.from_pandas(out_df[["c"]]).schema)
    except Exception as exc:  # the base conversion may raise on mixed objects
        schema = f"raises {type(exc).__name__}"
    return ("ok", cells, str(col.dtype), schema, dict(ctx.code_set_corpora), errs())


def _customer_corpus(tmp_path: pathlib.Path) -> str:
    path = tmp_path / "ab.parquet"
    pq.write_table(
        pa.table(
            {
                "code": pa.array(["A01", "A02", "B01", "B02"], type=pa.string()),
                "chapter": pa.array(["A", "A", "B", "B"], type=pa.string()),
            }
        ),
        str(path),
    )
    return f"customer:{path}"


_OPTION_SETS = [
    pytest.param({}, id="default"),
    pytest.param({"mode.string_storage": "pyarrow"}, id="pyarrow-storage"),
    pytest.param({"future.infer_string": True}, id="infer-string"),
]


def _option_context(opts: dict[str, Any]) -> Any:
    if not opts:
        return contextlib.nullcontext()
    flat: list[Any] = []
    for k, v in opts.items():
        flat += [k, v]
    try:
        return pd.option_context(*flat)
    except Exception:
        pytest.skip("pandas option unavailable")


_MIXED = ["1", 1, 1.0, True, None, float("nan"), pd.NA, "\ud800", "I10", "E11.9"]
_COLUMNS: dict[str, pd.Series] = {
    "mixed-object": pd.Series(_MIXED + _MIXED[::-1], dtype=object),
    "text": pd.Series(["I10", "E11.9", None, "I10", "J45", "E11.9", "I10"], dtype=object),
    "float": pd.Series([1.5, 2.5, None, 1.5, 2.5, 1.5], dtype="float64"),
    "int64-na": pd.Series([1, None, 2, 1, 2, None], dtype="Int64"),
    "boolean": pd.Series([True, None, False, True, False], dtype="boolean"),
    "category": pd.Series(["I10", "E11.9", None, "I10"], dtype="category"),
    "datetime": pd.Series(pd.to_datetime(["2024-01-01", None, "2024-01-01", "2024-02-02"])),
    "all-null": pd.Series([None, None, None], dtype=object),
    "zero-rows": pd.Series([], dtype=object),
}


class TestAt1Parity:
    @pytest.mark.parametrize("opts", _OPTION_SETS)
    @pytest.mark.parametrize("name", list(_COLUMNS))
    @pytest.mark.parametrize("corpus", ["icd10", "mcc"])
    @pytest.mark.parametrize("namespace", ["cs", "other", None])
    @pytest.mark.parametrize("mode", ["mask", "gen"])
    def test_handler_equals_base_loop(
        self, opts: dict, name: str, corpus: str, namespace: str | None, mode: str
    ) -> None:
        plan = _seed({"code_set": corpus, "mode": mode}, namespace)
        df = pd.DataFrame({"c": _COLUMNS[name]})
        with _option_context(opts):
            base = _snapshot(_base_run, df, plan)
            new = _snapshot(CodeSetHandler().run, df, plan)
        assert new == base

    @pytest.mark.parametrize("opts", _OPTION_SETS)
    def test_chapter_preserve_failures_interleaved(
        self, tmp_path: pathlib.Path, opts: dict
    ) -> None:
        plan = _seed(
            {
                "code_set": "ab",
                "mode": "mask",
                "chapter_preserve": True,
                "corpus_source": _customer_corpus(tmp_path),
            }
        )
        # `1` and "1" share a string form, fail on the same absent chapter,
        # and keep their own original objects (M2).
        vals = ["A01", "U07", 1, "1", "B01", "U07", "A01", 1, None, "1", "B02", "A02"]
        df = pd.DataFrame({"c": pd.Series(vals, dtype=object)})
        with _option_context(opts):
            base = _snapshot(_base_run, df, plan)
            new = _snapshot(CodeSetHandler().run, df, plan)
        assert new == base

    def test_two_calls_two_namespaces_two_corpora(self, tmp_path: pathlib.Path) -> None:
        # M3: a module-level memo would leak the first call's codes.
        df = pd.DataFrame({"c": pd.Series(["A01", "B01", "A01"], dtype=object)})
        p1 = _seed({"code_set": "icd10", "mode": "mask"}, "ns1")
        p2 = _seed(
            {"code_set": "ab", "mode": "mask", "corpus_source": _customer_corpus(tmp_path)},
            "ns2",
        )
        for plan in (p1, p2, p1, p2):
            assert _snapshot(CodeSetHandler().run, df, plan) == _snapshot(_base_run, df, plan)

    def test_chunks_that_split_repeats_equal_one_call(self) -> None:
        plan = _seed({"code_set": "icd10", "mode": "mask"})
        vals = ["I10", "E11.9", "I10", None, "J45", "E11.9", "I10", "J45"]
        whole, _ = CodeSetHandler().run(
            pd.DataFrame({"c": pd.Series(vals, dtype=object)}), "c", plan, _ctx()
        )
        parts = []
        for chunk in (vals[:3], vals[3:]):
            out, _ = CodeSetHandler().run(
                pd.DataFrame({"c": pd.Series(chunk, dtype=object)}), "c", plan, _ctx()
            )
            parts.append(out["c"])
        assert list(pd.concat(parts, ignore_index=True)) == list(whole["c"])


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    real = csm.apply_code_set

    def spy(value: str, *a: Any, **kw: Any) -> Any:
        seen.append(value)
        return real(value, *a, **kw)

    monkeypatch.setattr(csm, "apply_code_set", spy)
    return seen


class TestAt2CallCounts:
    def test_one_call_per_distinct_in_first_occurrence_order(self, calls: list[str]) -> None:
        plan = _seed({"code_set": "icd10", "mode": "mask"})
        vals = ["I10", "E11.9", "I10", None, 1, "1", "E11.9", 1.0, "I10"]
        CodeSetHandler().run(pd.DataFrame({"c": pd.Series(vals, dtype=object)}), "c", plan, _ctx())
        assert calls == ["I10", "E11.9", "1", "1.0"]

    def test_zero_rows_and_all_missing_make_no_calls(self, calls: list[str]) -> None:
        plan = _seed({"code_set": "icd10", "mode": "mask"})
        for vals in ([], [None, None]):
            CodeSetHandler().run(
                pd.DataFrame({"c": pd.Series(vals, dtype=object)}), "c", plan, _ctx()
            )
        assert calls == []

    def test_gen_mode_keeps_one_call_per_row(self, calls: list[str]) -> None:
        plan = _seed({"code_set": "icd10", "mode": "gen"})
        CodeSetHandler().run(
            pd.DataFrame({"c": pd.Series(["I10", "I10", None, "I10"], dtype=object)}),
            "c",
            plan,
            _ctx(),
        )
        assert len(calls) == 3

    def test_lone_surrogate_namespace_all_missing_succeeds(self, calls: list[str]) -> None:
        plan = _seed({"code_set": "icd10", "mode": "mask"}, "\ud800")
        CodeSetHandler().run(
            pd.DataFrame({"c": pd.Series([None, None], dtype=object)}), "c", plan, _ctx()
        )
        assert calls == []

    def test_fatal_precedence_same_row_errors_before_raise(self, tmp_path: pathlib.Path) -> None:
        plan = _seed(
            {
                "code_set": "ab",
                "mode": "mask",
                "chapter_preserve": True,
                "corpus_source": _customer_corpus(tmp_path),
            },
            "\ud800",
        )
        df = pd.DataFrame({"c": pd.Series(["U07", "A01", "U07"], dtype=object)})
        assert _snapshot(CodeSetHandler().run, df, plan) == _snapshot(_base_run, df, plan)


def _peak(fn: Any, make_df: Any, plan: ColumnSeed) -> tuple[int, list]:
    df = make_df()
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        out_df, _ = fn(df, "c", plan, _ctx())
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak, list(out_df["c"])


class TestAt5MemoryBound:
    def test_many_large_distinct_keys_stay_under_cap(self) -> None:
        plan = _seed({"code_set": "icd10", "mode": "mask", "chapter_preserve": False})

        def make() -> pd.DataFrame:
            cells = [f"{i:08d}".encode() + b"x" * 4088 for i in range(24_000)]
            return pd.DataFrame({"c": pd.Series(cells, dtype=object)})

        base_peak, base_out = _peak(_base_run, make, plan)
        new_peak, new_out = _peak(CodeSetHandler().run, make, plan)
        assert new_out == base_out
        assert new_peak - base_peak <= csm._MEMO_MAX_KEY_BYTES + 2 * 1024 * 1024

    def test_zero_entry_memo_does_not_hold_two_keys(self) -> None:
        plan = _seed({"code_set": "icd10", "mode": "mask", "chapter_preserve": False})
        mib16 = 16 * 1024 * 1024

        def make() -> pd.DataFrame:
            return pd.DataFrame({"c": pd.Series([["A" * mib16], ["B" * mib16]], dtype=object)})

        base_peak, base_out = _peak(_base_run, make, plan)
        new_peak, new_out = _peak(CodeSetHandler().run, make, plan)
        assert new_out == base_out
        assert new_peak - base_peak <= 1024 * 1024


class TestAt6Caps:
    # a, c valid (chapters A, B), b a per-value failure (absent chapter U), equal length.
    A, B, C, D = "A01", "U07", "B01", "A02"

    @pytest.fixture
    def plan(self, tmp_path: pathlib.Path) -> ColumnSeed:
        return _seed(
            {
                "code_set": "ab",
                "mode": "mask",
                "chapter_preserve": True,
                "corpus_source": _customer_corpus(tmp_path),
            }
        )

    @staticmethod
    def _check(plan: ColumnSeed, vals: list[str], expected: list[str], calls: list[str]) -> None:
        df = pd.DataFrame({"c": pd.Series(vals, dtype=object)})
        new = _snapshot(CodeSetHandler().run, df, plan)
        got = list(calls)
        calls.clear()
        base = _snapshot(_base_run, df, plan)
        calls.clear()
        assert new == base
        assert got == expected

    def test_default_caps(self, plan: ColumnSeed, calls: list[str]) -> None:
        a, b, c, d = self.A, self.B, self.C, self.D
        self._check(plan, [a, b, c, a, b, c, d, d], [a, b, c, d], calls)

    def test_entry_cap_two(
        self, plan: ColumnSeed, calls: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        a, b, c, d = self.A, self.B, self.C, self.D
        monkeypatch.setattr(csm, "_MEMO_MAX_ENTRIES", 2)
        self._check(plan, [a, b, c, a, b, c, d, d], [a, b, c, c, d, d], calls)

    def test_byte_cap_boundary_is_inclusive_and_counts_failed_keys(
        self, plan: ColumnSeed, calls: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        a, b, c, d = self.A, self.B, self.C, self.D
        monkeypatch.setattr(csm, "_MEMO_MAX_KEY_BYTES", sys.getsizeof(a) + sys.getsizeof(b))
        self._check(plan, [a, b, c, a, b, c, d, d], [a, b, c, c, d, d], calls)

    def test_both_caps_zero(
        self, plan: ColumnSeed, calls: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        a, b, c, d = self.A, self.B, self.C, self.D
        monkeypatch.setattr(csm, "_MEMO_MAX_ENTRIES", 0)
        monkeypatch.setattr(csm, "_MEMO_MAX_KEY_BYTES", 0)
        vals = [a, b, c, a, b, c, d, d]
        self._check(plan, vals, vals, calls)

    def test_memo_stays_closed_with_spare_bytes(
        self, plan: ColumnSeed, calls: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        a, b, d = self.A, self.B, self.D
        big = "U" + "x" * 4000  # oversized key, absent chapter: a per-value failure
        monkeypatch.setattr(
            csm,
            "_MEMO_MAX_KEY_BYTES",
            sys.getsizeof(a) + sys.getsizeof(b) + sys.getsizeof(d),
        )
        self._check(plan, [a, b, big, d, d], [a, b, big, d, d], calls)


def _route_plan(column: str, seed: ColumnSeed) -> Any:
    from types import SimpleNamespace

    from decoy_engine.plan._types import SeedEnvelope, TableSeed

    return SimpleNamespace(
        seed_envelope=SeedEnvelope(
            job_seed=_SEED,
            per_table=(("t", TableSeed(per_column=((column, seed),), per_group=())),),
        )
    )


def _nested_seed() -> ColumnSeed:
    return ColumnSeed(
        namespace=None,
        strategy="nested",
        provider=None,
        backend_type="decoy_native",
        backend_version="1",
        cardinality_mode="reuse",
        deterministic=False,
        provider_config=(
            ("target", "$.v"),
            ("strategy", "code_set"),
            ("strategy_config", {"code_set": "icd10", "mode": "mask"}),
        ),
        coherent_with=(),
    )


def _direct_seed() -> ColumnSeed:
    return ColumnSeed(
        namespace="cs",
        strategy="code_set",
        provider=None,
        backend_type="decoy_native",
        backend_version="1",
        cardinality_mode="reuse",
        deterministic=False,
        provider_config=(("code_set", "icd10"), ("mode", "mask")),
        coherent_with=(),
    )


_CODES = ["I10", "E11.9", None, "I10", "J45", "E11.9", "I10", "ZZZ"]


def _run_route(route: str) -> tuple[list, Any]:
    from decoy_engine.execution import PandasExecutionAdapter
    from decoy_engine.providers_v2 import get_default_registry

    kw: dict[str, Any] = {
        "registry": get_default_registry(),
        "relationship_graph": RelationshipGraph(edges=(), ordering=()),
        "namespace_registry": NamespaceRegistry(bindings=()),
    }
    if route == "nested":
        import json

        cells = [None if c is None else json.dumps({"v": c}) for c in _CODES]
        table = pa.table({"c": pa.array(cells, type=pa.string())})
        plan = _route_plan("c", _nested_seed())
    else:
        table = pa.table({"c": pa.array(_CODES, type=pa.string())})
        plan = _route_plan("c", _direct_seed())
    adapter = PandasExecutionAdapter()
    if route == "sequential":
        result = adapter.run_sequential(plan, lambda _n: table, config={}, **kw)
    else:
        result = adapter.run(plan, {"t": table}, **kw)
    return result.output.column("c").to_pylist() if result.output is not None else [], result


class TestAt1RouteEntries:
    """Nested and sequential routes through the adapter's real entry points."""

    @pytest.mark.parametrize("route", ["full-frame", "nested", "sequential"])
    def test_route_output_equals_old_loop(
        self, route: str, monkeypatch: pytest.MonkeyPatch, calls: list[str]
    ) -> None:
        new_out, new_res = _run_route(route)
        new_calls = list(calls)
        calls.clear()
        monkeypatch.setattr(
            CodeSetHandler, "run", lambda self, df, col, plan, ctx: _base_run(df, col, plan, ctx)
        )
        base_out, base_res = _run_route(route)
        assert new_out == base_out
        assert new_res.quality_metrics.get("code_set_corpora") == base_res.quality_metrics.get(
            "code_set_corpora"
        )
        # The memo route called the scalar function once per distinct value.
        assert len(new_calls) == len(set(new_calls)) > 0
        assert len(calls) > len(new_calls)
