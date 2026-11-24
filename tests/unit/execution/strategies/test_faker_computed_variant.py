"""GEN-NONFAKER-DRAWS S2 review fixes: one live variant decision, one output type, one kernel rule.

Each class pins one finding of the first review of the S2 PR:

- `TestLiveVariant`: every route reads the same variant from the live registry, so a rebound
  provider (`ProviderRegistry.override`) takes the same draw everywhere.
- `TestAllNullSchema`: an all-null computed column is Arrow `string` on every route.
- `TestKernelBinding`: admission binds and self-tests the kernel the resolved variant runs, so a
  broken hash kernel never fails a run that its index kernel admitted.
- `TestOneDeterministicDraw`: the two native routes share one deterministic batch operation.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

import pyarrow as pa
import pytest

from decoy_engine import ConfigError
from decoy_engine.execution import _faker_degenerate_pin as pin
from decoy_engine.execution._operator_registry import PYTHON_SCALAR, RUST_COMPANION
from decoy_engine.execution.native._crypto_ext import CryptoExtensionUnavailableError
from decoy_engine.execution.native._provider_class import (
    computed_mask_spec,
    resolve_faker_variant,
)
from decoy_engine.execution.native._real_type_admission import faker_provider_decline
from decoy_engine.providers_v2 import get_default_registry
from tests.native._chunked_entry_support import COMPANION_PRESENT
from tests.unit.execution.strategies.test_faker_computed import (
    CHOICE_KW,
    TestRelationshipRoutes,
)
from tests.unit.execution.strategies.test_faker_computed_routes import (
    _column,
    _seed,
)

_DEFAULT = get_default_registry()
needs_companion = pytest.mark.skipif(not COMPANION_PRESENT, reason="needs the native companion")
OOC_POOL = "out_of_core_faker_pool_unsupported"


def _rebound(provider: str, like: str, *, adapter_of: str | None = None) -> Any:
    """The default registry with `provider` rebound to `like`'s capabilities and adapter."""
    caps = _DEFAULT.get_capabilities(like).model_copy(update={"provider": provider})
    return _DEFAULT.override(provider, _DEFAULT.get_adapter(adapter_of or like), caps)


def uuid_as_pool() -> Any:
    """`uuid` rebound to a poolable string provider: the name says computed, the binding says pool."""
    return _rebound("uuid", "person_first_name")


def lorem_as_computed() -> Any:
    """`lorem_text` rebound to a computed capability the engine has no descriptor for."""
    return _rebound("lorem_text", "uuid")


class _Routes(TestRelationshipRoutes):
    """The relationship fixture, with the source column replaceable."""

    def run(self, tmp_path: Path, column: dict[str, Any], **kw: Any) -> Any:
        cfg = self._config(tmp_path, key_provider_name=None, column=column)
        return self._run(copy.deepcopy(cfg), **kw)


