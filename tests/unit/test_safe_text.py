"""F31 AE1a1: ``SafeText`` prints only a literal of the calling code object.

Failing seeds are built at run time (``"".join``) so no literal in the test body can match them.
The autouse fixture in ``tests/conftest.py`` turns the strict switch on; ``production`` turns it off.
"""

from __future__ import annotations

import ast
import logging
import multiprocessing
import pickle
import re
import sys
import weakref
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from decoy_engine import _safe_text
from decoy_engine._safe_text import WITHHELD, SafeText

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
    exec("def trampoline(text):\n    return SafeText(text)\n", ns)  # noqa: S102
    return ns["trampoline"]


# The runtime refuses what it can see. Whether an argument was written as a literal is the AST
# sentry's job (tests/sentry/safe_output/test_safe_text_literals.py).
_NON_TEXT: dict[str, Callable[[str], Any]] = {
    "direct-constructor": lambda v: SafeText(v),
    "not-a-str": lambda v: SafeText.const(1234),  # type: ignore[arg-type]
    "bytes": lambda v: SafeText.const(b"bytes text"),  # type: ignore[arg-type]
    "template-not-a-str": lambda v: SafeText.literal_template(None),  # type: ignore[arg-type]
}


@pytest.mark.parametrize("case", sorted(_NON_TEXT))
def test_a_non_literal_raises_under_the_strict_switch(case: str) -> None:
    canary = _canary()
    with pytest.raises(TypeError) as err:
        _NON_TEXT[case](canary)
    assert canary not in str(err.value)
    assert "test_safe_text" in str(err.value)  # the call site, as a code location


@pytest.mark.parametrize("case", sorted(_NON_TEXT))
def test_a_non_literal_is_withheld_in_production_with_no_canary(
    case: str, production: None, caplog: pytest.LogCaptureFixture
) -> None:
    canary = _canary()
    with caplog.at_level(logging.WARNING, logger="decoy_engine._safe_text"):
        out = _NON_TEXT[case](canary)
    assert out is WITHHELD
    assert str(out) == "" and not out
    assert canary not in caplog.text and canary not in repr(out)


def test_production_logs_one_warning_per_call_site(
    production: None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="decoy_engine._safe_text"):
        for _ in range(3):
            SafeText(_canary())
    assert len(caplog.records) == 1


def test_a_literal_in_every_plain_spelling_passes() -> None:
    folded = SafeText.const("ab" + "cd-ef")
    implicit = SafeText.const("one " "two")  # fmt: skip
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


# A20: the call site skips mutmut frames by module name, never by function name.
def test_a_refusal_through_a_mutmut_wrapper_names_the_callers_module() -> None:
    with pytest.raises(TypeError, match="test_safe_text"):
        _wrapper("mutmut.mutation.trampoline")(_canary())


def test_a_module_that_only_starts_like_mutmut_is_not_skipped() -> None:
    with pytest.raises(TypeError, match="mutmutx"):
        _wrapper("mutmutx.trampoline")(_canary())


def test_a_literal_template_with_keyword_slots_prints_its_text() -> None:
    made = SafeText.literal_template("plain {{x}}", names={"k": "v"}, paths=None)
    assert str(made) == "plain {x}"


# literal_template: AE1a1 has no safe slot type, so every slot is withheld.
def test_a_template_without_a_slot_prints_its_text() -> None:
    made = SafeText.literal_template("fixed {{braces}} text")
    assert str(made) == "fixed {braces} text"


def test_a_template_slot_raises_under_strict_and_prints_a_marker_in_production(
    production: None,
) -> None:
    made = SafeText.literal_template("at {name} done", names={"name": "orders"})
    assert str(made) == "at <withheld> done"
    _safe_text._set_strict(True)
    with pytest.raises(TypeError):
        SafeText.literal_template("at {name} done", names={"name": "orders"})


def test_a_malformed_template_is_withheld(production: None) -> None:
    assert SafeText.literal_template("broken {") is WITHHELD


