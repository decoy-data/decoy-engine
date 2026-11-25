"""The one fpe checksum decision (FPE-CHECKSUM-NATIVE S1).

Every route, the wrapper backstop and the unified binding ask `fpe_checksum_rejection`. S1 ships
the registry field empty, so every configured scheme still declines. The tests that need a
scheme to pass the registry clause patch a populated copy of the fpe spec, which is what S2b
will ship.
"""

from __future__ import annotations

import dataclasses
from types import MappingProxyType
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.execution import _operator_registry as registry
from decoy_engine.execution import _sequential_native_ops as seq
from decoy_engine.execution.native import _operator_config_rejections as rej
from decoy_engine.execution.native import fpe_checksum_config_rejection
from decoy_engine.execution.native._crypto_ext import FpeConfig
from decoy_engine.execution.native._fpe_ext import _CompiledFpeKernel
from decoy_engine.execution.out_of_core import _fpe_native as ooc
from decoy_engine.plan._types import ColumnSeed

SCHEMES = ("luhn", "npi", "ean13", "gtin", "isbn13", "vin")
DECLINE = "fpe_checksum_not_native:c"


@pytest.fixture
def populated(monkeypatch: pytest.MonkeyPatch) -> None:
    """The registry as S2b ships it: the six schemes listed."""
    spec = dataclasses.replace(registry.OPERATORS["fpe"], checksum_schemes=frozenset(SCHEMES))
    monkeypatch.setattr(rej, "OPERATORS", MappingProxyType({**registry.OPERATORS, "fpe": spec}))


def _seed(config: dict[str, Any], namespace: str | None = "ns") -> ColumnSeed:
    return ColumnSeed(
        namespace=namespace,
        strategy="fpe",
        provider="fpe",
        backend_type="faker",
        backend_version="v",
        cardinality_mode="reuse",
        deterministic=True,
        provider_config=tuple(config.items()),
        coherent_with=(),
    )


def test_registry_field_is_empty_in_s1() -> None:
    assert registry.OPERATORS["fpe"].checksum_schemes == frozenset()


@pytest.mark.parametrize("scheme", SCHEMES)
def test_every_scheme_declines_while_registry_is_empty(scheme: str) -> None:
    got = rej.fpe_checksum_rejection("c", scheme, "0123456789", context="payload")
    assert got == DECLINE


@pytest.mark.parametrize("empty", [None, ""])
def test_absent_scheme_passes(empty: str | None) -> None:
    assert rej.fpe_checksum_rejection("c", empty, "0123456789", context="payload") is None
    assert fpe_checksum_config_rejection("c", {"checksum": empty}, context="key") is None
    assert fpe_checksum_config_rejection("c", {}, context="payload") is None


@pytest.mark.usefixtures("populated")
class TestPopulatedRegistry:
    @pytest.mark.parametrize("scheme", SCHEMES)
    def test_digit_charset_passes_on_payload(self, scheme: str) -> None:
        assert rej.fpe_checksum_rejection("c", scheme, "0123456789", context="payload") is None
        # reversed order is still ASCII digits
        assert rej.fpe_checksum_rejection("c", scheme, "9876543210", context="payload") is None

    @pytest.mark.parametrize("scheme", SCHEMES)
    def test_key_context_declines_even_with_an_eligible_alphabet(self, scheme: str) -> None:
        assert rej.fpe_checksum_rejection("c", scheme, "0123456789", context="key") == DECLINE

    def test_unlisted_scheme_declines(self) -> None:
        assert rej.fpe_checksum_rejection("c", "iban", "0123456789", context="payload") == DECLINE

    @pytest.mark.parametrize("charset", ["0123456789-", "-0123456789", "01234567ab", ""])
    def test_numeric_scheme_checks_every_charset_symbol(self, charset: str) -> None:
        # A dash or letter anywhere in the charset, not only first, declines.
        assert rej.fpe_checksum_rejection("c", "npi", charset, context="payload") == DECLINE

    def test_vin_admits_ascii_alphanumerics_only(self) -> None:
        full = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        assert rej.fpe_checksum_rejection("c", "vin", full, context="payload") is None
        assert rej.fpe_checksum_rejection("c", "vin", full + "-", context="payload") == DECLINE
        assert rej.fpe_checksum_rejection("c", "vin", "0123456789Å", context="payload") == (DECLINE)

    def test_config_adapter_resolves_named_and_literal_charsets(self) -> None:
        assert fpe_checksum_config_rejection("c", {"checksum": "luhn"}, context="payload") is None
        cfg = {"checksum": "npi", "charset": "alphanum"}
        assert fpe_checksum_config_rejection("c", cfg, context="payload") == DECLINE
        cfg = {"checksum": "luhn", "charset": "0123456789"}
        assert fpe_checksum_config_rejection("c", cfg, context="payload") is None
        assert fpe_checksum_config_rejection("c", {"checksum": "luhn"}, context="key") == DECLINE

    def test_non_string_charset_declines_without_raising(self) -> None:
        cfg = {"checksum": "luhn", "charset": ["0", "1"]}
        assert fpe_checksum_config_rejection("c", cfg, context="payload") == DECLINE