class TestLiveVariant:
    """Finding 1: the variant comes from the live binding, not the provider name."""

    def test_the_stock_registry_resolves_by_capability(self) -> None:
        assert resolve_faker_variant("uuid", {}).kind == "computed"
        assert resolve_faker_variant("random_choice", CHOICE_KW).kind == "computed"
        assert resolve_faker_variant("person_email", {}).kind == "pool"
        assert resolve_faker_variant("lorem_text", {}).kind == "pool"

    def test_a_pool_rebinding_of_a_computed_name_is_a_pool(self) -> None:
        assert resolve_faker_variant("uuid", {}, uuid_as_pool()).kind == "pool"
        assert computed_mask_spec("uuid", {}, uuid_as_pool()) is None

    def test_a_computed_rebinding_without_a_descriptor_is_unsupported(self) -> None:
        variant = resolve_faker_variant("lorem_text", {}, lorem_as_computed())
        assert variant.kind == "unsupported" and variant.spec is None

    def test_every_route_verdict_follows_the_rebinding(self) -> None:
        for runs_computed in (True, False):
            assert faker_provider_decline(
                "f", "uuid", {}, runs_computed=runs_computed, registry=uuid_as_pool()
            ) == ("faker_provider_not_native:f:uuid", mock.ANY)
            assert faker_provider_decline(
                "f", "lorem_text", {}, runs_computed=runs_computed, registry=lorem_as_computed()
            ) == ("faker_provider_not_native:f:lorem_text", mock.ANY)

    def test_a_stock_only_route_declines_any_rebinding_that_changes_the_variant(self) -> None:
        assert faker_provider_decline("f", "uuid", {}, runs_computed=True, stock_only=True) is None
        assert faker_provider_decline(
            "f", "uuid", {}, runs_computed=True, registry=uuid_as_pool(), stock_only=True
        )

    def test_the_sequential_run_reads_the_rebinding(self, tmp_path) -> None:
        """`uuid` rebound to a pool provider masks with pool values on full-frame and sequential
        alike, and the sequential kernels run the pool leg."""
        helper = _Routes()
        column = _column("uuid", {}, deterministic=True)
        whole = helper.run(
            tmp_path, column, registry=uuid_as_pool(), execution_mode="full_frame", auto_chunk=False
        )
        seq = helper.run(tmp_path, column, registry=uuid_as_pool(), execution_mode="sequential")
        assert seq.outputs["t"].equals(whole.outputs["t"])
        stock = helper.run(tmp_path, column, execution_mode="full_frame", auto_chunk=False)
        # The rebinding draws from a pool; the stock `uuid` keys its value from the source.
        assert not seq.outputs["t"].equals(stock.outputs["t"])

    def test_the_out_of_core_route_declines_a_rebinding_instead_of_drawing_uuids(
        self, tmp_path
    ) -> None:
        helper = _Routes()
        column = _column("uuid", {}, deterministic=True)
        with pytest.raises(ConfigError, match=OOC_POOL):
            helper.run(tmp_path, column, registry=uuid_as_pool(), execution_mode="out_of_core")

    def test_a_computed_rebinding_without_a_descriptor_fails_alike_on_every_route(
        self, tmp_path
    ) -> None:
        helper = _Routes()
        column = _column("lorem_text", {"pool_size": 50}, deterministic=True)
        registry = lorem_as_computed()
        errors = []
        for mode in ("full_frame", "sequential"):
            with pytest.raises(Exception) as exc:
                helper.run(tmp_path, column, registry=registry, execution_mode=mode)
            errors.append(type(exc.value))
        assert errors[0] is errors[1]
        with pytest.raises(ConfigError, match=OOC_POOL):
            helper.run(tmp_path, column, registry=registry, execution_mode="out_of_core")


class _AllNull(_Routes):
    @classmethod
    def _tables(cls) -> tuple[pa.Table, pa.Table]:
        parent, child = super()._tables()
        nulls = pa.array([None] * parent.num_rows, pa.string())
        return parent.set_column(parent.schema.get_field_index("f"), "f", nulls), child


class TestAllNullSchema:
    """Finding 2: the draw owns the output type, so a column of nulls is still `string`."""

    @pytest.mark.parametrize("deterministic", [True, False], ids=["deterministic", "positional"])
    @pytest.mark.parametrize(("provider", "config"), [("uuid", {}), ("random_choice", CHOICE_KW)])
    def test_the_schema_is_equal_on_every_route(
        self, provider, config, deterministic, tmp_path
    ) -> None:
        helper = _AllNull()
        column = _column(provider, config, deterministic=deterministic)
        whole = helper.run(tmp_path, column, execution_mode="full_frame", auto_chunk=False)
        seq = helper.run(tmp_path, column, execution_mode="sequential")
        assert whole.outputs["t"].schema.field("f").type == pa.string()
        assert seq.outputs["t"].schema == whole.outputs["t"].schema
        assert seq.outputs["t"].column("f").null_count == whole.outputs["t"].num_rows
        if deterministic:
            forced = helper.run(tmp_path, column, execution_mode="out_of_core")
            assert forced.outputs["t"].schema == whole.outputs["t"].schema

    def test_the_pin_covers_a_computed_string_draw_over_any_source(self) -> None:
        schema = pa.schema([("f", pa.string()), ("n", pa.int64())])
        config = {
            "tables": [
                {
                    "name": "t",
                    "columns": [
                        {"name": "f", "strategy": "faker", "provider": "uuid"},
                        {
                            "name": "n",
                            "strategy": "faker",
                            "provider": "random_int_range",
                            "provider_config": {"min": 1, "max": 9},
                        },
                    ],
                }
            ]
        }
        assert pin.deterministic_faker_pin_columns(config, "t", schema) == {"f"}


@contextmanager
def _hash_kernel_fails() -> Iterator[None]:
    """The compiled hash kernel fails its self-test; the index kernel is untouched."""
    boom = CryptoExtensionUnavailableError("injected self-test failure")
    with (
        mock.patch(
            "decoy_engine.execution.sequential._faker_admission.load_compiled_crypto_kernel",
            side_effect=boom,
        ),
        mock.patch(
            "decoy_engine.execution.out_of_core._hash_run.load_compiled_crypto_kernel",
            side_effect=boom,
        ),
        mock.patch(
            "decoy_engine.execution.native._kernels_keyed.load_compiled_crypto_kernel",
            side_effect=boom,
        ),
    ):
        yield


