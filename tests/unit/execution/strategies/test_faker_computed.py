"""GEN-NONFAKER-DRAWS S1: masking `strategy: faker` with uuid, random_int_range and random_choice.

Acceptance tests AT-2 (pandas full-frame leg), AT-3 (frozen vectors), AT-4 (batch and gate
invariance), AT-6 (foreign keys) and AT-12 (structure). Expected values come from the scalar
primitives (`derive_index`, `derive`) and the stdlib uuid layout, never from the code under test,
and the frozen vectors were captured once.
"""

from __future__ import annotations

import ast
import datetime as dt
import decimal
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.determinism import derive, derive_index
from decoy_engine.execution import PandasExecutionAdapter
from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._strategies import _faker_positional as fp
from decoy_engine.execution._strategies._faker import FakerStrategyHandler
from decoy_engine.execution._strategies._faker_positional import computed_mask_draw
from decoy_engine.generation.pool import computed_draw_spec
from decoy_engine.generation.pool._cache import PoolCache
from decoy_engine.kernel._canonicalize import canonicalize_derive_source, encode_int
from decoy_engine.plan._types import ColumnSeed, SeedEnvelope, TableSeed
from decoy_engine.providers_v2 import get_default_registry
from decoy_engine.relationships._graph import RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceRegistry

_REG = get_default_registry()
_GRAPH = RelationshipGraph(edges=(), ordering=())
_NSREG = NamespaceRegistry(bindings=())
MASK = (0x77).to_bytes(8, "big")
JOB = (0x0123456789).to_bytes(8, "big")
UUID_V4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
SRC = pd.Series(["alice", "bob", None, "alice", "carol", "dave", "erin", "frank"])

INT_KW = {"min": 10, "max": 50, "step": 5}
CHOICE_KW = {"elements": ["a", "b", "c", "d", "e"]}

# Captured once with MASK / JOB, namespace "ns", over SRC; positional rows start at row_offset 3.
KAT_UUID_DET = [
    "ccebb7f2-2bfa-4330-b28a-2f66b02070db",
    "1cfe633f-f450-4b42-a76b-aa4479b7a7f2",
    None,
    "ccebb7f2-2bfa-4330-b28a-2f66b02070db",
    "faf26df9-345c-4610-a339-415bda3068ec",
]
KAT_UUID_POS = [
    "30b7a100-da42-4a9c-b440-8eae59ff8ffc",
    "6f909bab-af8d-4088-a686-eacc88d5ac35",
    None,
    "68b18e71-02fb-4948-b841-db20dbad93e9",
    "24f0c7fb-361e-40ff-855a-feb006ef0695",
]
KAT_INT_DET = [40, 40, None, 40, 10, 50, 10, 25]
KAT_INT_POS = [40, 50, None, 30, 20, 20, 30, 20]
KAT_CHOICE_DET = ["e", "c", None, "e", "c", "e", "c", "a"]
KAT_CHOICE_POS = ["d", "c", None, "a", "b", "c", "d", "a"]


def _spec(name: str, kwargs: dict[str, Any] | None = None) -> Any:
    spec = computed_draw_spec("mask", name, kwargs or {})
    assert spec is not None
    return spec


def _draw(name: str, kwargs: dict | None, source: pd.Series, **kw: Any) -> list[Any]:
    mode = kw.pop("mode", "deterministic")
    seed = MASK if mode == "deterministic" else JOB
    return computed_mask_draw(
        source, spec=_spec(name, kwargs), mode=mode, seed=seed, namespace="ns", **kw
    ).to_pylist()


