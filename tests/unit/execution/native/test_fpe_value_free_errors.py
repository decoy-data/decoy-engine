"""Configured fpe values never appear in an error: charset and checksum scheme (canary tests).

A custom charset or a scheme string is customer configuration. Each error path keeps the field
name and the reason code and drops the value, whichever layer raises it.
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import run_mask_chunked
from decoy_engine.execution.native._crypto_ext import FpeConfig, FpeConfigError
from decoy_engine.execution.native._fpe_ext import _CompiledFpeKernel
from decoy_engine.plan._checks_fpe import check_fpe_charset_config, check_fpe_checksum_scheme
from decoy_engine.transforms.fpe import fpe_encrypt_value
from tests.native._chunked_entry_support import ENGINE_VERSION, TABLE, key_provider, make_config

DUP = "CQZ9CQZ9"  # a duplicate-symbol charset that is plain printable ASCII
ONE = "Q"  # one distinct symbol: degenerate, no duplicate
SCHEME = "CANARYSCHEME"
NS = "people.ssn"


def _raw(**provider_config: Any) -> dict[str, Any]:
    col = {"name": "c", "strategy": "fpe", "namespace": NS, "provider_config": provider_config}
    return {"tables": [{"name": TABLE, "columns": [col]}]}


def _text(exc: BaseException) -> str:
    return f"{exc} {exc!r} {getattr(exc, 'message', '')}"


def _clean(exc: BaseException, *values: str) -> None:
    for value in values:
        assert value not in _text(exc), value


@pytest.mark.parametrize("charset", [DUP, ONE])
def test_plan_charset_errors_carry_no_charset(charset: str) -> None:
    with pytest.raises(Exception) as info:
        check_fpe_charset_config(_raw(charset=charset, checksum="luhn"))
    _clean(info.value, charset, charset[:3])


def test_plan_unknown_scheme_error_carries_no_scheme() -> None:
    with pytest.raises(Exception) as info:
        check_fpe_checksum_scheme(_raw(checksum=SCHEME))
    _clean(info.value, SCHEME)


def test_plan_incompatible_charset_error_carries_no_charset() -> None:
    with pytest.raises(Exception) as info:
        check_fpe_checksum_scheme(_raw(checksum="vin", charset="QZ9"))
    _clean(info.value, "QZ9")


@pytest.mark.parametrize("charset", [DUP, ONE])
def test_kernel_config_errors_carry_no_charset(charset: str) -> None:
    with pytest.raises(FpeConfigError) as info:
        FpeConfig.from_mapping({"charset": charset, "checksum": "luhn"})._resolve()
    _clean(info.value, charset)


def test_direct_kernel_call_with_a_bad_charset_carries_no_charset() -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("the FFI must not be reached")

    kernel = _CompiledFpeKernel(boom)
    cfg = FpeConfig.from_mapping({"charset": DUP, "checksum": "luhn"})
    with pytest.raises(Exception) as info:
        kernel.encrypt_batch(
            pa.array(["79927398713"]),
            mask_key=b"k" * 32,
            namespace="ns",
            tweak_column="c",
            config=cfg,
        )
    _clean(info.value, DUP)


def test_chunked_job_with_a_duplicate_charset_carries_no_charset() -> None:
    config = make_config(
        [
            {
                "name": "c",
                "strategy": "fpe",
                "namespace": NS,
                "provider_config": {"charset": DUP, "checksum": "luhn"},
            }
        ]
    )
    chunks = [pa.table({"c": pa.array(["79927398713"], pa.string())})]
    with pytest.raises(Exception) as info:
        list(
            run_mask_chunked(
                config,
                chunks,
                table=TABLE,
                engine_version=ENGINE_VERSION,
                key_provider=key_provider(),
            )
        )
    _clean(info.value, DUP)


def test_oracle_invalid_check_digit_error_carries_neither_value_nor_scheme() -> None:
    source = "79927398710"  # fails the Luhn check
    with pytest.raises(Exception) as info:
        fpe_encrypt_value(source, b"k" * 32, "0123456789", b"t", True, False, "luhn")
    _clean(info.value, source, "luhn")