class TestKernelBinding:
    """Finding 3: a column is admitted on the kernel its variant runs, not on a sibling kernel."""

    def test_a_uuid_declines_at_sequential_admission_when_the_hash_kernel_is_missing(self) -> None:
        from decoy_engine.execution.sequential._faker_admission import (
            BoundFakerKernels,
            faker_admit,
        )

        index = mock.sentinel.index
        bound = BoundFakerKernels(index, None, None)
        seed = _seed("uuid", {})
        assert faker_admit("f", pa.string(), seed, bound=bound) == "crypto_extension_unavailable"
        assert (
            faker_admit("f", pa.string(), seed, bound=BoundFakerKernels(index, None, mock.Mock()))
            is None
        )
        choice = _seed("random_choice", CHOICE_KW)
        assert faker_admit("f", pa.string(), choice, bound=bound) is None

    @needs_companion
    @pytest.mark.parametrize("deterministic", [True, False], ids=["deterministic", "positional"])
    def test_the_sequential_run_survives_a_failing_hash_kernel(
        self, deterministic, tmp_path
    ) -> None:
        helper = _Routes()
        column = _column("uuid", {}, deterministic=deterministic)
        whole = helper.run(tmp_path, column, execution_mode="full_frame", auto_chunk=False)
        with _hash_kernel_fails():
            seq = helper.run(tmp_path, column, execution_mode="sequential")
        assert seq.outputs["t"].equals(whole.outputs["t"])
        [entry] = [e for e in seq.quality_metrics["sequential_faker"] if e["column"] == "f"]
        assert entry["executed_backend"] == PYTHON_SCALAR and entry["native_calls"] == 0, entry

    @needs_companion
    def test_a_choice_column_keeps_its_index_kernel_when_the_hash_kernel_fails(
        self, tmp_path
    ) -> None:
        helper = _Routes()
        column = _column("random_choice", CHOICE_KW, deterministic=True)
        with _hash_kernel_fails():
            seq = helper.run(tmp_path, column, execution_mode="sequential")
        [entry] = [e for e in seq.quality_metrics["sequential_faker"] if e["column"] == "f"]
        assert entry["executed_backend"] == RUST_COMPANION, entry

    @needs_companion
    def test_the_out_of_core_run_survives_a_failing_hash_kernel(self, tmp_path) -> None:
        """The reference hash is byte-identical, so the run completes with the same values and
        records the backend that ran."""
        helper = _Routes()
        column = _column("uuid", {}, deterministic=True)
        whole = helper.run(tmp_path, column, execution_mode="full_frame", auto_chunk=False)
        with _hash_kernel_fails():
            forced = helper.run(tmp_path, column, execution_mode="out_of_core")
        assert forced.outputs["t"].equals(whole.outputs["t"])
        entries = [e for e in forced.quality_metrics["out_of_core_faker"] if e["column"] == "f"]
        assert entries and all(e["executed_backend"] == PYTHON_SCALAR for e in entries), entries


class TestOneDeterministicDraw:
    """Finding 4: the namespace, the uuid-or-choice branch and the hash width live in one place."""

    ROOT = Path(__file__).resolve().parents[4] / "src" / "decoy_engine" / "execution"

    @pytest.mark.parametrize(
        "route", ["sequential/_computed_faker.py", "out_of_core/_faker_native.py"]
    )
    def test_a_route_calls_the_shared_operation_and_keeps_no_copy(self, route) -> None:
        text = (self.ROOT / route).read_text()
        assert "deterministic_computed_array" in text
        for private in ("uuid_from_hex", "hash_array", "native_keyed_hash", "UUID_HEX"):
            assert private not in text.replace("keyed_uuid_array", ""), (route, private)

    def test_the_shared_operation_is_reached_through_a_package_api(self) -> None:
        text = (self.ROOT / "sequential/_computed_faker.py").read_text()
        assert "execution.native.draw import" in text
        strategy = (self.ROOT / "_strategies/_faker.py").read_text()
        assert "execution.sequential import computed_faker_column" in strategy
        assert "sequential._computed_faker" not in strategy

    def test_the_two_routes_draw_equal_bytes(self, tmp_path) -> None:
        helper = _Routes()
        for provider, config in (("uuid", {}), ("random_choice", CHOICE_KW)):
            column = _column(provider, config, deterministic=True)
            seq = helper.run(tmp_path, column, execution_mode="sequential")
            forced = helper.run(tmp_path, column, execution_mode="out_of_core")
            assert forced.outputs["t"].equals(seq.outputs["t"]), provider
