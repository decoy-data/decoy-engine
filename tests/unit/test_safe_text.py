"""F31 AE1a1: ``SafeText`` prints only a literal of the calling code object.

Failing seeds are built at run time (``"".join``) so no literal in the test body can match them.
The autouse fixture in ``tests/conftest.py`` turns the strict switch on; ``production`` turns it off.
"""

from __future__ import annotations

import ast
import functools
import logging
import multiprocessing
import pickle
import re
import sys
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from decoy_engine import _safe_text
from decoy_engine._safe_text import WITHHELD, SafeText

_MODULE_TEXT = "a module level constant"
_LEAF = Path(_safe_text.__file__)


def _canary() -> str:
    return "".join(["CANARY", "-", "4417"])


@pytest.fixture
def production() -> Iterator[None]:
    previous = _safe_text._set_strict(False)
    yield
    _safe_text._set_strict(previous)


def _wrapper(module_name: str) -> Callable[[Any], Any]:
    """A function named ``trampoline`` whose globals carry ``module_name``."""
    ns: dict[str, Any] = {"__name__": module_name, "SafeText": SafeText}
    exec("def trampoline(text):\n    return SafeText.const(text)\n", ns)  # noqa: S102
    return ns["trampoline"]


def _wrap_param(v: Any) -> Any:
    return SafeText.const(v)


# Test B: every spelling that is not a literal call.
_NON_LITERAL: dict[str, Callable[[str], Any]] = {
    "wrapper-parameter": _wrap_param,
    "f-string-field": lambda v: SafeText.const(f"value {v}"),
    "str-of-exception": lambda v: SafeText.const(str(ValueError(v))),
    "module-constant": lambda v: SafeText.const(_MODULE_TEXT),
    "partial": lambda v: functools.partial(SafeText.const, v)(),
    "getattr": lambda v: getattr(SafeText, "const")(v),  # noqa: B009
    "direct-constructor": lambda v: SafeText(v),
    "template-format": lambda v: SafeText.literal_template(v),
    "not-a-str": lambda v: SafeText.const(1234),  # type: ignore[arg-type]
    "bytes": lambda v: SafeText.const(b"bytes text"),  # type: ignore[arg-type]
}


@pytest.mark.parametrize("case", sorted(_NON_LITERAL))
def test_a_non_literal_raises_under_the_strict_switch(case: str) -> None:
    canary = _canary()
    with pytest.raises(TypeError) as err:
        _NON_LITERAL[case](canary)
    assert canary not in str(err.value)
    assert "test_safe_text" in str(err.value)  # the call site, as a code location


@pytest.mark.parametrize("case", sorted(_NON_LITERAL))
def test_a_non_literal_is_withheld_in_production_with_no_canary(
    case: str, production: None, caplog: pytest.LogCaptureFixture
) -> None:
    canary = _canary()
    with caplog.at_level(logging.WARNING, logger="decoy_engine._safe_text"):
        out = _NON_LITERAL[case](canary)
    assert out is WITHHELD
    assert str(out) == "" and not out
    assert canary not in caplog.text and canary not in repr(out)


def test_production_logs_one_warning_per_call_site(
    production: None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="decoy_engine._safe_text"):
        for _ in range(3):
            _wrap_param(_canary())
    assert len(caplog.records) == 1


def test_a_literal_in_every_plain_spelling_passes() -> None:
    folded = SafeText.const("ab" + "cd-ef")
    implicit = SafeText.const("one two")
    plain = SafeText.const("plain text")
    nofield = SafeText.const(f"no field here")  # noqa: F541
    in_lambda = (lambda: SafeText.const("inside a lambda"))()
    in_comp = next(SafeText.const("inside a comprehension") for _ in range(1))
    assert [str(x) for x in (plain, folded, implicit, nofield, in_lambda, in_comp)] == [
        "plain text",
        "abcd-ef",
        "one two",
        "no field here",
        "inside a lambda",
        "inside a comprehension",
    ]


