"""One FPE scheme classification, shared by plan compile, runtime and unmask.

`checksums.classify_fpe_scheme` separates "recognized" from "supported for FPE". The three
callers keep their own error codes, so this pins the verdicts and that they agree on each
scheme for populated and all-null columns.
"""

from __future__ import annotations

import pyarrow as pa
import pytest

from decoy_engine import checksums, unmask_pipeline
from decoy_engine.errors import FpeChecksumError
from decoy_engine.execution import ExecutionError
from decoy_engine.plan._checks import check_fpe_checksum_scheme
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.transforms.fpe import fpe_encrypt_value
from tests.unit.test_unmask import _config, _fpe_col

_SCHEMES = ["luhn", "npi", "vin", "isbn13", "ean13", "gtin", "iban", "nope"]
_EXPECTED = {
    "luhn": "supported",
    "npi": "supported",
    "vin": "supported",
    "isbn13": "supported",
    "ean13": "supported",
    "gtin": "supported",
    "iban": "unsupported",
    "nope": "unknown",
}


@pytest.mark.parametrize("scheme", _SCHEMES)
def test_classification_verdicts(scheme: str) -> None:
    assert checksums.classify_fpe_scheme(scheme) == _EXPECTED[scheme]


@pytest.mark.parametrize("bad", [None, 5, ["luhn"], b"luhn", ("luhn",)])
def test_a_non_string_scheme_is_unknown(bad: object) -> None:
    assert checksums.classify_fpe_scheme(bad) == "unknown"


def _plan_refuses(scheme: str) -> bool:
    raw = {
        "tables": [
            {
                "name": "t",
                "columns": [
                    {
                        "name": "c",
                        "strategy": "fpe",
                        "provider_config": {"checksum": scheme, "charset": "alphanum"},
                    }
                ],
            }
        ]
    }
    try:
        check_fpe_checksum_scheme(raw)
    except PlanCompileError as exc:
        return exc.code in ("fpe_checksum_unknown_scheme", "fpe_checksum_iban_unsupported")
    return False


def _runtime_refuses(scheme: str) -> bool:
    try:
        fpe_encrypt_value("1234567893", b"k" * 32, "0123456789", b"t", True, False, scheme)
    except FpeChecksumError as exc:
        return exc.code != "fpe.checksum_invalid_source" and "fixed length" not in str(exc)
    return False


def _unmask_refuses(scheme: str, values: list[str | None], tmp_path) -> bool:
    cfg = _config(tmp_path, [_fpe_col("acct")])
    cfg["tables"][0]["columns"][0]["provider_config"]["checksum"] = scheme
    masked = {"accounts": pa.table({"acct": pa.array(values, pa.string())})}
    try:
        unmask_pipeline(cfg, masked)
    except ExecutionError as exc:
        return exc.code == "fpe.checksum_unsupported"
    except FpeChecksumError:
        return False  # a supported scheme reached the cipher and refused this value's length
    return False


@pytest.mark.parametrize(
    "values", [["1234567893"], [None, None], []], ids=["populated", "null", "empty"]
)
@pytest.mark.parametrize("scheme", _SCHEMES)
def test_every_caller_agrees_with_the_classification(scheme: str, values, tmp_path) -> None:
    refused = _EXPECTED[scheme] != "supported"
    assert _plan_refuses(scheme) is refused
    assert _unmask_refuses(scheme, values, tmp_path) is refused
    if values == ["1234567893"]:
        assert _runtime_refuses(scheme) is refused
