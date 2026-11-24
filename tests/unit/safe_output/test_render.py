"""F31 AE1: ``SafeText`` and ``render_failure`` print registry text or a type label, never data."""

from __future__ import annotations

import dataclasses
import json

import pytest

from decoy_engine import reasons
from decoy_engine.reason_adapter import (
    ReasonContext,
    capture_failure,
    failure_scope,
    reason_from_exception,
)
from decoy_engine.reasons import ReasonRecord
from decoy_engine.safe_output import SafeText, _render, render_failure, safe_error_type

_CANARY = "DECOY_CANARY_F31_7Q4Z"
_SSN = "123-45-6789"


class _RegisteredError(Exception):
    """Stands in for a registry class: its message is the one thing the renderer may print."""


class _RaisingStrError(Exception):
    def __str__(self) -> str:
        raise RuntimeError(_CANARY)


def _dotted(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


@pytest.fixture
def registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _render,
        "VALUE_FREE_CLASSES",
        frozenset({_dotted(_RegisteredError), _dotted(_RaisingStrError)}),
    )


def _summary(reason: reasons.ReasonCode) -> str:
    return ReasonRecord.for_reason(reason).summary


# -- one test per helper ------------------------------------------------------------------------


def test_coded_error_uses_registry_summary() -> None:
    text = render_failure(MemoryError(_CANARY))
    assert text.text == _summary(reasons.decoy.PROCESS_OUT_OF_MEMORY)


def test_coded_error_follows_the_registry_not_a_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    real_get = reasons._registry.get

    def get(namespace: str, code: str):  # type: ignore[no-untyped-def]
        return dataclasses.replace(real_get(namespace, code), summary="a changed summary")

    monkeypatch.setattr(reasons._registry, "get", get)
    assert render_failure(MemoryError()).text == "a changed summary"


def test_coded_error_adds_approved_refs() -> None:
    exc = MemoryError()
    capture_failure(exc, context=ReasonContext.build(object_ref="orders", storage_ref="vol.1"))
    text = render_failure(exc).text
    assert text == _summary(reasons.decoy.PROCESS_OUT_OF_MEMORY) + " (object=orders, storage=vol.1)"


def test_registered_class_keeps_its_message(registered: None) -> None:
    assert render_failure(_RegisteredError("column count is 3")).text == "column count is 3"


def test_registered_match_is_by_exact_type(registered: None) -> None:
    class _ChildError(_RegisteredError):
        pass

    assert (
        render_failure(_ChildError("column count is 3")).text
        == safe_error_type(_ChildError()).value
    )


def test_unregistered_class_message_is_dropped() -> None:
    assert render_failure(_RegisteredError(_CANARY)).text == "Exception"


def test_coded_cause_gives_label_and_summary() -> None:
    try:
        try:
            raise MemoryError(_CANARY)
        except MemoryError as inner:
            raise RuntimeError(f"wrapped {_SSN}") from inner
    except RuntimeError as outer:
        text = render_failure(outer).text
    assert text == f"RuntimeError caused by: {_summary(reasons.decoy.PROCESS_OUT_OF_MEMORY)}"


def test_cause_cycle_ends() -> None:
    a, b = ValueError(_CANARY), ValueError(_CANARY)
    a.__cause__, b.__cause__ = b, a
    assert render_failure(a).text == "ValueError"


def test_plain_exception_gives_type_label() -> None:
    assert render_failure(ValueError(f"bad {_SSN}")).text == "ValueError"


def test_third_party_text_dropped() -> None:
    exc = json.JSONDecodeError(_CANARY, _CANARY, 0)
    assert render_failure(exc).text == safe_error_type(exc).value == "Exception"


def test_raising_str_gives_type_label(registered: None) -> None:
    assert render_failure(_RaisingStrError()).text == "Exception"