class TestFrozenVectors:
    """AT-3: fixed key, namespace and inputs give committed outputs of the right shape."""

    def test_uuid(self) -> None:
        assert _draw("uuid", None, SRC.iloc[:5]) == KAT_UUID_DET
        assert _draw("uuid", None, SRC.iloc[:5], mode="positional", row_offset=3) == KAT_UUID_POS

    def test_int(self) -> None:
        assert _draw("random_int_range", INT_KW, SRC) == KAT_INT_DET
        assert (
            _draw("random_int_range", INT_KW, SRC, mode="positional", row_offset=3) == KAT_INT_POS
        )

    def test_choice(self) -> None:
        assert _draw("random_choice", CHOICE_KW, SRC) == KAT_CHOICE_DET
        assert (
            _draw("random_choice", CHOICE_KW, SRC, mode="positional", row_offset=3)
            == KAT_CHOICE_POS
        )

    def test_every_uuid_is_version_4(self) -> None:
        got = _draw("uuid", None, pd.Series([f"v{i}" for i in range(500)]))
        assert all(UUID_V4.match(v) for v in got) and len(set(got)) == 500

    def test_every_int_is_on_the_step_grid_inside_the_range(self) -> None:
        got = _draw("random_int_range", INT_KW, pd.Series([f"v{i}" for i in range(500)]))
        assert all(10 <= v <= 50 and (v - 10) % 5 == 0 for v in got)
        assert set(got) == {10, 15, 20, 25, 30, 35, 40, 45, 50}

    def test_every_choice_is_an_element(self) -> None:
        got = _draw("random_choice", CHOICE_KW, pd.Series([f"v{i}" for i in range(200)]))
        assert set(got) == set(CHOICE_KW["elements"])


class TestAgainstScalarPrimitives:
    """The index and uuid bits are the scalar keyed primitives, not a private derivation."""

    @pytest.mark.parametrize("value", ["alice", "bob", "x" * 40])
    def test_deterministic_int_is_derive_index_over_the_canonical_source(self, value: str) -> None:
        count = 9
        idx = derive_index(
            MASK, "ns/computed:random_int_range", canonicalize_derive_source(value), pool_size=count
        )
        assert _draw("random_int_range", INT_KW, pd.Series([value])) == [10 + 5 * idx]

    def test_positional_choice_is_derive_index_over_the_row_number(self) -> None:
        got = _draw(
            "random_choice", CHOICE_KW, pd.Series(["s"] * 6), mode="positional", row_offset=7
        )
        want = [
            CHOICE_KW["elements"][
                derive_index(JOB, "ns/computed:random_choice", encode_int(7 + i), pool_size=5)
            ]
            for i in range(6)
        ]
        assert got == want

    def test_deterministic_uuid_is_the_keyed_digest_in_version_4_layout(self) -> None:
        got = _draw("uuid", None, pd.Series(["alice"]))
        digest = derive(MASK, "ns/computed:uuid", canonicalize_derive_source("alice"))
        assert got == [str(uuid.UUID(bytes=digest[:16], version=4))]

    def test_positional_uuid_keys_the_row_number(self) -> None:
        got = _draw("uuid", None, pd.Series(["s", "s"]), mode="positional", row_offset=11)
        want = [
            str(
                uuid.UUID(bytes=derive(JOB, "ns/computed:uuid", encode_int(11 + i))[:16], version=4)
            )
            for i in range(2)
        ]
        assert got == want

    def test_deterministic_mode_ignores_the_row_position(self) -> None:
        a = _draw("uuid", None, pd.Series(["alice", "bob"]))
        b = _draw("uuid", None, pd.Series(["bob", "alice"]))
        assert a == b[::-1]

    def test_positional_mode_ignores_the_source_value(self) -> None:
        a = _draw("uuid", None, pd.Series(["alice", "bob"]), mode="positional")
        b = _draw("uuid", None, pd.Series(["zed", "yan"]), mode="positional")
        assert a == b

    def test_namespace_separates_draws(self) -> None:
        spec = _spec("random_int_range", {"min": 0, "max": 10**9})
        src = pd.Series([f"v{i}" for i in range(20)])
        a = computed_mask_draw(src, spec=spec, mode="deterministic", seed=MASK, namespace="a")
        b = computed_mask_draw(src, spec=spec, mode="deterministic", seed=MASK, namespace="b")
        assert a.to_pylist() != b.to_pylist()

    def test_computed_namespace_is_apart_from_the_pool_namespace(self) -> None:
        # The same column namespace feeds a pool draw as derive_index(ns, ...); the computed draw
        # appends its marker so the two never share index material.
        plain = derive_index(MASK, "ns", canonicalize_derive_source("alice"), pool_size=10**9)
        spec = _spec("random_int_range", {"min": 0, "max": 10**9 - 1})
        got = computed_mask_draw(
            pd.Series(["alice"]), spec=spec, mode="deterministic", seed=MASK, namespace="ns"
        )
        assert got.to_pylist() != [plain]