def test_a_literal_in_a_tuple_constant_is_not_a_literal_of_the_caller() -> None:
    pair = ("only inside a tuple", "other")
    with pytest.raises(TypeError):
        SafeText.const(pair[0])


# A20 and A20b: the mutmut wrapper is skipped by module name, never by function name.
def test_a_wrapper_in_a_mutmut_module_passes_the_literal_of_its_caller() -> None:
    wrap = _wrapper("mutmut.mutation.trampoline")
    # Calls sit outside the asserts: pytest's assert rewriting changes folded constants.
    plain = wrap("plain text")
    folded = wrap("ab" + "cd-ef")
    implicit = wrap("one two")
    assert [str(x) for x in (plain, folded, implicit)] == ["plain text", "abcd-ef", "one two"]


def test_the_same_wrapper_outside_mutmut_withholds_a_non_literal_argument() -> None:
    wrap = _wrapper("someapp.x")
    with pytest.raises(TypeError):
        wrap(_canary())
    with pytest.raises(TypeError):
        wrap("plain text")  # the wrapper's own constants do not hold it


def test_a_module_that_only_starts_like_mutmut_is_not_skipped() -> None:
    with pytest.raises(TypeError):
        _wrapper("mutmutx.trampoline")("plain text")


def test_a_mutmut_wrapper_calling_a_body_with_the_literal_passes() -> None:
    def body() -> Any:
        return SafeText.const("body literal")

    ns: dict[str, Any] = {"__name__": "mutmut.mutation.trampoline"}
    exec("def trampoline(fn):\n    return fn()\n", ns)  # noqa: S102
    assert str(ns["trampoline"](body)) == "body literal"


# A22: identity with a literal must not be a cache accident.
def test_a_one_character_cell_equal_to_a_literal_is_withheld() -> None:
    literal = "a"
    cell = sys.intern(b"a".decode())  # 3.11 does not hand back the cached cell without this
    assert cell is literal  # CPython caches one-character strings
    with pytest.raises(TypeError):
        SafeText.const(cell)


def test_an_interned_cell_equal_to_no_literal_is_withheld() -> None:
    cell = sys.intern("".join(["unrelated", "-cell"]))
    with pytest.raises(TypeError):
        SafeText.const(cell)


def test_an_interned_cell_equal_to_a_caller_literal_prints_only_that_literal() -> None:
    literal = "abcdef"
    cell = sys.intern("".join(["abc", "def"]))
    assert cell is literal
    assert str(SafeText.const(cell)) == "abcdef"


# A23: equal is not identical.
def test_an_equal_but_not_identical_cell_is_withheld() -> None:
    literal = "CANARY-77"
    row = "".join(["CANARY", "-77"])
    assert row == literal and row is not literal
    with pytest.raises(TypeError):
        SafeText.const(row)


# literal_template: AE1a1 has no safe slot type, so every slot is withheld.
def test_a_template_without_a_slot_prints_its_text() -> None:
    assert str(SafeText.literal_template("fixed {{braces}} text")) == "fixed {braces} text"


def test_a_template_slot_raises_under_strict_and_prints_a_marker_in_production(
    production: None,
) -> None:
    assert str(SafeText.literal_template("at {name} done", names={"name": "orders"})) == (
        "at <withheld> done"
    )
    _safe_text._set_strict(True)
    with pytest.raises(TypeError):
        SafeText.literal_template("at {name} done", names={"name": "orders"})


def test_a_malformed_template_is_withheld(production: None) -> None:
    assert SafeText.literal_template("broken {") is WITHHELD


# The leaf imports nothing from decoy_engine (A19, part one; the layer contract is the second).
def test_the_leaf_imports_only_the_standard_library() -> None:
    tree = ast.parse(_LEAF.read_text(encoding="utf-8"))
    names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names] + [
        n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
    ]
    assert not [n for n in names if n.startswith(("decoy_engine", "importlib"))]


