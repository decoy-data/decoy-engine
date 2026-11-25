"""F31 native canary (AE6): the compiled kernel and its Python translators never echo input text.

The Rust crate has 20 `PyErr::new_err` sites. The 19 cells below reach 14 of them. The other 6
are four panic catches and two Arrow export failures, which no caller can trigger through the
API. The engine has five translators that copy the compiled error detail into a Python
exception. Only a convention (the "redacted-error contract": `code: detail`) keeps that detail
value-free. Each cell plants `CANARY` where an input reaches a native error (a cell value, an
Arrow field name, a detector or validator name, a namespace), checks that the intended site ran
(exception class and the site's `code:` prefix), and then checks every surface of the raised
error and of the translated exception.

Needs the compiled companion, so it lives in `tests/native`: the `core-companion-present` job
of `native-companion.yml` runs that whole directory with the companion built, and a companion
that failed to load fails the earlier `--require-companion` steps of the same job. The module
skips without the companion for the companion-less regression lane. Locally, run it in the
lock-faithful venv (`venv-native-lock`): the gate venvs do not install the companion.
"""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable
from typing import Any

import pyarrow as pa
import pytest

from tests._exception_surfaces import rendered_surfaces
from tests._f31_canary import CANARY, ROW_CANARY, assert_no_canary, leak_xfail

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("decoy_engine_native") is None,
    reason="decoy-engine-native companion not installed; the companion-present CI job covers this",
)

_KEY = b"\x01" * 32


def _kernel() -> Any:
    from decoy_engine_native import _kernel

    return _kernel


def _struct_with_canary_field() -> pa.Array:
    """An Arrow type the kernels do not admit, whose field name carries the marker."""
    return pa.array([{CANARY: 1}])


def _struct_with_canary_metadata() -> pa.Array:
    """The same unadmitted type with a clean field name: the marker is only in a metadata value."""
    child = pa.field("child", pa.int64(), metadata={"note": CANARY})
    return pa.array([{"child": 1}], pa.struct([child]))


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


_F1 = "V2-LOG 2026-11-25 F31 AE6-F1 config ids in native errors"
_F2 = "V2-LOG 2026-11-25 F31 AE6-F2 struct type text in native errors"


def _leak(entry: str, site: str, what: str) -> Any:
    return leak_xfail(f"{entry}: {site} {what}")


_NAME = "formats the config id into the error"
_TYPE = "formats the Arrow type, struct field names included"
_TYPE_META = "formats the Arrow type, child field metadata values included"