@pytest.mark.parametrize(
    "admit",
    [
        pytest.param(lambda cfg, ns, typ: seq._fpe_admit("c", typ, _seed(cfg, ns)), id="seq"),
        pytest.param(
            lambda cfg, ns, typ: ooc.decline_reason("c", pa.schema([("c", typ)]), _seed(cfg, ns))[
                1
            ],
            id="ooc",
        ),
    ],
)
class TestSequentialAndOutOfCorePrecedence:
    def test_checksum_wins_over_namespace_config_and_type(self, admit: Any) -> None:
        cfg = {"checksum": "luhn", "charset": "aab"}
        assert admit(cfg, None, pa.int64()) == DECLINE

    def test_empty_registry_declines_a_valid_checksum_payload(self, admit: Any) -> None:
        assert admit({"checksum": "luhn"}, "ns", pa.string()) == DECLINE

    @pytest.mark.usefixtures("populated")
    def test_eligible_checksum_payload_is_not_declined(self, admit: Any) -> None:
        assert admit({"checksum": "luhn"}, "ns", pa.string()) is None

    @pytest.mark.usefixtures("populated")
    def test_namespace_then_config_then_type_after_the_checksum_passes(self, admit: Any) -> None:
        dup = {"checksum": "luhn", "charset": "00123456789"}
        assert admit(dup, None, pa.string()) == "fpe_requires_namespace_stays_python:c"
        assert admit(dup, "ns", pa.string()) == "fpe_config_stays_python:c"
        assert admit({"checksum": "luhn"}, "ns", pa.int64()) == (
            f"fpe_source_type_not_string:c:{pa.int64()}"
        )


@pytest.mark.usefixtures("populated")
def test_sequential_key_context_declines_a_checksum_key() -> None:
    seed = _seed({"checksum": "luhn"})
    assert seq._fpe_key_admit("c", pa.string(), seed) == DECLINE
    assert seq._fpe_key_admit("c", pa.int64(), seed) == DECLINE
    assert seq._fpe_key_admit("c", pa.string(), _seed({})) is None


def test_wrapper_refuses_a_checksum_config_before_the_ffi() -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("the FFI must not be reached")

    kernel = _CompiledFpeKernel(boom)
    cfg = FpeConfig.from_mapping({"checksum": "luhn"})
    for call in (kernel.encrypt_batch, kernel.decrypt_batch):
        with pytest.raises(ValueError) as info:
            call(
                pa.array(["79927398713"]),
                mask_key=b"k" * 32,
                namespace="ns",
                tweak_column="secret_col",
                config=cfg,
            )
        # the code only: no column name, no value
        assert str(info.value) == "fpe_checksum_not_native"


@pytest.mark.usefixtures("populated")
def test_wrapper_forwards_an_admitted_checksum_config_to_the_ffi() -> None:
    seen: list[dict[str, Any]] = []

    def fake(array: Any, **kwargs: Any) -> tuple[Any, list[Any]]:
        seen.append(kwargs)
        return array, []

    kernel = _CompiledFpeKernel(fake)
    kernel.encrypt_batch(
        pa.array(["79927398713"]),
        mask_key=b"k" * 32,
        namespace="ns",
        tweak_column="c",
        config=FpeConfig.from_mapping({"checksum": "luhn"}),
    )
    assert len(seen) == 1


@pytest.mark.parametrize("scheme", [["luhn"], {"luhn": 1}, {"luhn"}, 7])
def test_a_malformed_non_string_scheme_declines_coded_not_raises(
    populated: None, scheme: Any
) -> None:
    """An unhashable or non-string scheme is malformed config. The decision keeps the coded
    decline it gave before the registry check existed, instead of raising `TypeError`."""
    assert fpe_checksum_config_rejection("c", {"checksum": scheme}, context="payload") == DECLINE