class TestBatchAndGateInvariance:
    """AT-4 (pandas leg): a row's draw depends on its full-table number, not on the batch."""

    @pytest.mark.parametrize("size", [1, 3, 7])
    @pytest.mark.parametrize(
        ("name", "kwargs"),
        [("uuid", None), ("random_int_range", INT_KW), ("random_choice", CHOICE_KW)],
    )
    def test_positional_slices_equal_the_whole_column(self, name, kwargs, size) -> None:
        source = pd.Series([f"v{i}" if i % 5 else None for i in range(23)])
        whole = _draw(name, kwargs, source, mode="positional")
        parts: list[Any] = []
        for start in range(0, len(source), size):
            piece = source.iloc[start : start + size].reset_index(drop=True)
            parts += _draw(name, kwargs, piece, mode="positional", row_offset=start)
        assert parts == whole

    @pytest.mark.parametrize(
        ("name", "kwargs"),
        [("uuid", None), ("random_int_range", INT_KW), ("random_choice", CHOICE_KW)],
    )
    def test_a_when_gate_keys_the_selected_rows_by_their_own_position(self, name, kwargs) -> None:
        source = pd.Series([f"v{i}" for i in range(10)])
        whole = _draw(name, kwargs, source, mode="positional", row_offset=100)
        picked = np.array([1, 4, 5, 9])
        gated = _draw(
            name,
            kwargs,
            source.iloc[picked].reset_index(drop=True),
            mode="positional",
            row_offset=100,
            gate_positions=picked,
        )
        assert gated == [whole[i] for i in picked]

    def test_deterministic_slices_equal_the_whole_column(self) -> None:
        source = pd.Series([f"v{i % 6}" for i in range(20)])
        whole = _draw("uuid", None, source)
        parts: list[Any] = []
        for start in range(0, 20, 7):
            parts += _draw("uuid", None, source.iloc[start : start + 7].reset_index(drop=True))
        assert parts == whole


def _plan(
    provider: str,
    config: dict[str, Any] | None = None,
    *,
    deterministic: bool,
    namespace: str | None = "ns",
) -> Any:
    column = ColumnSeed(
        namespace=namespace,
        strategy="faker",
        provider=provider,
        backend_type="faker",
        backend_version="v",
        cardinality_mode="reuse",
        deterministic=deterministic,
        provider_config=tuple((config or {}).items()),
        coherent_with=(),
    )
    return SimpleNamespace(
        seed_envelope=SeedEnvelope(
            job_seed=JOB, per_table=(("t", TableSeed(per_column=(("v", column),), per_group=())),)
        )
    )


def _run(plan: Any, values: pa.Array) -> pa.Table:
    return (
        PandasExecutionAdapter()
        .run_single(
            plan,
            pa.table({"v": values}),
            registry=_REG,
            relationship_graph=_GRAPH,
            namespace_registry=_NSREG,
        )
        .output
    )


def _handler(plan: Any, frame: pd.DataFrame) -> pd.DataFrame:
    """Run the faker handler directly with a known mask key (the adapter derives its own)."""
    column = plan.seed_envelope.per_table[0][1].per_column[0][1]
    ctx = StrategyContext(
        registry=_REG,
        pool_cache=PoolCache(),
        relationship_graph=_GRAPH,
        namespace_registry=_NSREG,
        job_seed=JOB,
        mask_key=MASK,
        current_table="t",
    )
    out, _warnings = FakerStrategyHandler().run(frame.copy(), "v", column, ctx)
    return out


def _handler_ctx(**kw: Any) -> StrategyContext:
    return StrategyContext(
        registry=_REG,
        pool_cache=PoolCache(),
        relationship_graph=_GRAPH,
        namespace_registry=_NSREG,
        job_seed=JOB,
        mask_key=MASK,
        current_table="t",
        **kw,
    )


def _handler_with(plan: Any, frame: pd.DataFrame, **ctx_kw: Any) -> list[Any]:
    column = plan.seed_envelope.per_table[0][1].per_column[0][1]
    out, _ = FakerStrategyHandler().run(frame.copy(), "v", column, _handler_ctx(**ctx_kw))
    return out["v"].tolist()