# The leaf imports nothing from decoy_engine (A19, part one; the layer contract is the second).
def _runtime_imports(node: ast.AST) -> Iterator[ast.Import | ast.ImportFrom]:
    """Every import in the tree except those in an ``if TYPE_CHECKING:`` body.

    Walks all suites (try, except, else, finally, with, defs), so a fallback import in an
    ``except ImportError`` handler is seen.
    """
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        yield node
        return
    skip: list[ast.stmt] = []
    if (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "TYPE_CHECKING"
    ):
        skip = node.body
    for child in ast.iter_child_nodes(node):
        if not any(child is s for s in skip):
            yield from _runtime_imports(child)


def _non_stdlib_imports(source: str) -> list[str]:
    bad: list[str] = []
    for node in _runtime_imports(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            roots = ["." * node.level + (node.module or "")] if node.level else [node.module or ""]
        else:
            roots = [a.name for a in node.names]
        bad += [
            r for r in roots if r.startswith(".") or r.split(".")[0] not in sys.stdlib_module_names
        ]
    return bad


def test_the_leaf_imports_only_the_standard_library() -> None:
    assert _non_stdlib_imports(_LEAF.read_text(encoding="utf-8")) == []


def test_the_import_walker_sees_every_suite_but_not_type_checking() -> None:
    planted = (
        "try:\n    import json\nexcept ImportError:\n    import typing_extensions\n"
        "else:\n    import pandas\nfinally:\n    from . import sibling\n"
        "if TYPE_CHECKING:\n    import numpy\nelse:\n    import yaml\n"
    )
    assert _non_stdlib_imports(planted) == ["typing_extensions", "pandas", ".", "yaml"]


# E: pickle and the process pool.
def test_a_safe_text_and_the_withheld_singleton_round_trip_through_pickle() -> None:
    text = SafeText.const("pickled text")
    again = pickle.loads(pickle.dumps(text))  # noqa: S301
    assert isinstance(again, SafeText) and str(again) == "pickled text" and again == text
    assert pickle.loads(pickle.dumps(WITHHELD)) is WITHHELD  # noqa: S301


def test_a_safe_text_does_not_print_itself_in_a_repr() -> None:
    text = SafeText.const("pickled text")
    assert "pickled" not in repr(text)


def _worker_literal() -> Any:
    return SafeText.const("worker literal")


def _worker_non_text() -> Any:
    return SafeText.const(None)  # type: ignore[arg-type]


def _worker_echo(text: object) -> str:
    return str(text)


def _worker_strict() -> bool:
    return _safe_text._strict_active()


def test_a_safe_text_crosses_a_process_pool_and_the_worker_withholds() -> None:
    # A25: spawn gives the worker a fresh module, so the strict switch is off there.
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as pool:
        assert pool.submit(_worker_strict).result() is False
        made = pool.submit(_worker_literal).result()
        assert isinstance(made, SafeText) and str(made) == "worker literal"
        sent = SafeText.const("sent text")
        assert pool.submit(_worker_echo, sent).result() == "sent text"
        assert pool.submit(_worker_non_text).result() is WITHHELD


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
    again = SafeText.const("fixed text")
    assert text == again


def test_the_slot_refusal_names_the_line() -> None:
    with pytest.raises(TypeError, match=r"test_safe_text:test_the_slot_refusal_names_the_line:\d+"):
        SafeText.literal_template("hello {name}")


def test_the_reprs_never_print_text() -> None:
    assert repr(WITHHELD) == "WITHHELD"
    text = SafeText.const("secret-ish")
    assert repr(text) == "SafeText(<text>)"


def test_hash_follows_the_text() -> None:
    first = SafeText.const("same text")
    second = SafeText.const("same text")
    assert hash(first) == hash("same text")
    assert len({first, second}) == 1


def test_a_deleted_attribute_message_says_immutable() -> None:
    text = SafeText.const("fixed text")
    with pytest.raises(AttributeError, match="^SafeText is immutable$"):
        del text._text  # type: ignore[union-attr]


def test_the_production_warning_names_module_function_and_line(
    production: None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="decoy_engine._safe_text"):
        SafeText(_canary())
    pattern = r"SafeText withheld a refused value at \S+:test_the_production_warning_[a-z_]+:\d+$"
    assert re.search(pattern, caplog.records[0].getMessage())


def test_a_template_that_starts_with_a_slot_keeps_only_the_marker(production: None) -> None:
    made = SafeText.literal_template("{x}")
    assert str(made) == "<withheld>"


def test_no_frame_means_an_unknown_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_safe_text.inspect, "currentframe", lambda: None)
    assert _safe_text._caller_site() == ("unknown", "unknown", 0)