def test_failing_helper_falls_back_to_label(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(exc: BaseException) -> SafeText:
        raise RuntimeError(_CANARY)

    monkeypatch.setattr(_render, "_render_cause", boom)
    assert render_failure(ValueError(_CANARY)).text == "ValueError"


def test_failing_label_falls_back_to_fixed_line(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(exc: BaseException) -> SafeText:
        raise RuntimeError(_CANARY)

    monkeypatch.setattr(_render, "_render_label", boom)
    assert render_failure(ValueError(_CANARY)).text == "Operation failed."


# -- reading never changes failure state -------------------------------------------------------


def test_render_inside_scope_is_read_only() -> None:
    exc = MemoryError()
    with failure_scope() as scope:
        before = (scope.first, list(scope.secondary), dict(exc.__dict__))
        render_failure(exc)
        render_failure(exc)
        assert (scope.first, scope.secondary, dict(exc.__dict__)) == (
            before[0],
            before[1],
            before[2],
        )
        assert scope.first is None
    assert reason_from_exception(exc).code == str(reasons.decoy.PROCESS_OUT_OF_MEMORY)


def test_render_does_not_replace_the_first_failure() -> None:
    with failure_scope() as scope:
        first = capture_failure(ValueError("first"))
        render_failure(MemoryError())
        assert scope.first is first and not scope.secondary


# -- SafeText ------------------------------------------------------------------------------------


def test_safe_text_is_not_built_directly() -> None:
    with pytest.raises(TypeError):
        SafeText("x")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        SafeText("x", _token=object())


def test_safe_text_is_frozen_and_not_a_str() -> None:
    text = SafeText.const("fixed")
    with pytest.raises(AttributeError):
        text._text = "other"  # type: ignore[misc]
    assert not isinstance(text, str) and str(text) == "fixed" and text == SafeText.const("fixed")


def test_template_fills_closed_slots() -> None:
    text = SafeText.template(
        "column {col} in {where} has {n} rows",
        names={"col": "email"},
        paths={"where": "data/in.csv"},
        counts={"n": 3},
    )
    assert text.text == "column email in data/in.csv has 3 rows"


@pytest.mark.parametrize("bad", ["a/b", "x=y", "a" * 129, "tab\there", "", 7, None])
def test_template_withholds_a_bad_name(bad: object) -> None:
    assert SafeText.template("column {c}", names={"c": bad}).text == "column <withheld>"


@pytest.mark.parametrize("bad", ["", "x" * 513, "line\nbreak", 5])
def test_template_withholds_a_bad_path(bad: object) -> None:
    assert SafeText.template("in {p}", paths={"p": bad}).text == "in <withheld>"


@pytest.mark.parametrize("bad", [-1, True, "3", 1.5])
def test_template_count_takes_a_nonnegative_int(bad: object) -> None:
    with pytest.raises(TypeError):
        SafeText.template("n {n}", counts={"n": bad})  # type: ignore[dict-item]


@pytest.mark.parametrize(
    ("literal", "kwargs"),
    [
        ("a {x}", {}),
        ("a", {"names": {"x": "y"}}),
        ("a {x!r}", {"names": {"x": "y"}}),
        ("a {x:>5}", {"names": {"x": "y"}}),
        ("a {x.y}", {"names": {"x": "y"}}),
        ("a {x}", {"names": {"x": "y"}, "paths": {"x": "z"}}),
    ],
)
def test_template_slot_misuse_is_a_programming_error(literal: str, kwargs: dict) -> None:
    with pytest.raises(ValueError):
        SafeText.template(literal, **kwargs)


def test_template_slot_value_braces_are_not_reformatted() -> None:
    assert SafeText.template("c {a}", names={"a": "{b}"}).text == "c {b}"


@pytest.mark.parametrize(
    "reason",
    [reasons.decoy.UNEXPECTED_ERROR, reasons.decoy.UNREGISTERED_REASON, reasons.config.UNTAGGED],
    ids=["unexpected_error", "unregistered_reason", "untagged"],
)
def test_generic_reasons_do_not_count_as_coded(
    registered: None, monkeypatch: pytest.MonkeyPatch, reason: reasons.ReasonCode
) -> None:
    monkeypatch.setattr(
        _render, "reason_from_exception", lambda exc: ReasonRecord.for_reason(reason)
    )
    assert render_failure(_RegisteredError("kept message")).text == "kept message"
    assert render_failure(ValueError(_CANARY)).text == "ValueError"


def test_registered_message_control_characters_become_spaces(registered: None) -> None:
    assert render_failure(_RegisteredError("a\nb\x1b[31mc")).text == "a b [31mc"


def test_long_registered_message_is_cut_with_a_marker(registered: None) -> None:
    text = render_failure(_RegisteredError("x" * 600)).text
    assert text == "x" * _render.MAX_MESSAGE_LEN + _render.TRUNCATED_MARKER
    assert render_failure(_RegisteredError("x" * 500)).text == "x" * 500