class TestHandlerKeying:
    """The handler hands each mode the right seed, row number and gate to the draw.

    `mask_key` and `job_seed` differ, the row offset is not zero and a `when:` gate selects
    rows, so a handler that passes the wrong key or a chunk-local row number changes the output."""

    FRAME = pd.DataFrame({"v": ["alice", "bob", None, "carol", "alice"]})
    OFFSET = 40
    # Frame-local positions of the gated rows; the full-table row is OFFSET + position.
    GATE = np.array([1, 3, 4, 7, 8], dtype=np.int64)

    def test_positional_int_is_the_job_seed_draw_over_the_global_row_number(self) -> None:
        plan = _plan("random_int_range", INT_KW, deterministic=False)
        got = _handler_with(plan, self.FRAME, row_offset=self.OFFSET)
        want = [
            None
            if self.FRAME["v"][i] is None
            else 10
            + 5
            * derive_index(
                JOB, "ns/computed:random_int_range", encode_int(self.OFFSET + i), pool_size=9
            )
            for i in range(5)
        ]
        assert got == want

    def test_positional_choice_under_a_gate_uses_the_gated_full_table_rows(self) -> None:
        plan = _plan("random_choice", CHOICE_KW, deterministic=False)
        got = _handler_with(plan, self.FRAME, row_offset=self.OFFSET, gate_positions=self.GATE)
        want = [
            None
            if self.FRAME["v"][i] is None
            else CHOICE_KW["elements"][
                derive_index(
                    JOB,
                    "ns/computed:random_choice",
                    encode_int(self.OFFSET + int(self.GATE[i])),
                    pool_size=5,
                )
            ]
            for i in range(5)
        ]
        assert got == want

    def test_positional_uuid_is_the_job_seed_digest_over_the_global_row_number(self) -> None:
        plan = _plan("uuid", deterministic=False)
        got = _handler_with(plan, self.FRAME, row_offset=self.OFFSET)
        want = [
            None
            if self.FRAME["v"][i] is None
            else str(
                uuid.UUID(
                    bytes=derive(JOB, "ns/computed:uuid", encode_int(self.OFFSET + i))[:16],
                    version=4,
                )
            )
            for i in range(5)
        ]
        assert got == want

    @pytest.mark.parametrize(
        ("provider", "config"),
        [("random_int_range", INT_KW), ("random_choice", CHOICE_KW)],
    )
    def test_deterministic_index_draws_are_the_mask_key_over_the_canonical_source(
        self, provider: str, config: dict[str, Any]
    ) -> None:
        plan = _plan(provider, config, deterministic=True)
        got = _handler_with(plan, self.FRAME, row_offset=self.OFFSET)
        count = 9 if provider == "random_int_range" else 5
        want: list[Any] = []
        for value in self.FRAME["v"]:
            if value is None:
                want.append(None)
                continue
            idx = derive_index(
                MASK,
                f"ns/computed:{provider}",
                canonicalize_derive_source(value),
                pool_size=count,
            )
            want.append(
                10 + 5 * idx if provider == "random_int_range" else CHOICE_KW["elements"][idx]
            )
        assert got == want

    def test_deterministic_uuid_is_the_mask_key_digest_over_the_canonical_source(self) -> None:
        plan = _plan("uuid", deterministic=True)
        got = _handler_with(plan, self.FRAME, row_offset=self.OFFSET)
        want = [
            None
            if value is None
            else str(
                uuid.UUID(
                    bytes=derive(MASK, "ns/computed:uuid", canonicalize_derive_source(value))[:16],
                    version=4,
                )
            )
            for value in self.FRAME["v"]
        ]
        assert got == want


_SOURCES = {
    "string": pa.array(["a", "b", None, "a"], pa.string()),
    "int64": pa.array([1, 2, None, 1], pa.int64()),
    "date": pa.array([dt.date(2020, 1, 1), dt.date(2021, 2, 2), None, dt.date(2020, 1, 1)]),
    "decimal": pa.array(
        [decimal.Decimal("1.50"), decimal.Decimal("2.25"), None, decimal.Decimal("1.50")],
        pa.decimal128(10, 2),
    ),
}
_PROVIDERS = [
    ("uuid", {}, pa.string()),
    ("random_int_range", INT_KW, pa.int64()),
    ("random_choice", CHOICE_KW, pa.string()),
    ("random_choice", {"elements": [1, 2, 3]}, pa.int64()),
]