def test_an_error_while_walking_frames_means_an_unknown_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Broken:
        @property
        def f_globals(self) -> dict[str, Any]:
            raise RuntimeError("broken frame")

    monkeypatch.setattr(_safe_text.inspect, "currentframe", lambda: _Broken())
    assert _safe_text._caller_site() == ("unknown", "unknown", 0)


class _RaisingLen(str):
    def __len__(self) -> int:
        raise RuntimeError("len ran")


def _dead_proxy() -> Any:
    class _Holder(str):
        pass

    obj = _Holder("some long text")
    proxy = weakref.proxy(obj)
    del obj
    return proxy


def _raising() -> Any:
    return _RaisingLen("abcdef")


_ODD_INPUTS = {"raising-len": _raising, "dead-proxy": _dead_proxy}
_BUILDERS: dict[str, Callable[[Any], Any]] = {
    "const": lambda v: SafeText.const(v),
    "template": lambda v: SafeText.literal_template(v),
}


@pytest.mark.parametrize("builder", sorted(_BUILDERS))
@pytest.mark.parametrize("odd", sorted(_ODD_INPUTS))
def test_an_odd_input_is_withheld_without_running_its_code(
    odd: str, builder: str, production: None
) -> None:
    assert _BUILDERS[builder](_ODD_INPUTS[odd]()) is WITHHELD


@pytest.mark.parametrize("builder", sorted(_BUILDERS))
@pytest.mark.parametrize("odd", sorted(_ODD_INPUTS))
def test_an_odd_input_under_strict_raises_only_the_location_error(odd: str, builder: str) -> None:
    with pytest.raises(TypeError, match=r"^SafeText needs a string literal at \S+:\S+:\d+$"):
        _BUILDERS[builder](_ODD_INPUTS[odd]())


def test_a_malformed_template_error_does_not_chain_the_parser_error() -> None:
    with pytest.raises(TypeError) as info:
        SafeText.literal_template("broken {")
    assert info.value.__context__ is None


def _worker_strict_active() -> bool:
    return _safe_text._strict_active()


def _worker_withholds(value: object) -> bool:
    return SafeText.const(value) is WITHHELD  # type: ignore[arg-type]


@pytest.mark.parametrize("method", ["fork", "spawn"])
def test_strict_applies_only_in_the_process_that_set_it(method: str) -> None:
    if method not in multiprocessing.get_all_start_methods():
        pytest.skip(f"{method} is not available here")
    assert _safe_text._strict_active() is True
    ctx = multiprocessing.get_context(method)
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as pool:
        assert pool.submit(_worker_strict_active).result() is False
        assert pool.submit(_worker_withholds, None).result() is True


def _worker_set_strict_roundtrip() -> tuple[bool, bool, bool]:
    first = _safe_text._set_strict(True)
    second = _safe_text._set_strict(first)
    return first, second, _safe_text._strict_active()


def test_set_strict_returns_the_effective_value_in_a_forked_child() -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork is not available here")
    assert _safe_text._strict is True  # the autouse fixture; the child inherits it raw
    ctx = multiprocessing.get_context("fork")
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as pool:
        # The child's effective strict is off, so save/restore must read False then True.
        assert pool.submit(_worker_set_strict_roundtrip).result() == (False, True, False)