# E: pickle and the process pool.
def test_a_safe_text_and_the_withheld_singleton_round_trip_through_pickle() -> None:
    text = SafeText.const("pickled text")
    again = pickle.loads(pickle.dumps(text))  # noqa: S301
    assert isinstance(again, SafeText) and str(again) == "pickled text" and again == text
    assert pickle.loads(pickle.dumps(WITHHELD)) is WITHHELD  # noqa: S301


def test_a_safe_text_does_not_print_itself_in_a_repr() -> None:
    assert "pickled" not in repr(SafeText.const("pickled text"))


def _worker_literal() -> Any:
    return SafeText.const("worker literal")


def _worker_non_literal(value: str) -> Any:
    return SafeText.const(value)


def _worker_echo(text: object) -> str:
    return str(text)


def _worker_strict() -> bool:
    return _safe_text._strict


def test_a_safe_text_crosses_a_process_pool_and_the_worker_withholds() -> None:
    # A25: spawn gives the worker a fresh module, so the strict switch is off there.
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as pool:
        assert pool.submit(_worker_strict).result() is False
        made = pool.submit(_worker_literal).result()
        assert isinstance(made, SafeText) and str(made) == "worker literal"
        assert pool.submit(_worker_echo, SafeText.const("sent text")).result() == "sent text"
        assert pool.submit(_worker_non_literal, _canary()).result() is WITHHELD


def test_a_two_character_literal_is_the_shortest_that_passes() -> None:
    assert str(SafeText.const("ok")) == "ok"


def test_a_minted_text_cannot_be_changed_or_deleted() -> None:
    text = SafeText.const("fixed text")
    with pytest.raises(AttributeError):
        text._text = "other"  # type: ignore[union-attr]
    with pytest.raises(AttributeError):
        del text._text  # type: ignore[union-attr]
    assert str(text) == "fixed text"


def test_equality_with_a_non_safe_text_defers_to_the_other_side() -> None:
    text = SafeText.const("fixed text")
    assert text.__eq__("fixed text") is NotImplemented
    assert text != "fixed text"
    assert text == SafeText.const("fixed text")


def test_the_slot_refusal_names_the_line() -> None:
    with pytest.raises(TypeError, match=r"test_safe_text:test_the_slot_refusal_names_the_line:\d+"):
        SafeText.literal_template("hello {name}")


def test_the_reprs_never_print_text() -> None:
    assert repr(WITHHELD) == "WITHHELD"
    assert repr(SafeText.const("secret-ish")) == "SafeText(<text>)"


def test_hash_follows_the_text() -> None:
    assert hash(SafeText.const("same text")) == hash("same text")
    assert len({SafeText.const("same text"), SafeText.const("same text")}) == 1


def test_a_deleted_attribute_message_says_immutable() -> None:
    text = SafeText.const("fixed text")
    with pytest.raises(AttributeError, match="^SafeText is immutable$"):
        del text._text  # type: ignore[union-attr]


def test_the_production_warning_names_module_function_and_line(
    production: None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="decoy_engine._safe_text"):
        SafeText.const(_canary())
    pattern = r"SafeText withheld a non-literal at \S+:test_the_production_warning_[a-z_]+:\d+$"
    assert re.search(pattern, caplog.records[0].getMessage())


def test_a_template_that_starts_with_a_slot_keeps_only_the_marker(production: None) -> None:
    assert str(SafeText.literal_template("{x}")) == "<withheld>"


def test_no_frame_means_no_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_safe_text.inspect, "currentframe", lambda: None)
    assert _safe_text._caller_code() == (None, ("unknown", "unknown", 0))


def test_an_error_while_walking_frames_means_no_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Broken:
        @property
        def f_globals(self) -> dict[str, Any]:
            raise RuntimeError("broken frame")

    monkeypatch.setattr(_safe_text.inspect, "currentframe", lambda: _Broken())
    assert _safe_text._caller_code() == (None, ("unknown", "unknown", 0))