class TestPandasFullFrameMatrix:
    """AT-2 (pandas leg): three providers x modes x source families, values and exact schema."""

    @pytest.mark.parametrize("deterministic", [True, False], ids=["deterministic", "positional"])
    @pytest.mark.parametrize("kind", list(_SOURCES))
    @pytest.mark.parametrize(("provider", "config", "arrow"), _PROVIDERS)
    def test_schema_nulls_and_repeatability(
        self, provider, config, arrow, kind, deterministic
    ) -> None:
        plan = _plan(provider, config, deterministic=deterministic)
        out = _run(plan, _SOURCES[kind])
        assert out.schema.field("v").type == arrow
        values = out.column("v").to_pylist()
        assert values[2] is None and None not in (values[0], values[1], values[3])
        if deterministic:
            assert values[0] == values[3]
        assert _run(plan, _SOURCES[kind]).column("v").to_pylist() == values

    @pytest.mark.parametrize("kind", ["date", "decimal"])
    def test_deterministic_values_of_non_arrow_index_sources_match_the_scalar_reference(
        self, kind: str
    ) -> None:
        # Dates and decimals are outside the compiled index kernel's admitted types, so the draw
        # takes the reference fallback; the result is still derive_index over the canonical value.
        plan = _plan("random_choice", CHOICE_KW, deterministic=True)
        frame = pa.table({"v": _SOURCES[kind]}).to_pandas()
        raw = frame["v"].tolist()
        out = _handler(plan, frame)["v"].tolist()
        want = [
            None
            if pd.isna(v)
            else CHOICE_KW["elements"][
                derive_index(
                    MASK,
                    "ns/computed:random_choice",
                    canonicalize_derive_source(v),
                    pool_size=5,
                )
            ]
            for v in raw
        ]
        assert out == want
        assert len({v for v in out if v is not None}) > 1

    def test_a_non_arrow_object_source_still_masks(self) -> None:
        mixed = pd.Series(["a", 1, None, ("t", 2)], dtype=object)
        got = _draw("uuid", None, mixed)
        assert got[2] is None and all(UUID_V4.match(v) for v in (got[0], got[1], got[3]))

    def test_empty_frame_keeps_the_type(self) -> None:
        out = _run(_plan("uuid", deterministic=True), pa.array([], pa.string()))
        assert len(out) == 0

    def test_all_null_source(self) -> None:
        out = _run(
            _plan("random_int_range", INT_KW, deterministic=True),
            pa.array([None, None], pa.string()),
        )
        assert out.column("v").to_pylist() == [None, None]

    def test_a_non_reuse_mode_is_not_drawn_here(self) -> None:
        column = ColumnSeed(
            namespace="ns",
            strategy="faker",
            provider="uuid",
            backend_type="faker",
            backend_version="v",
            cardinality_mode="unique",
            deterministic=False,
            provider_config=(),
            coherent_with=(),
        )
        plan = SimpleNamespace(
            seed_envelope=SeedEnvelope(
                job_seed=JOB,
                per_table=(("t", TableSeed(per_column=(("v", column),), per_group=())),),
            )
        )
        with pytest.raises(ValueError, match="reuse"):
            _run(plan, pa.array(["a"], pa.string()))