# (id, callable, exception type, the site's message prefix, leak mark or None, whether the case
# plants ROW_CANARY). The prefix is the `code: ` the site writes, or its whole fixed text where
# the site has no code. A cell that reaches another site with the same exception class fails on
# the prefix.
_RAISERS: list[tuple[str, Callable[[Any], Any], type[Exception], str, Any, bool]] = [
    (
        "derive_unadmitted_type",
        lambda k: _derive(k, _struct_with_canary_field()),
        ValueError,
        "mixed_object_not_native: ",
        _leak(_F2, "batch/string.rs:53", _TYPE),
        False,
    ),
    (
        "derive_unadmitted_type_metadata_value",
        lambda k: _derive(k, _struct_with_canary_metadata()),
        ValueError,
        "mixed_object_not_native: ",
        _leak(_F2, "batch/string.rs:53", _TYPE_META),
        False,
    ),
    (
        "derive_empty_namespace",
        lambda k: _derive(k, _strings(), namespace=""),
        ValueError,
        "namespace_empty: ",
        None,
        False,
    ),
    (
        "derive_bad_truncate",
        lambda k: _derive(k, _strings(), truncate=CANARY),
        TypeError,
        "truncate must be an int or None",
        None,
        False,
    ),
    (
        "derive_bad_threads",
        lambda k: _derive(k, _strings(), native_threads=-1),
        ValueError,
        "native_threads_negative: ",
        None,
        False,
    ),
    (
        "index_unadmitted_type",
        lambda k: _index(k, _struct_with_canary_field()),
        ValueError,
        "mixed_object_not_native: ",
        _leak(_F2, "batch/index.rs:93", _TYPE),
        False,
    ),
    (
        "index_unadmitted_type_metadata_value",
        lambda k: _index(k, _struct_with_canary_metadata()),
        ValueError,
        "mixed_object_not_native: ",
        _leak(_F2, "batch/index.rs:93", _TYPE_META),
        False,
    ),
    (
        "index_pool_size_text",
        lambda k: _index(k, _strings(), pool_size=CANARY),
        TypeError,
        "pool_size must be an int",
        None,
        False,
    ),
    (
        "hex_unadmitted_type",
        lambda k: _hex(k, _struct_with_canary_field()),
        ValueError,
        "group_key_input_not_string: ",
        None,
        False,
    ),
    (
        "hex_odd_chars",
        lambda k: _hex(k, _strings(), hex_chars=3),
        ValueError,
        "group_key_hex_chars_invalid: ",
        None,
        False,
    ),
    (
        "fpe_unadmitted_type",
        lambda k: _fpe(k, _struct_with_canary_field()),
        ValueError,
        "fpe_input_not_string: ",
        None,
        False,
    ),
    (
        "fpe_empty_namespace",
        lambda k: _fpe(k, _strings(), namespace=""),
        ValueError,
        "namespace_empty: ",
        None,
        False,
    ),
    (
        "fpe_bad_threads",
        lambda k: _fpe(k, _strings(), native_threads=-1),
        ValueError,
        "native_threads_negative: ",
        None,
        False,
    ),
    (
        "redact_unknown_detector",
        lambda k: k.text_redact_candidates([ROW_CANARY], [CANARY], k.text_redact_catalog_version()),
        ValueError,
        "unknown_detector_id: ",
        _leak(_F1, "pyboundary.rs:48", _NAME),
        True,
    ),
    (
        "redact_catalog_mismatch",
        lambda k: k.text_redact_candidates([CANARY], [], -1),
        ValueError,
        "catalog_version_mismatch: ",
        None,
        False,
    ),
    (
        "redact_unknown_validator",
        lambda k: k.text_redact_validate(CANARY, ROW_CANARY),
        ValueError,
        "unknown validator ",
        _leak(_F1, "pyboundary.rs:151", _NAME),
        True,
    ),
    (
        "redact_unknown_class",
        lambda k: k.text_redact_class_members(CANARY),
        ValueError,
        "unknown class ",
        _leak(_F1, "pyboundary.rs:174", _NAME),
        False,
    ),
    (
        "mask_unknown_detector",
        lambda k: k.text_mask_detect_splice(
            [ROW_CANARY], [CANARY], [False], "x", False, k.text_redact_catalog_version()
        ),
        ValueError,
        "unknown_detector_id: ",
        _leak(_F1, "text_mask.rs:219", _NAME),
        True,
    ),
    (
        "mask_verbatim_mismatch",
        lambda k: k.text_mask_detect_splice(
            [CANARY], [], [True], "x", False, k.text_redact_catalog_version()
        ),
        ValueError,
        "verbatim_length_mismatch",
        None,
        False,
    ),
    (
        "mask_catalog_mismatch",
        lambda k: k.text_mask_detect_splice([CANARY], [], [], "x", False, -1),
        ValueError,
        "catalog_version_mismatch: ",
        None,
        False,
    ),
    (
        "mask_spans_short",
        lambda k: k.text_mask_splice_spans([CANARY, "b"], [[]], "x", False),
        ValueError,
        "spans_shorter_than_values",
        None,
        False,
    ),
]

_PARAMS = [
    pytest.param(raiser, exc, prefix, id=name, marks=[mark] if mark is not None else [])
    for name, raiser, exc, prefix, mark, _ in _RAISERS
]


_ROW_PLANTED = [
    pytest.param(raiser, exc, prefix, id=name)
    for name, raiser, exc, prefix, _, plants_row in _RAISERS
    if plants_row
]


def _raised(raiser: Callable[[Any], Any], exc_type: type[Exception], prefix: str) -> Exception:
    """The error the intended site raised. `pytest.fail` keeps a miss out of a leak mark."""
    try:
        raiser(_kernel())
    except exc_type as raised:
        if not str(raised).startswith(prefix):
            pytest.fail(f"site prefix {prefix!r} not found: another site raised {type(raised)}")
        return raised
    except Exception as other:
        pytest.fail(f"expected {exc_type.__name__}, got {type(other).__name__}")
    pytest.fail(f"expected {exc_type.__name__}, nothing was raised")


@pytest.mark.parametrize(("raiser", "exc_type", "prefix"), _PARAMS)
def test_native_error_carries_no_input_text(
    raiser: Callable[[Any], Any], exc_type: type[Exception], prefix: str
) -> None:
    assert_no_canary(rendered_surfaces(_raised(raiser, exc_type, prefix)))


