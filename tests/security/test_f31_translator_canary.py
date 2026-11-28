"""F31 translator canary (AE6): the five native-error translators, fed synthetic native errors.

A translator turns a compiled kernel's `ValueError("<code>: <detail>")` into the engine's own
exception. Two properties hold it value-free, and each gets its own cell:

1. The translated exception carries the code and the detail text, and nothing else of the input
   error: not its cause, its context or its attributes. A translator that returned the native
   error itself, or chained it, would pass these. Green.
2. The detail text is copied as given, so a detail that carries input text reaches the translated
   message. The translators do not scrub: the native canary (`tests/native/f31_canary/test_native_canary.py`)
   is what keeps the detail value-free. Strict xfail, recorded in the V2-LOG.

These cells feed the translators directly, so they need no native companion and run in every lane.
`tests/native/f31_canary/test_native_canary.py` feeds them errors from the real kernel.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable

import pytest

from tests._exception_surfaces import rendered_surfaces
from tests._f31_canary import (
    CANARY,
    EXC_MESSAGE_AND_ATTR_SURFACES,
    assert_extra_surface_is_flagged,
    assert_known_leak,
    assert_no_canary,
)

_FIXED_DETAIL = "fixed native detail"
_F3 = "V2-LOG 2026-11-25 F31 AE6-F3 native translators copy the native detail verbatim"

_NATIVE = "decoy_engine.execution.native."

# (module, translator, native code the translator maps, class name it returns for that code)
_MAPPED: list[tuple[str, str, str, str]] = [
    ("_crypto_ext", "_translate_compiled_kernel_error", "seed_wrong_length", "DeterminismError"),
    ("_crypto_ext", "_translate_compiled_kernel_error", "namespace_empty", "DeterminismError"),
    (
        "_crypto_ext",
        "_translate_compiled_kernel_error",
        "mixed_object_not_native",
        "GenerationError",
    ),
    (
        "_index_ext",
        "_translate_compiled_index_kernel_error",
        "seed_wrong_length",
        "DeterminismError",
    ),
    (
        "_index_ext",
        "_translate_compiled_index_kernel_error",
        "pool_size_invalid",
        "DeterminismError",
    ),
    (
        "_index_ext",
        "_translate_compiled_index_kernel_error",
        "pool_size_overflow",
        "DeterminismError",
    ),
    (
        "_index_ext",
        "_translate_compiled_index_kernel_error",
        "mixed_object_not_native",
        "GenerationError",
    ),
    (
        "_group_key_ext",
        "_translate_compiled_raw_hex_kernel_error",
        "namespace_empty",
        "DeterminismError",
    ),
    (
        "_group_key_ext",
        "_translate_compiled_raw_hex_kernel_error",
        "mixed_object_not_native",
        "GenerationError",
    ),
    (
        "_group_key_ext",
        "_translate_compiled_raw_hex_kernel_error",
        "group_key_input_not_string",
        "GenerationError",
    ),
    (
        "_group_key_ext",
        "_translate_compiled_raw_hex_kernel_error",
        "group_key_hex_chars_invalid",
        "GenerationError",
    ),
    ("_fpe_ext", "_translate_compiled_fpe_error", "seed_wrong_length", "DeterminismError"),
    ("_fpe_ext", "_translate_compiled_fpe_error", "namespace_empty", "DeterminismError"),
]

# Both fold an unadmitted Arrow type into a fixed message: the native detail formats the type,
# field names and metadata values included, so these two codes do not forward it.
_DETAIL_DROPPED = {
    ("_crypto_ext", "mixed_object_not_native"),
    ("_index_ext", "mixed_object_not_native"),
}

_IDS = [f"{module.strip('_')}-{code}" for module, _, code, _ in _MAPPED]


def _translate(module: str, translator: str, error: ValueError) -> BaseException:
    fn: Callable[[ValueError], BaseException] = getattr(
        importlib.import_module(_NATIVE + module), translator
    )
    return fn(error)


def _native_error_with_marker_outside_the_detail(code: str) -> ValueError:
    """A native error whose own text is clean and whose cause, context and attribute are not."""
    error = ValueError(f"{code}: {_FIXED_DETAIL}")
    error.__cause__ = RuntimeError(CANARY)
    error.__context__ = KeyError(CANARY)
    error.payload = CANARY  # type: ignore[attr-defined]
    return error


@pytest.mark.parametrize(("module", "translator", "code", "expected"), _MAPPED, ids=_IDS)
def test_translated_error_forwards_only_code_and_detail(
    module: str, translator: str, code: str, expected: str
) -> None:
    translated = _translate(module, translator, _native_error_with_marker_outside_the_detail(code))
    if type(translated).__name__ != expected:
        pytest.fail(f"expected {expected}, got {type(translated).__name__}")
    forwarded = _FIXED_DETAIL in str(translated)
    if (module, code) in _DETAIL_DROPPED:
        if forwarded:
            pytest.fail("the translator forwarded a native detail it must drop")
    elif not forwarded:
        pytest.fail("the translator dropped the native detail")
    assert_no_canary(rendered_surfaces(translated))


# One leak cell per translator: every code of a translator that still copies its detail does so
# the same way (the two mixed_object_not_native mappings drop it, see _DETAIL_DROPPED).
_FIRST_PER_TRANSLATOR = list({row[0]: row for row in reversed(_MAPPED)}.values())


def _check_detail_copy(translated: BaseException, reason: str) -> None:
    """The recorded leak goes through `assert_known_leak`, so the marker reaching a surface
    beyond the translated message and its attributes fails the cell instead of passing as the known leak."""
    assert_known_leak(rendered_surfaces(translated), EXC_MESSAGE_AND_ATTR_SURFACES, reason)


def _copied_detail(module: str, translator: str, code: str, expected: str) -> BaseException:
    translated = _translate(module, translator, ValueError(f"{code}: row value {CANARY}"))
    if type(translated).__name__ != expected:
        pytest.fail(f"expected {expected}, got {type(translated).__name__}")
    return translated


_COPY_ROWS = [pytest.param(*row, id=row[0].strip("_")) for row in _FIRST_PER_TRANSLATOR]


@pytest.mark.parametrize(("module", "translator", "code", "expected"), _COPY_ROWS)
def test_translated_error_copies_the_detail_it_is_given(
    module: str, translator: str, code: str, expected: str
) -> None:
    translated = _copied_detail(module, translator, code, expected)
    _check_detail_copy(translated, f"{_F3}: {module.strip('_')}, the detail is not scrubbed")


@pytest.mark.parametrize(("module", "translator", "code", "expected"), _COPY_ROWS)
def test_detail_copy_cell_fails_when_the_marker_reaches_another_surface(
    module: str, translator: str, code: str, expected: str
) -> None:
    """The marker also stored in the error's records is a new leak, not the recorded one."""
    translated = _copied_detail(module, translator, code, expected)
    translated.records = [CANARY]  # type: ignore[attr-defined]
    assert_extra_surface_is_flagged(lambda: _check_detail_copy(translated, _F3))


def _text_mask_translator() -> Callable[[str], BaseException]:
    from decoy_engine.execution.native._text_mask_route import text_mask_fail_closed_error

    return text_mask_fail_closed_error


def test_text_mask_translator_takes_no_value_and_carries_none() -> None:
    """The translator is value-free by construction: it is given the column name only."""
    translated = _text_mask_translator()("col")
    if type(translated).__name__ != "StrategyError":
        pytest.fail(f"expected StrategyError, got {type(translated).__name__}")
    assert translated.__cause__ is None
    assert_no_canary(rendered_surfaces(translated))


def test_real_fpe_error_reaches_the_text_mask_translator_value_free() -> None:
    """The error the engine really raises for a sub-floor value, through the real translator."""
    from decoy_engine.errors import FpeUnencryptableError
    from decoy_engine.transforms.fpe import fpe_encrypt_value

    with pytest.raises(FpeUnencryptableError):
        fpe_encrypt_value(CANARY, b"\x01" * 32, "0123456789", b"t", False)
    translated = _text_mask_translator()("col")
    assert_no_canary(rendered_surfaces(translated))