class TestForeignKeys:
    """AT-6: a deterministic computed key gives equal outputs on both sides of the key."""

    @pytest.mark.parametrize(
        ("provider", "config"),
        [
            ("uuid", {}),
            ("random_int_range", {"min": 0, "max": 10**9}),
            ("random_choice", CHOICE_KW),
        ],
    )
    def test_child_rows_reordered_and_duplicated_match_the_parent(self, provider, config) -> None:
        plan = _plan(provider, config, deterministic=True, namespace="fk_ns")
        parent_src = ["k1", "k2", "k3", "k4"]
        child_src = ["k3", "k1", "k1", "k4", "k2", "k3"]
        parent = _run(plan, pa.array(parent_src)).column("v").to_pylist()
        child = _run(plan, pa.array(child_src)).column("v").to_pylist()
        by_key = dict(zip(parent_src, parent, strict=True))
        assert child == [by_key[k] for k in child_src]
        if provider != "random_choice":
            assert len(set(parent)) == 4

    @pytest.mark.parametrize(
        "provider", ["person_first_name", "uuid", "random_int_range", "random_choice"]
    )
    @pytest.mark.parametrize("deterministic", [False, True])
    def test_fk_compile_outcome_matches_the_pool_provider(
        self, provider: str, deterministic: bool, tmp_path: Path
    ) -> None:
        """A positional key is refused, and a deterministic one compiles, exactly as for a pool."""
        from decoy_engine.contracts.column_shape import NO_SOURCES
        from decoy_engine.plan import compile_plan
        from decoy_engine.profile import profile_source
        from tests.native._chunked_entry_support import TABLE, make_config

        pd.DataFrame({"k": ["a", "b", "c"]}).to_csv(tmp_path / "p.csv", index=False)
        pd.DataFrame({"k": ["a", "b", "a"]}).to_csv(tmp_path / "c.csv", index=False)

        def outcome(name: str) -> str:
            col = {
                "name": "k",
                "strategy": "faker",
                "provider": name,
                "deterministic": deterministic,
            }
            if deterministic:
                col["namespace"] = "kns"
            cfg = make_config(
                [dict(col)],
                extra_tables=[{"name": "c", "columns": [dict(col)]}],
                relationships=[
                    {
                        "parent": {"table": TABLE, "columns": ["k"]},
                        "children": [{"table": "c", "columns": ["k"]}],
                        "orphan_policy": "warn",
                    }
                ],
            )
            cfg["sources"][TABLE]["path"] = str(tmp_path / "p.csv")
            cfg["sources"]["c"]["path"] = str(tmp_path / "c.csv")
            try:
                compile_plan(
                    cfg,
                    profile_source(cfg, seed=1),
                    decoy_engine_version="t",
                    sources=NO_SOURCES,
                )
            except Exception as exc:
                return getattr(exc, "code", type(exc).__name__)
            return "compiled"

        assert outcome(provider) == outcome("person_first_name")


class TestStructure:
    """AT-12: the deterministic index draw goes through the one public helper."""

    @staticmethod
    def _calls() -> set[str]:
        tree = ast.parse(Path(fp.__file__).read_text(encoding="utf-8"))
        func = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "computed_mask_draw"
        )
        return {
            n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
            for n in ast.walk(func)
            if isinstance(n, ast.Call)
        }

    def test_deterministic_index_branch_calls_derive_pool_indices(self) -> None:
        assert "derive_pool_indices" in self._calls()

    def test_no_direct_kernel_or_bare_validated_index_call(self) -> None:
        assert not {"derive_index_batch", "derive_validated_indices"} & self._calls()

    def test_derive_pool_indices_is_the_public_pool_export(self) -> None:
        from decoy_engine.generation import pool

        assert pool.derive_pool_indices is pool._sampler.derive_pool_indices


