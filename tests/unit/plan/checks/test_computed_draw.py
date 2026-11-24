"""GEN-NONFAKER-DRAWS S1: compile refusals for the computed Faker draws (AT-7) and the
scan and init starters that were refused before (AT-1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from decoy_engine.contracts.column_shape import NO_SOURCES
from decoy_engine.plan import PlanCompileError, compile_plan, run_config_only_checks
from decoy_engine.plan.checks import check_computed_draws
from decoy_engine.profile import profile_source
from tests.native._chunked_entry_support import make_config


def _cfg(column: dict[str, Any]) -> dict[str, Any]:
    return {"version": 2, "tables": [{"name": "t", "columns": [column]}]}


def _col(provider: str, **extra: Any) -> dict[str, Any]:
    return {"name": "c", "strategy": "faker", "provider": provider, **extra}


def _refusal(column: dict[str, Any]) -> PlanCompileError:
    with pytest.raises(PlanCompileError) as exc:
        check_computed_draws(_cfg(column))
    assert exc.value.__cause__ is None and exc.value.__context__ is None
    return exc.value


class TestRangeRefusals:
    @pytest.mark.parametrize(
        "config",
        [
            {"min": True},
            {"max": False},
            {"step": True},
            {"min": "5"},
            {"max": "9"},
            {"max": 5.0},
            {"min": 1.5},
            {"min": 9, "max": 3},
            {"step": 0},
            {"step": -2},
            {"min": 0, "max": 2**56},
            {"min": 0, "max": 2**63},
            {"min": -(2**63) - 1, "max": 0},
            {"min": 0, "max": 2**63 - 1, "step": 2},
            {"max_value": 5},
        ],
    )
    def test_out_of_contract_range_is_computed_draw_range_invalid(self, config: dict) -> None:
        found = _refusal(_col("random_int_range", provider_config=config))
        assert found.code == "computed_draw_range_invalid"
        assert found.path == "tables.t.columns.c.provider_config"

    def test_the_int64_top_value_cell(self) -> None:
        # count 2**56 fits the index domain, but the top value min + (count - 1) * step does not.
        config = {"min": 2**62, "max": 2**63 + 5, "step": 1}
        assert _refusal(_col("random_int_range", provider_config=config)).code == (
            "computed_draw_range_invalid"
        )

    @pytest.mark.parametrize(
        "config",
        [
            {},
            {"min": 1},
            {"min": 0, "max": 2**56 - 1},
            {"min": -(2**63), "max": 2**63 - 256, "step": 256},
        ],
    )
    def test_in_contract_ranges_pass(self, config: dict) -> None:
        check_computed_draws(_cfg(_col("random_int_range", provider_config=config)))

    def test_pool_build_knobs_are_not_draw_arguments(self) -> None:
        check_computed_draws(
            _cfg(_col("random_int_range", provider_config={"pool_size": 10, "locale": "en_US"}))
        )


class TestElementRefusals:
    @pytest.mark.parametrize(
        "elements",
        [
            [],
            (),
            "abc",
            {"a": 1},
            None,
            5,
            [1, "a"],
            [1, 2.5],
            [True, 1],
            [None],
            [[1]],
            [{"a": 1}],
        ],
    )
    def test_bad_elements_are_computed_draw_elements_invalid(self, elements: Any) -> None:
        found = _refusal(_col("random_choice", provider_config={"elements": elements}))
        assert found.code == "computed_draw_elements_invalid"

    def test_unknown_choice_argument_is_refused(self) -> None:
        found = _refusal(_col("random_choice", provider_config={"element": ["a"]}))
        assert found.code == "computed_draw_elements_invalid"

    def test_uuid_takes_no_arguments(self) -> None:
        found = _refusal(_col("uuid", provider_config={"version": 7}))
        assert found.code == "computed_draw_elements_invalid"

    def test_non_dict_provider_config_is_refused(self) -> None:
        found = _refusal(_col("random_choice", provider_config=["a"]))
        assert found.code == "computed_draw_elements_invalid"

    @pytest.mark.parametrize("elements", [["a", "b"], ("a",), [1, 2, 3], [1.5], [True, False]])
    def test_homogeneous_lists_pass(self, elements: Any) -> None:
        check_computed_draws(_cfg(_col("random_choice", provider_config={"elements": elements})))


class TestModeAndNamespace:
    @pytest.mark.parametrize(
        "mode", ["unique", "match_source_cardinality", "scale_source_cardinality"]
    )
    @pytest.mark.parametrize("provider", ["uuid", "random_int_range", "random_choice"])
    def test_a_cardinality_mode_other_than_reuse_is_refused(self, provider: str, mode: str) -> None:
        found = _refusal(_col(provider, cardinality_mode=mode))
        assert found.code == "computed_draw_mode_unsupported"
        assert found.path == "tables.t.columns.c.cardinality_mode"

    def test_reuse_and_absent_pass(self) -> None:
        check_computed_draws(_cfg(_col("uuid", cardinality_mode="reuse")))
        check_computed_draws(_cfg(_col("uuid")))

    @pytest.mark.parametrize("provider", ["uuid", "random_choice", "person_email"])
    def test_a_namespace_with_the_computed_marker_is_reserved(self, provider: str) -> None:
        found = _refusal(_col(provider, namespace="people/computed:uuid"))
        assert found.code == "computed_draw_namespace_reserved"
        assert found.path == "tables.t.columns.c.namespace"

    def test_other_namespaces_pass(self) -> None:
        check_computed_draws(_cfg(_col("uuid", namespace="people/computed")))

    def test_pool_providers_are_not_checked_for_arguments_or_mode(self) -> None:
        check_computed_draws(
            _cfg(_col("person_first_name", cardinality_mode="unique", provider_config={"x": 1}))
        )

    def test_non_faker_columns_and_malformed_entries_are_skipped(self) -> None:
        check_computed_draws(_cfg({"name": "c", "strategy": "hash", "provider": "uuid"}))
        check_computed_draws({"tables": ["junk", {"name": "t", "columns": ["junk"]}]})
        check_computed_draws({})


class TestMessagesCarryNoValues:
    CANARY = "CANARY-9f3c"

    @pytest.mark.parametrize(
        "column",
        [
            _col("random_choice", provider_config={"elements": [CANARY, 1]}),
            _col("random_int_range", provider_config={"min": CANARY}),
            _col("random_int_range", provider_config={"min": 123456789, "max": 5}),
            _col("uuid", provider_config={CANARY: 1}),
        ],
    )
    def test_refusal_text_never_echoes_arguments(self, column: dict[str, Any]) -> None:
        found = _refusal(column)
        assert self.CANARY not in found.message
        assert "123456789" not in found.message
        assert "t" in found.message and "c" in found.message


class TestWiring:
    def test_run_config_only_checks_runs_the_refusals(self) -> None:
        with pytest.raises(PlanCompileError) as exc:
            run_config_only_checks(_cfg(_col("random_int_range", provider_config={"step": 0})))
        assert exc.value.code == "computed_draw_range_invalid"

    def test_compile_plan_refuses_through_the_same_check(self, tmp_path: Path) -> None:
        (tmp_path / "t.csv").write_text("c\na\nb\n")
        cfg = make_config([_col("random_choice", provider_config={"elements": []})])
        cfg["sources"]["t"]["path"] = str(tmp_path / "t.csv")
        with pytest.raises(PlanCompileError) as exc:
            compile_plan(
                cfg, profile_source(cfg, seed=1), decoy_engine_version="t", sources=NO_SOURCES
            )
        assert exc.value.code == "computed_draw_elements_invalid"


class TestScanAndInitStartersCompile:
    """AT-1: what `decoy scan` and `decoy init` write for a UUID column compiles and runs."""

    @staticmethod
    def _compile(tmp_path: Path, column: dict[str, Any], values: list[str]) -> Any:
        (tmp_path / "t.csv").write_text("c\n" + "\n".join(values) + "\n")
        cfg = make_config([column])
        cfg["sources"]["t"]["path"] = str(tmp_path / "t.csv")
        plan = compile_plan(
            cfg, profile_source(cfg, seed=1), decoy_engine_version="t", sources=NO_SOURCES
        )
        return cfg, plan

    def test_every_faker_starter_in_the_detector_table_compiles(self, tmp_path: Path) -> None:
        from decoy_engine.profiling.recommendations import DETECTOR_DESCRIPTORS

        starters = {
            d: s.starter
            for d, s in DETECTOR_DESCRIPTORS.items()
            if s.starter is not None and s.starter.strategy == "faker" and s.starter.provider
        }
        assert "uuid" in starters
        for detector_id, starter in starters.items():
            column = {
                "name": "c",
                "strategy": "faker",
                "provider": starter.provider,
                "provider_config": dict(starter.provider_config),
            }
            self._compile(tmp_path, column, ["a", "b", "c"])  # raises on a refused starter
            assert detector_id

    def test_the_uuid_starter_runs_and_writes_version_4_uuids(self, tmp_path: Path) -> None:
        import re

        import pyarrow as pa

        from decoy_engine import run_pipeline
        from decoy_engine.profiling.recommendations import starter_choice
        from tests.native._chunked_entry_support import ENGINE_VERSION, key_provider

        choice = starter_choice("uuid")
        assert choice is not None and choice.provider == "uuid"
        column = {"name": "c", "strategy": "faker", "provider": choice.provider}
        cfg, _plan = self._compile(tmp_path, column, ["a", "b", "c"])
        result = run_pipeline(
            cfg,
            {"t": pa.table({"c": ["a", "b", None, "a"]})},
            engine_version=ENGINE_VERSION,
            key_provider=key_provider(),
            auto_chunk=False,
        )
        values = result.outputs["t"].column("c").to_pylist()
        pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
        )
        assert values[2] is None and all(
            pattern.match(v) for v in (values[0], values[1], values[3])
        )
        assert len({values[0], values[1]}) == 2

    def test_the_ipv4_swap_the_init_review_text_suggests_compiles_and_runs(
        self, tmp_path: Path
    ) -> None:
        import pyarrow as pa

        from decoy_engine import run_pipeline
        from tests.native._chunked_entry_support import ENGINE_VERSION, key_provider

        column = {
            "name": "c",
            "strategy": "faker",
            "provider": "random_choice",
            "provider_config": {"elements": ["10.0.0.1", "10.0.0.2", "192.168.1.9"]},
        }
        cfg, _plan = self._compile(tmp_path, column, ["1.2.3.4", "5.6.7.8"])
        result = run_pipeline(
            cfg,
            {"t": pa.table({"c": ["1.2.3.4", "5.6.7.8", "1.2.3.4"]})},
            engine_version=ENGINE_VERSION,
            key_provider=key_provider(),
            auto_chunk=False,
        )
        values = result.outputs["t"].column("c").to_pylist()
        assert set(values) <= {"10.0.0.1", "10.0.0.2", "192.168.1.9"}
