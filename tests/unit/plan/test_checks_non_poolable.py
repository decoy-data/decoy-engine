"""Row 11: non_poolable_provider_with_pool_backend (audit H5, 2026-06-12).

Pre-fix, `strategy: faker` on a provider with poolable=False (uuid,
lorem_text-style) passed every compile check and crashed at runtime with
PoolCapacityError[provider_not_poolable] -- which is exactly how 3 of
the 5 shipped CLI templates (hipaa/pci/gdpr) were dead-on-arrival while
`decoy validate` exited 0. These cells pin the compile-time rejection
and the config-only check API that lets `validate` catch it.
"""

from __future__ import annotations

import pytest

from decoy_engine.plan import PlanCompileError, run_config_only_checks
from decoy_engine.plan._checks import check_non_poolable_provider_with_pool_backend


def _cfg(columns: list[dict]) -> dict:
    return {"version": 2, "tables": [{"name": "t", "columns": columns}]}


class TestNonPoolableProviderWithPoolBackend:
    def test_faker_address_full_rejected(self):
        cfg = _cfg([{"name": "home", "strategy": "faker", "provider": "address_full"}])
        with pytest.raises(PlanCompileError) as exc:
            check_non_poolable_provider_with_pool_backend(cfg)
        assert exc.value.code == "non_poolable_provider_with_pool_backend"
        assert "home" in exc.value.message

    def test_faker_lorem_text_rejected_until_it_pools(self):
        cfg = _cfg([{"name": "notes", "strategy": "faker", "provider": "lorem_text"}])
        with pytest.raises(PlanCompileError) as exc:
            check_non_poolable_provider_with_pool_backend(cfg)
        assert exc.value.code == "non_poolable_provider_with_pool_backend"

    @pytest.mark.parametrize("provider", ["uuid", "random_int_range", "random_choice"])
    def test_faker_computed_draw_is_not_a_pool_refusal(self, provider):
        # A computed draw builds no pool, so poolable=False is not a reason to refuse it.
        cfg = _cfg([{"name": "device_id", "strategy": "faker", "provider": provider}])
        check_non_poolable_provider_with_pool_backend(cfg)  # no raise

    def test_faker_poolable_provider_passes(self):
        cfg = _cfg([{"name": "email", "strategy": "faker", "provider": "person_email"}])
        check_non_poolable_provider_with_pool_backend(cfg)  # no raise

    def test_non_faker_strategy_with_non_poolable_provider_passes(self):
        # hash does not route through the pool; uuid as a provider hint
        # on a keyed strategy is not this check's concern.
        cfg = _cfg([{"name": "id", "strategy": "hash", "provider": "uuid"}])
        check_non_poolable_provider_with_pool_backend(cfg)  # no raise

    def test_unknown_provider_is_not_this_checks_concern(self):
        cfg = _cfg([{"name": "x", "strategy": "faker", "provider": "no_such_provider"}])
        check_non_poolable_provider_with_pool_backend(cfg)  # row 2 owns it

    def test_malformed_entries_skipped(self):
        cfg = {"version": 2, "tables": [{"name": "t", "columns": ["junk", {"name": "a"}]}, "junk"]}
        check_non_poolable_provider_with_pool_backend(cfg)  # no raise


class TestShippedTemplateShapesCompile:
    """The three shipped-template column shapes the audit found dead on arrival (2026-06-12).

    They were refused at compile because a faker uuid column built a pool. A uuid is a computed
    draw now, so the same shapes compile and run (GEN-NONFAKER-DRAWS)."""

    @pytest.mark.parametrize(
        "column",
        [
            {"name": "vehicle_id", "strategy": "faker", "provider": "uuid"},  # hipaa
            {  # pci (also declared deterministic on a non-deterministic provider)
                "name": "transaction_id",
                "strategy": "faker",
                "provider": "uuid",
                "deterministic": True,
                "namespace": "transaction_identity",
            },
            {"name": "device_id", "strategy": "faker", "provider": "uuid"},  # gdpr
        ],
    )
    def test_template_shape_compiles(self, column):
        run_config_only_checks(_cfg([column]))


class TestRunConfigOnlyChecks:
    def test_clean_config_returns_check_names(self):
        cfg = _cfg([{"name": "email", "strategy": "faker", "provider": "person_email"}])
        names = run_config_only_checks(cfg)
        assert names == (
            "unknown_provider",
            "when_with_coherent_with",
            "deterministic_namespace_completeness",
            "non_poolable_provider_with_pool_backend",
            # Row 31 (DPS-3): dp generate-contract mutual exclusion.
            "dp_generate_contract",
            "statistical_columns",
            "text_redact_ner_available",
            "text_mask_ner_available",
            "vault_columns",
            "fpe_checksum_scheme",
            "derived_column_refs",
            "derived_aggregate_refs",
            "grouped_series_refs",
            "windowed_date_refs",
            "group_key_refs",
            # Row 27 (HC-3a): date_shift group_by (entity-anchor) column ref.
            "date_shift_group_by_refs",
            # Row 21 (SP-46): fpe_join_group structural validation.
            "fpe_join_groups",
            # Row 22 (Sprint 13 S3): truncate length/keep/mask_char validation.
            "truncate_config",
            # Row 23 (Sprint 13 S3, GATE-1 Q4): bucketize width resolution.
            "bucketize_config",
            # Row 28 (HC-3b): top_code bound resolution.
            "top_code_config",
            # Date-format guard: bucket_perturb date_format must write a date back.
            "bucket_perturb_config",
            # Row 24 (Sprint 13 S3, GATE-1 Q4): categorical categories shape.
            "categorical_categories",
            # Row 25 (Sprint 2 honesty pack, S6, GATE-1 Q4): fpe charset resolution.
            "fpe_charset_config",
            # Row 26 (DE-03): faker-without-provider rejection.
            "faker_requires_provider",
            # E-F0: text_mask detector ids and strategy pairs, tail-appended.
            "text_mask_strategies",
        )

    def test_raises_on_unknown_provider(self):
        cfg = _cfg([{"name": "x", "strategy": "faker", "provider": "no_such_provider"}])
        with pytest.raises(PlanCompileError) as exc:
            run_config_only_checks(cfg)
        assert exc.value.code == "unknown_provider"

    def test_raises_on_non_poolable_pool_backend(self):
        cfg = _cfg([{"name": "home", "strategy": "faker", "provider": "address_full"}])
        with pytest.raises(PlanCompileError) as exc:
            run_config_only_checks(cfg)
        assert exc.value.code == "non_poolable_provider_with_pool_backend"

    def test_raises_on_when_with_coherent_with(self):
        cfg = _cfg(
            [
                {
                    "name": "a",
                    "strategy": "faker",
                    "provider": "person_email",
                    "when": "b > 1",
                    "coherent_with": ["c"],
                }
            ]
        )
        with pytest.raises(PlanCompileError) as exc:
            run_config_only_checks(cfg)
        assert exc.value.code == "when_with_coherent_with_unsupported"

    def test_check_set_is_subset_of_compile_plan(self):
        # Drift guard between the two surfaces: every config-only check
        # must exist in compile_plan's full checks_passed contract.
        from tests.unit.plan.test_compile_s2_refactor import EXPECTED_S2_CHECKS_PASSED

        cfg = _cfg([{"name": "email", "strategy": "faker", "provider": "person_email"}])
        names = set(run_config_only_checks(cfg))
        full = set(EXPECTED_S2_CHECKS_PASSED) | {"when_with_coherent_with"}
        assert names <= full