class TestChunkedRouting:
    """AT-2 and AT-4 (chunked routing): no native route admits a computed provider in this slice.

    A computed provider is outside the chunked faker allowlist, like any pool provider that is not
    a first or last name. An auto-routed job therefore runs the whole frame and equals the forced
    full-frame run; a forced chunked entry refuses before reading any chunk, with the same code it
    gives a non-allowlisted pool provider."""

    ROWS = 30

    @staticmethod
    def _columns(provider: str, config: dict[str, Any], deterministic: bool) -> list[dict]:
        col: dict[str, Any] = {
            "name": "f",
            "strategy": "faker",
            "provider": provider,
            "deterministic": deterministic,
        }
        if deterministic:
            col["namespace"] = "chunk_ns"
        if config:
            col["provider_config"] = config
        return [col, {"name": "p", "strategy": "passthrough"}]

    @classmethod
    def _table(cls) -> pa.Table:
        values = [None if i % 7 == 3 else f"v{i % 5}" for i in range(cls.ROWS)]
        return pa.table({"f": pa.array(values, pa.string()), "p": pa.array(range(cls.ROWS))})

    @classmethod
    def _run(cls, columns: list[dict], tmp_path: Path, **kw: Any) -> Any:
        import pyarrow.parquet as pq

        from decoy_engine import run_pipeline
        from tests.native._chunked_entry_support import (
            ENGINE_VERSION,
            TABLE,
            key_provider,
            make_config,
        )

        cfg = make_config(columns)
        pq.write_table(cls._table(), str(tmp_path / "in.parquet"))
        cfg["sources"][TABLE] = {
            "type": "file",
            "format": "parquet",
            "path": str(tmp_path / "in.parquet"),
        }
        cfg["targets"][TABLE] = {
            "type": "file",
            "format": "parquet",
            "path": str(tmp_path / "out.parquet"),
        }
        return run_pipeline(
            cfg,
            {TABLE: cls._table()},
            engine_version=ENGINE_VERSION,
            key_provider=key_provider(),
            **kw,
        ).outputs[TABLE]

    @pytest.mark.parametrize("deterministic", [True, False], ids=["deterministic", "positional"])
    @pytest.mark.parametrize(
        ("provider", "config", "arrow"),
        [
            ("uuid", {}, pa.string()),
            ("random_int_range", INT_KW, pa.int64()),
            ("random_choice", CHOICE_KW, pa.string()),
        ],
    )
    def test_auto_routing_equals_the_full_frame_run(
        self, provider, config, arrow, deterministic, tmp_path
    ) -> None:
        columns = self._columns(provider, config, deterministic)
        whole = self._run(columns, tmp_path, auto_chunk=False)
        auto = self._run(columns, tmp_path, auto_chunk_threshold_rows=3, chunk_size_rows=4)
        assert auto.schema.field("f").type == whole.schema.field("f").type == arrow
        assert auto.column("f").to_pylist() == whole.column("f").to_pylist()
        assert whole.column("f").to_pylist()[3] is None and whole.column("f")[0].is_valid

    @pytest.mark.parametrize("provider", ["uuid", "random_int_range", "random_choice"])
    def test_the_native_admission_declines_a_computed_provider_by_name(self, provider) -> None:
        """Why auto routing falls through: the native faker allowlist has no computed provider."""
        from decoy_engine.execution.native._dispatch import NodeRouteRecord
        from decoy_engine.execution.native._real_type_admission import real_type_decline
        from decoy_engine.execution.native._route_decline_codes import (
            RouteDeclineCode,
            column_decline,
        )
        from tests.native._chunked_entry_support import TABLE, make_config

        config = {"random_int_range": INT_KW, "random_choice": CHOICE_KW}.get(provider, {})
        cfg = make_config(self._columns(provider, config, True))
        node = (NodeRouteRecord(column="f", strategy="faker", route="native_kernel"),)
        found = real_type_decline(
            cfg, node, pa.schema([("f", pa.string())]), table=TABLE, profile=None
        )
        assert found is not None
        assert found.record == column_decline(
            RouteDeclineCode.FAKER_PROVIDER_NOT_NATIVE, TABLE, "f"
        )
        assert found.reason == f"faker_provider_not_native:f:{provider}"

    @pytest.mark.parametrize("provider", ["uuid", "random_int_range", "random_choice"])
    def test_a_forced_chunked_entry_refuses_before_any_chunk_runs(self, provider) -> None:
        from decoy_engine.plan import PlanCompileError
        from tests.native._b8_support import run_one
        from tests.native._chunked_entry_support import make_config, split

        config = {"random_int_range": INT_KW, "random_choice": CHOICE_KW}.get(provider, {})
        columns = self._columns(provider, config, True)
        with pytest.raises(PlanCompileError) as exc:
            run_one(make_config(columns), split(self._table(), 7))
        assert exc.value.code == "chunked_strategy_conditions_unmet"


