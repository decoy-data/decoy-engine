"""F31 native canary (AE6): the compiled kernel and its Python translators never echo input text.

The Rust crate has 20 `PyErr::new_err` sites and the engine has five translators that copy the
compiled error detail into a Python exception. Nothing but a convention ("redacted-error
contract": `code: detail`) kept the detail value-free. Each cell here plants `CANARY` where an
input reaches a native error (a cell value, an Arrow field name, a detector or validator name, a
namespace) and checks the raised error and the translated exception.

Needs the compiled companion. Run it in the lock-faithful venv (`venv-native-lock`): the gate
venvs do not install the companion, and this module skips there with a reason.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from typing import Any

import pyarrow as pa
import pytest

from tests.security._f31_canary import CANARY, exception_surfaces

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("decoy_engine_native") is None,
    reason="decoy-engine-native companion not installed; use venv-native-lock",
)

_KEY = b"\x01" * 32


def _kernel() -> Any:
    from decoy_engine_native import _kernel

    return _kernel


def _struct_with_canary_field() -> pa.Array:
    """An Arrow type the kernels do not admit, whose field name carries the marker."""
    return pa.array([{CANARY: 1}])


def _strings() -> pa.Array:
    return pa.array([CANARY, "abc"], pa.string())


def _derive(k: Any, values: Any, **over: Any) -> Any:
    args: dict[str, Any] = {"mask_key": _KEY, "namespace": "ns"} | over
    return k.derive_batch(values, **args)


def _index(k: Any, values: Any, **over: Any) -> Any:
    args: dict[str, Any] = {"mask_key": _KEY, "namespace": "ns", "pool_size": 10} | over
    return k.derive_index_batch(values, **args)


def _hex(k: Any, values: Any, **over: Any) -> Any:
    args: dict[str, Any] = {"mask_key": _KEY, "namespace": "ns", "hex_chars": 4} | over
    return k.derive_hex_raw_batch(values, **args)


def _fpe(k: Any, values: Any, **over: Any) -> Any:
    args: dict[str, Any] = {
        "mask_key": _KEY,
        "namespace": "ns",
        "tweak": b"t",
        "charset": "0123456789",
        "preserve_separators": True,
        "validate_luhn": False,
        "forward": True,
    } | over
    return k.fpe_transform_batch(values, **args)


# (id, callable, the exception type that proves the intended native site ran)
_RAISERS: list[tuple[str, Callable[[Any], Any], type[Exception]]] = [
    ("derive_unadmitted_type", lambda k: _derive(k, _struct_with_canary_field()), ValueError),
    ("derive_empty_namespace", lambda k: _derive(k, _strings(), namespace=""), ValueError),
    ("derive_bad_truncate", lambda k: _derive(k, _strings(), truncate=CANARY), TypeError),
    ("derive_bad_threads", lambda k: _derive(k, _strings(), native_threads=-1), ValueError),
    ("index_unadmitted_type", lambda k: _index(k, _struct_with_canary_field()), ValueError),
    ("index_pool_size_text", lambda k: _index(k, _strings(), pool_size=CANARY), TypeError),
    ("hex_unadmitted_type", lambda k: _hex(k, _struct_with_canary_field()), ValueError),
    ("hex_odd_chars", lambda k: _hex(k, _strings(), hex_chars=3), ValueError),
    ("fpe_unadmitted_type", lambda k: _fpe(k, _struct_with_canary_field()), ValueError),
    ("fpe_empty_namespace", lambda k: _fpe(k, _strings(), namespace=""), ValueError),
    ("fpe_bad_threads", lambda k: _fpe(k, _strings(), native_threads=-1), ValueError),
    (
        "redact_unknown_detector",
        lambda k: k.text_redact_candidates([CANARY], [CANARY], k.text_redact_catalog_version()),
        ValueError,
    ),
    ("redact_catalog_mismatch", lambda k: k.text_redact_candidates([CANARY], [], -1), ValueError),
    ("redact_unknown_validator", lambda k: k.text_redact_validate(CANARY, CANARY), ValueError),
    ("redact_unknown_class", lambda k: k.text_redact_class_members(CANARY), ValueError),
    (
        "mask_unknown_detector",
        lambda k: k.text_mask_detect_splice(
            [CANARY], [CANARY], [False], "x", False, k.text_redact_catalog_version()
        ),
        ValueError,
    ),
    (
        "mask_verbatim_mismatch",
        lambda k: k.text_mask_detect_splice(
            [CANARY], [], [True], "x", False, k.text_redact_catalog_version()
        ),
        ValueError,
    ),
    (
        "mask_catalog_mismatch",
        lambda k: k.text_mask_detect_splice([CANARY], [], [], "x", False, -1),
        ValueError,
    ),
    (
        "mask_spans_short",
        lambda k: k.text_mask_splice_spans([CANARY, "b"], [[]], "x", False),
        ValueError,
    ),
]

# Sites that echo a caller-supplied identifier. The identifier is a detector id, validator name
# or class name from config, not a row value; no open F31 slice covers these sites.
_NAME_ECHO = {
    "redact_unknown_detector": "pyboundary.rs:48",
    "redact_unknown_validator": "pyboundary.rs:151",
    "redact_unknown_class": "pyboundary.rs:174",
    "mask_unknown_detector": "text_mask.rs:219",
}

# The Arrow type's Debug text carries struct field names, which come from the data schema.
_TYPE_ECHO = {
    "derive_unadmitted_type": "batch/string.rs:53",
    "index_unadmitted_type": "batch/index.rs:93",
}


def _xfail(reason: str) -> Any:
    return pytest.mark.xfail(strict=True, reason=reason)


def _param(name: str, raiser: Callable[[Any], Any], exc: type[Exception]) -> Any:
    marks = []
    if name in _NAME_ECHO:
        reason = f"finding AE6-F1: {_NAME_ECHO[name]} formats the caller's name into the error"
        marks.append(pytest.mark.xfail(strict=True, reason=reason))
    if name in _TYPE_ECHO:
        reason = f"finding AE6-F2: {_TYPE_ECHO[name]} formats the Arrow type, field names included"
        marks.append(pytest.mark.xfail(strict=True, reason=reason))
    return pytest.param(raiser, exc, id=name, marks=marks)


_PARAMS = [_param(*entry) for entry in _RAISERS]


@pytest.mark.parametrize(("raiser", "exc_type"), _PARAMS)
def test_native_error_carries_no_input_text(
    raiser: Callable[[Any], Any], exc_type: type[Exception]
) -> None:
    with pytest.raises(exc_type) as raised:
        raiser(_kernel())
    surfaces = exception_surfaces(raised.value)
    leaked = sorted(key for key, text in surfaces.items() if CANARY in text)
    assert not leaked, f"marker reached {leaked}"


def _native_value_error(raiser: Callable[[Any], Any]) -> ValueError:
    with pytest.raises(ValueError) as raised:
        raiser(_kernel())
    return raised.value


@pytest.mark.parametrize(
    ("module", "translator", "raiser"),
    [
        pytest.param(
            "decoy_engine.execution.native._crypto_ext",
            "_translate_compiled_kernel_error",
            lambda k: _derive(k, _struct_with_canary_field()),
            marks=_xfail(
                "finding AE6-F2: batch/string.rs:53 formats the Arrow type; the translator copies it"
            ),
        ),
        pytest.param(
            "decoy_engine.execution.native._index_ext",
            "_translate_compiled_index_kernel_error",
            lambda k: _index(k, _struct_with_canary_field()),
            marks=_xfail(
                "finding AE6-F2: batch/index.rs:93 formats the Arrow type; the translator copies it"
            ),
        ),
        (
            "decoy_engine.execution.native._group_key_ext",
            "_translate_compiled_raw_hex_kernel_error",
            lambda k: _hex(k, _strings(), hex_chars=3),
        ),
        (
            "decoy_engine.execution.native._fpe_ext",
            "_translate_compiled_fpe_error",
            lambda k: _fpe(k, _struct_with_canary_field()),
        ),
    ],
    ids=["crypto", "index", "group_key", "fpe"],
)
def test_translator_output_carries_no_input_text(
    module: str, translator: str, raiser: Callable[[Any], Any]
) -> None:
    mod = importlib.import_module(module)
    translated = getattr(mod, translator)(_native_value_error(raiser))
    surfaces = exception_surfaces(translated)
    leaked = sorted(key for key, text in surfaces.items() if CANARY in text)
    assert not leaked, f"marker reached {leaked}"


def test_text_mask_translator_carries_no_value() -> None:
    from decoy_engine.errors import FpeUnencryptableError
    from decoy_engine.execution.native._text_mask_route import text_mask_fail_closed_error
    from decoy_engine.transforms.fpe import fpe_encrypt_value

    with pytest.raises(FpeUnencryptableError) as raised:
        fpe_encrypt_value(CANARY, _KEY, "0123456789", b"t", False)
    translated = text_mask_fail_closed_error(raised.value, "col")
    surfaces = exception_surfaces(translated)
    leaked = sorted(key for key, text in surfaces.items() if CANARY in text)
    assert not leaked, f"marker reached {leaked}"
