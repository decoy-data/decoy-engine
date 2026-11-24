"""GEN-NONFAKER-DRAWS S2: the sequential and out-of-core routes for computed Faker draws.

Acceptance tests AT-2 (sequential and out-of-core legs, E11 and E13 declines, forced preflight
refusal) and AT-8 (`lorem_text` pools, `address_full` stays refused). The oracle for every value is
the forced full-frame run, which S1 pins to the scalar primitives; this file proves the native
routes give the same values and the same schema, and that a draw no string-tokenizing route can
carry is declined with its registered reason before it runs.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import ConfigError
from decoy_engine.execution import PandasExecutionAdapter
from decoy_engine.execution._operator_registry import PYTHON_SCALAR, RUST_COMPANION
from decoy_engine.execution.native._provider_class import (
    classify_provider,
    computed_mask_spec,
    computed_output_decline,
)
from decoy_engine.execution.native._real_type_admission import faker_provider_decline
from decoy_engine.execution.native._route_decline_codes import RouteDeclineCode
from decoy_engine.execution.out_of_core import run_fk_out_of_core
from decoy_engine.execution.out_of_core._mask import masked_output_type
from decoy_engine.generation.kinds._provider import draw_path
from decoy_engine.plan import PlanCompileError
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.providers_v2 import get_default_registry
from decoy_engine.relationships._graph import OrphanPolicy
from decoy_engine.relationships._namespace import NamespaceRegistry
from tests.native._chunked_entry_support import COMPANION_PRESENT
from tests.parity.test_out_of_core_group_b_parity import (
    _assert_value_equal,
    _gate_admits,
    _gate_codes,
    _payload_edge_job,
)
from tests.unit.execution.strategies.test_faker_computed import (
    CHOICE_KW,
    INT_KW,
    UUID_V4,
    TestRelationshipRoutes,
)

_REG = get_default_registry()
_NS = NamespaceRegistry(bindings=())
NOT_STRING = "faker_computed_output_type_unsupported"
OOC_NOT_STRING = "out_of_core_faker_computed_output_type_unsupported"

UUID = ("uuid", {})
STR_CHOICE = ("random_choice", CHOICE_KW)
INT_CHOICE = ("random_choice", {"elements": [1, 2, 3]})
INT_RANGE = ("random_int_range", INT_KW)
STRING_DRAWS = [UUID, STR_CHOICE]
OTHER_DRAWS = [INT_RANGE, INT_CHOICE]


def _column(provider: str, config: dict[str, Any], *, deterministic: bool) -> dict[str, Any]:
    column: dict[str, Any] = {"name": "f", "strategy": "faker", "provider": provider}
    column["deterministic"] = deterministic
    if deterministic:
        column["namespace"] = "fns"
    if config:
        column["provider_config"] = config
    return column


def _seed(provider: str, config: dict[str, Any], *, deterministic: bool = True) -> ColumnSeed:
    return ColumnSeed(
        namespace="fns" if deterministic else None,
        strategy="faker",
        provider=provider,
        backend_type="faker",
        backend_version="v",
        cardinality_mode="reuse",
        deterministic=deterministic,
        provider_config=tuple(config.items()),
        coherent_with=(),
    )


needs_companion = pytest.mark.skipif(not COMPANION_PRESENT, reason="needs the native companion")


class TestSequentialRoute:
    """AT-2 sequential leg: exact-string draws run on the kernels, others decline with E13."""

    helper = TestRelationshipRoutes()

    def _runs(self, tmp_path: Path, column: dict[str, Any]) -> tuple[Any, Any]:
        cfg = self.helper._config(tmp_path, key_provider_name=None, column=column)
        whole = self.helper._run(copy.deepcopy(cfg), execution_mode="full_frame", auto_chunk=False)
        seq = self.helper._run(copy.deepcopy(cfg), execution_mode="sequential")
        return whole, seq

    @staticmethod
    def _entry(result: Any) -> dict[str, Any]:
        [entry] = [
            e
            for e in result.quality_metrics["sequential_faker"]
            if e["column"] == "f" and e["path"] == "scalar"
        ]
        return entry

    @pytest.mark.parametrize("deterministic", [True, False], ids=["deterministic", "positional"])
    @pytest.mark.parametrize(("provider", "config"), STRING_DRAWS)
    def test_values_and_schema_equal_the_full_frame_run(
        self, provider, config, deterministic, tmp_path
    ) -> None:
        whole, seq = self._runs(tmp_path, _column(provider, config, deterministic=deterministic))
        for table in ("t", "c"):
            assert seq.outputs[table].equals(whole.outputs[table]), table
        values = seq.outputs["t"].column("f")
        assert values.type == pa.string()
        assert 0 < values.null_count < len(values)
        if provider == "uuid":
            assert all(UUID_V4.match(v) for v in values.drop_null().to_pylist())

    @needs_companion
    @pytest.mark.parametrize("deterministic", [True, False], ids=["deterministic", "positional"])
    @pytest.mark.parametrize(("provider", "config"), STRING_DRAWS)
    def test_the_kernel_ran_and_the_evidence_says_so(
        self, provider, config, deterministic, tmp_path
    ) -> None:
        _, seq = self._runs(tmp_path, _column(provider, config, deterministic=deterministic))
        entry = self._entry(seq)
        assert entry["executed_backend"] == RUST_COMPANION, entry
        assert "reason" not in entry and entry["native_calls"] == 1, entry

    @pytest.mark.parametrize("deterministic", [True, False], ids=["deterministic", "positional"])
    @pytest.mark.parametrize(("provider", "config"), OTHER_DRAWS)
    def test_a_non_string_draw_runs_on_pandas_with_the_full_frame_values(
        self, provider, config, deterministic, tmp_path
    ) -> None:
        whole, seq = self._runs(tmp_path, _column(provider, config, deterministic=deterministic))
        for table in ("t", "c"):
            assert seq.outputs[table].equals(whole.outputs[table]), table
        entry = self._entry(seq)
        assert entry["executed_backend"] == PYTHON_SCALAR and entry["native_calls"] == 0, entry
        assert seq.outputs["t"].schema.field("f").type != pa.string()

    @pytest.mark.parametrize("deterministic", [True, False], ids=["deterministic", "positional"])
    @pytest.mark.parametrize(("provider", "config"), OTHER_DRAWS)
    def test_a_non_string_draw_declines_with_the_typed_reason(
        self, provider, config, deterministic
    ) -> None:
        from decoy_engine.execution._sequential_native_ops import _faker_admit

        seed = _seed(provider, config, deterministic=deterministic)
        assert _faker_admit("f", pa.string(), seed) == f"{NOT_STRING}:f:{provider}"

    def test_a_uuid_with_a_non_string_source_stays_on_pandas(self, tmp_path) -> None:
        """Admission is exact `string` in, as for the pool operator: another source type declines
        with the shared source reason and the pandas draw still masks it."""
        from decoy_engine.execution._sequential_native_ops import _faker_admit

        seed = _seed("uuid", {})
        assert _faker_admit("f", pa.string(), seed) is None
        assert _faker_admit("f", pa.int64(), seed) == "faker_source_type_not_string:f:int64"


class TestOutOfCoreRoute:
    """AT-2 out-of-core leg: deterministic exact-string draws stream through the route."""

    @staticmethod
    def _job(provider: str, config: dict[str, Any], *, deterministic: bool = True) -> Any:
        values = [None if i % 5 == 3 else f"v{i % 4}" for i in range(12)]
        return _payload_edge_job(
            _seed(provider, config, deterministic=deterministic),
            values,
            policy=OrphanPolicy.PRESERVE,
        )

    @pytest.mark.parametrize(("provider", "config"), STRING_DRAWS)
    def test_the_gate_admits_and_values_equal_the_pandas_oracle(self, provider, config) -> None:
        plan, sources, graph = self._job(provider, config)
        assert _gate_admits(plan, graph)
        oracle = PandasExecutionAdapter().run(
            plan, sources, registry=_REG, relationship_graph=graph, namespace_registry=_NS
        )
        ooc = run_fk_out_of_core(plan, sources, config={}, registry=_REG, relationship_graph=graph)
        for table in oracle.outputs:
            _assert_value_equal(oracle.outputs[table], ooc.outputs[table], f"{provider}:{table}")
        out = ooc.outputs["parent"].column("pay")
        assert out.type == pa.string() and out.null_count > 0
        src = sources["parent"].column("pay").to_pylist()
        assert out.to_pylist() != src

    @needs_companion
    @pytest.mark.parametrize(("provider", "config"), STRING_DRAWS)
    def test_the_evidence_names_the_kernel(self, provider, config) -> None:
        plan, sources, graph = self._job(provider, config)
        ooc = run_fk_out_of_core(plan, sources, config={}, registry=_REG, relationship_graph=graph)
        entries = [e for e in ooc.quality_metrics["out_of_core_faker"] if e["column"] == "pay"]
        assert entries and all(e["executed_backend"] == RUST_COMPANION for e in entries), entries

    @pytest.mark.parametrize(("provider", "config"), OTHER_DRAWS)
    def test_a_non_string_draw_is_declined_at_the_gate_with_the_typed_code(
        self, provider, config
    ) -> None:
        plan, _, graph = self._job(provider, config)
        assert not _gate_admits(plan, graph)
        assert OOC_NOT_STRING in _gate_codes(plan, graph)

    @pytest.mark.parametrize(("provider", "config"), STRING_DRAWS)
    def test_a_positional_draw_keeps_the_existing_shape_decline(self, provider, config) -> None:
        plan, _, graph = self._job(provider, config, deterministic=False)
        assert not _gate_admits(plan, graph)
        assert "out_of_core_faker_pool_unsupported" in _gate_codes(plan, graph)

    @pytest.mark.parametrize(
        ("provider", "config", "arrow"),
        [
            ("uuid", {}, pa.string()),
            ("random_int_range", INT_KW, pa.int64()),
            ("random_choice", CHOICE_KW, pa.string()),
            ("random_choice", {"elements": [1, 2, 3]}, pa.int64()),
            ("random_choice", {"elements": [0.5, 1.5]}, pa.float64()),
            ("person_email", {}, pa.string()),
        ],
    )
    def test_masked_output_type_reads_the_descriptor(self, provider, config, arrow) -> None:
        assert masked_output_type(_seed(provider, config), pa.string()) == arrow

    def test_a_forced_run_refuses_a_non_string_draw_before_any_write(self, tmp_path) -> None:
        helper = TestRelationshipRoutes()
        cfg = helper._config(
            tmp_path, key_provider_name=None, column=_column(*INT_RANGE, deterministic=True)
        )
        with pytest.raises(ConfigError, match=OOC_NOT_STRING):
            helper._run(cfg, execution_mode="out_of_core")
        assert not list(tmp_path.glob("*_out.parquet"))

    @pytest.mark.parametrize(("provider", "config"), STRING_DRAWS)
    def test_a_forced_run_equals_the_full_frame_run(self, provider, config, tmp_path) -> None:
        helper = TestRelationshipRoutes()
        cfg = helper._config(
            tmp_path, key_provider_name=None, column=_column(provider, config, deterministic=True)
        )
        whole = helper._run(copy.deepcopy(cfg), execution_mode="full_frame", auto_chunk=False)
        forced = helper._run(copy.deepcopy(cfg), execution_mode="out_of_core")
        for table in ("t", "c"):
            assert forced.outputs[table].equals(whole.outputs[table]), table


class TestProviderAdmission:
    """The one provider-level verdict every route reads (`faker_provider_decline`)."""

    @pytest.mark.parametrize(("provider", "config"), STRING_DRAWS)
    def test_a_route_that_runs_computed_admits_an_exact_string_draw(self, provider, config) -> None:
        assert faker_provider_decline("f", provider, config, runs_computed=True) is None

    @pytest.mark.parametrize(("provider", "config"), STRING_DRAWS)
    def test_a_route_that_does_not_run_computed_declines_it_as_not_native(
        self, provider, config
    ) -> None:
        assert faker_provider_decline("f", provider, config, runs_computed=False) == (
            f"faker_provider_not_native:f:{provider}",
            RouteDeclineCode.FAKER_PROVIDER_NOT_NATIVE,
        )

    @pytest.mark.parametrize("runs_computed", [True, False])
    @pytest.mark.parametrize(("provider", "config"), OTHER_DRAWS)
    def test_every_route_declines_a_non_string_draw_with_the_typed_reason(
        self, provider, config, runs_computed
    ) -> None:
        assert faker_provider_decline("f", provider, config, runs_computed=runs_computed) == (
            f"{NOT_STRING}:f:{provider}",
            RouteDeclineCode.FAKER_COMPUTED_OUTPUT_TYPE_UNSUPPORTED,
        )

    def test_a_pool_provider_follows_the_allowlist_on_every_route(self) -> None:
        for runs_computed in (True, False):
            assert (
                faker_provider_decline("f", "person_email", {}, runs_computed=runs_computed) is None
            )
            assert faker_provider_decline("f", "address_full", {}, runs_computed=runs_computed) == (
                "faker_provider_not_native:f:address_full",
                RouteDeclineCode.FAKER_PROVIDER_NOT_NATIVE,
            )

    def test_the_reason_never_carries_an_argument_value(self) -> None:
        reason = computed_output_decline("f", "random_choice", {"elements": [101, 202, 303]})
        assert reason == f"{NOT_STRING}:f:random_choice"
        assert computed_mask_spec("person_email", {}) is None
        assert computed_output_decline("f", "uuid", {}) is None


class TestLoremText:
    """AT-8: `lorem_text` pools; `address_full` stays refused."""

    def test_it_is_a_pool_provider_now(self) -> None:
        assert classify_provider("lorem_text", None) == "pool_native"
        assert draw_path(_REG.get_capabilities("lorem_text")) == "pool"

    def test_address_full_is_still_refused_at_compile(self) -> None:
        from decoy_engine.plan._checks import check_non_poolable_provider_with_pool_backend

        cfg = {
            "version": 2,
            "tables": [
                {
                    "name": "t",
                    "columns": [{"name": "a", "strategy": "faker", "provider": "address_full"}],
                }
            ],
        }
        with pytest.raises(PlanCompileError) as exc:
            check_non_poolable_provider_with_pool_backend(cfg)
        assert exc.value.code == "non_poolable_provider_with_pool_backend"

    @pytest.mark.parametrize("deterministic", [True, False], ids=["deterministic", "positional"])
    def test_a_masked_lorem_text_column_runs_on_the_pool_path(
        self, deterministic, tmp_path
    ) -> None:
        helper = TestRelationshipRoutes()
        column = _column("lorem_text", {"pool_size": 50}, deterministic=deterministic)
        cfg = helper._config(tmp_path, key_provider_name=None, column=column)
        first = helper._run(copy.deepcopy(cfg), execution_mode="full_frame", auto_chunk=False)
        again = helper._run(copy.deepcopy(cfg), execution_mode="full_frame", auto_chunk=False)
        values = first.outputs["t"].column("f")
        assert values.type == pa.string() and values.null_count > 0
        assert all(len(v) > 20 for v in values.drop_null().to_pylist())
        assert first.outputs["t"].equals(again.outputs["t"])