class TestRelationshipRoutes:
    """AT-2 and AT-6 (other routes): a computed column beside a foreign key.

    Sequential and auto-routed jobs equal the full-frame run, a uuid key matches on both sides of
    the key, and the out-of-core route declines the column (it admits no computed provider yet), so
    a forced out-of-core request is refused up front."""

    N = 40

    @classmethod
    def _tables(cls) -> tuple[pa.Table, pa.Table]:
        n = cls.N
        parent = pa.table(
            {
                "id": pa.array([f"k{i}" for i in range(n)]),
                "f": pa.array([f"v{i % 5}" if i % 9 else None for i in range(n)]),
            }
        )
        child = pa.table(
            {
                "cid": pa.array([f"c{i}" for i in range(n * 2)]),
                "pid": pa.array([f"k{i % n}" for i in range(n * 2)]),
            }
        )
        return parent, child

    def _config(self, tmp_path: Path, *, key_provider_name: str | None, column: dict) -> Any:
        import pyarrow.parquet as pq

        from tests.native._chunked_entry_support import TABLE, make_config

        parent, child = self._tables()
        pq.write_table(parent, str(tmp_path / "p.parquet"))
        pq.write_table(child, str(tmp_path / "c.parquet"))

        def key(name: str) -> dict[str, Any]:
            if key_provider_name is None:
                return {"name": name, "strategy": "passthrough"}
            return {
                "name": name,
                "strategy": "faker",
                "provider": key_provider_name,
                "deterministic": True,
                "namespace": "idns",
            }

        cfg = make_config(
            [key("id"), column],
            extra_tables=[
                {
                    "name": "c",
                    "columns": [{"name": "cid", "strategy": "passthrough"}, key("pid")],
                }
            ],
            relationships=[
                {
                    "parent": {"table": TABLE, "columns": ["id"]},
                    "children": [{"table": "c", "columns": ["pid"]}],
                    "orphan_policy": "warn",
                    "namespace": "idns",
                }
            ],
        )
        for name, stem in ((TABLE, "p"), ("c", "c")):
            cfg["sources"][name] = {
                "type": "file",
                "format": "parquet",
                "path": str(tmp_path / f"{stem}.parquet"),
            }
            cfg["targets"][name] = {
                "type": "file",
                "format": "parquet",
                "path": str(tmp_path / f"{stem}_out.parquet"),
            }
        return cfg

    def _run(self, cfg: Any, **kw: Any) -> Any:
        import copy

        from decoy_engine import run_pipeline
        from tests.native._chunked_entry_support import ENGINE_VERSION, TABLE, key_provider

        parent, child = self._tables()
        return run_pipeline(
            copy.deepcopy(cfg),
            {TABLE: parent, "c": child},
            engine_version=ENGINE_VERSION,
            key_provider=key_provider(),
            **kw,
        )

    @pytest.mark.parametrize(
        ("provider", "config", "deterministic"),
        [
            ("uuid", {}, True),
            ("random_int_range", {"min": 1, "max": 9}, False),
            ("random_choice", CHOICE_KW, True),
        ],
    )
    def test_sequential_and_auto_routes_equal_the_full_frame_run(
        self, provider, config, deterministic, tmp_path
    ) -> None:
        column = {"name": "f", "strategy": "faker", "provider": provider}
        column["deterministic"] = deterministic
        if deterministic:
            column["namespace"] = "fns"
        if config:
            column["provider_config"] = config
        cfg = self._config(tmp_path, key_provider_name=None, column=column)
        whole = self._run(cfg, execution_mode="full_frame", auto_chunk=False)
        for kw in (
            {"execution_mode": "sequential"},
            {
                "auto_chunk_threshold_rows": 3,
                "chunk_size_rows": 16,
                "out_of_core_threshold_rows": 3,
            },
        ):
            got = self._run(cfg, **kw)
            for table in ("t", "c"):
                assert got.outputs[table].equals(whole.outputs[table]), (table, kw)

    def test_a_uuid_key_matches_on_both_sides_of_the_key(self, tmp_path: Path) -> None:
        column = {"name": "f", "strategy": "passthrough"}
        cfg = self._config(tmp_path, key_provider_name="uuid", column=column)
        out = self._run(cfg, execution_mode="full_frame", auto_chunk=False).outputs
        parent_ids = out["t"].column("id").to_pylist()
        child_pids = out["c"].column("pid").to_pylist()
        assert all(UUID_V4.match(v) for v in parent_ids) and len(set(parent_ids)) == self.N
        assert child_pids == [parent_ids[i % self.N] for i in range(self.N * 2)]

    def test_forced_out_of_core_refuses_a_computed_column(self, tmp_path: Path) -> None:
        from decoy_engine import ConfigError

        column = {
            "name": "f",
            "strategy": "faker",
            "provider": "uuid",
            "deterministic": True,
            "namespace": "fns",
        }
        cfg = self._config(tmp_path, key_provider_name=None, column=column)
        with pytest.raises(ConfigError, match="out_of_core_faker_pool_unsupported"):
            self._run(cfg, execution_mode="out_of_core")