@pytest.mark.parametrize(("raiser", "exc_type", "prefix"), _ROW_PLANTED)
def test_native_error_carries_no_row_text(
    raiser: Callable[[Any], Any], exc_type: type[Exception], prefix: str
) -> None:
    """The row marker is checked apart from the name-echo leak marks above, so a mark on a cell
    that echoes its config id cannot hide a leak of the row text into the same error."""
    assert_no_canary(rendered_surfaces(_raised(raiser, exc_type, prefix)), ROW_CANARY)


# The translator, the exception class it returns for the native error below, and the native
# error. The native error comes from the real kernel, so the cell proves the translated class
# for a real input. `tests/security/test_f31_translator_canary.py` feeds each translator a
# synthetic detail and needs no companion.
_TRANSLATORS: list[Any] = [
    pytest.param(
        "decoy_engine.execution.native._crypto_ext",
        "_translate_compiled_kernel_error",
        "GenerationError",
        lambda k: _derive(k, _struct_with_canary_field()),
        id="crypto",
    ),
    pytest.param(
        "decoy_engine.execution.native._index_ext",
        "_translate_compiled_index_kernel_error",
        "GenerationError",
        lambda k: _index(k, _struct_with_canary_field()),
        id="index",
    ),
    pytest.param(
        "decoy_engine.execution.native._crypto_ext",
        "_translate_compiled_kernel_error",
        "GenerationError",
        lambda k: _derive(k, _struct_with_canary_metadata()),
        id="crypto_metadata_value",
    ),
    pytest.param(
        "decoy_engine.execution.native._index_ext",
        "_translate_compiled_index_kernel_error",
        "GenerationError",
        lambda k: _index(k, _struct_with_canary_metadata()),
        id="index_metadata_value",
    ),
    pytest.param(
        "decoy_engine.execution.native._group_key_ext",
        "_translate_compiled_raw_hex_kernel_error",
        "GenerationError",
        lambda k: _hex(k, _strings(), hex_chars=3),
        id="group_key",
    ),
    pytest.param(
        "decoy_engine.execution.native._fpe_ext",
        "_translate_compiled_fpe_error",
        "ValueError",
        lambda k: _fpe(k, _struct_with_canary_field()),
        id="fpe",
    ),
]


@pytest.mark.parametrize(("module", "translator", "expected", "raiser"), _TRANSLATORS)
def test_translator_output_carries_no_input_text(
    module: str, translator: str, expected: str, raiser: Callable[[Any], Any]
) -> None:
    native = _raised(raiser, ValueError, "")
    translated = getattr(importlib.import_module(module), translator)(native)
    if type(translated).__name__ != expected:
        pytest.fail(f"expected {expected}, got {type(translated).__name__}")
    assert_no_canary(rendered_surfaces(translated))


def test_public_index_derivation_error_carries_no_metadata_value() -> None:
    """The caller-facing path: `derive_validated_indices` hands the array to the compiled kernel
    and raises the translated error. The field name is clean, so only a metadata value can leak."""
    from decoy_engine.generation.pool import GenerationError, derive_validated_indices

    try:
        derive_validated_indices(
            _struct_with_canary_metadata(), mask_key=_KEY, namespace="ns", pool_size=10
        )
    except GenerationError as raised:
        assert_no_canary(rendered_surfaces(raised))
        return
    pytest.fail("derive_validated_indices did not raise GenerationError")


_ADMISSION_MESSAGE = (
    "[native_type_not_admitted] the native kernel does not admit the input column type"
)


def _crypto_wrapper_call() -> None:
    from decoy_engine.execution.native._crypto_ext import load_compiled_crypto_kernel

    load_compiled_crypto_kernel().derive_batch(
        _struct_with_canary_metadata(), mask_key=_KEY, namespace="ns", truncate=None
    )


def _index_wrapper_call() -> None:
    from decoy_engine.execution.native._index_ext import load_compiled_index_kernel

    load_compiled_index_kernel().derive_index_batch(
        _struct_with_canary_metadata(), mask_key=_KEY, namespace="ns", pool_size=10
    )


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(_crypto_wrapper_call, id="crypto"),
        pytest.param(_index_wrapper_call, id="index"),
    ],
)
def test_compiled_wrapper_raises_fixed_admission_error_with_no_native_chain(
    call: Callable[[], None],
) -> None:
    """The real wrapper, fed a struct whose only marker is a child-field metadata value, raises
    the fixed error and chains nothing: the native error formats the Arrow type, so it must be
    neither the cause nor the context."""
    from decoy_engine.generation.pool import GenerationError

    with pytest.raises(GenerationError) as info:
        call()
    assert str(info.value) == _ADMISSION_MESSAGE
    assert info.value.__cause__ is None
    assert info.value.__context__ is None
    assert_no_canary(rendered_surfaces(info.value))
