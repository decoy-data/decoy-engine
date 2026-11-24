"""F31 AE1 sentry: a class in the value-free registry stays value-free.

The renderer prints the message of every class in `VALUE_FREE_CLASSES`. That is safe only while
every raise of the class passes no exception or data-value name and sits in no function that
copies exception text, and while its `__str__`/`__repr__` (and its bases') add nothing. The
registry is seeded by that rule, so this test re-runs the rule on each run: a later raise that
interpolates a value fails here, and the class must leave the registry or the raise be fixed.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from decoy_engine.safe_output._render import VALUE_FREE_CLASSES
from tests.sentry.safe_output._registry_rule import (
    Admission,
    analyze,
    read_sources,
    special_method_findings,
)

PKG = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"
_SOURCES = read_sources(PKG)
_ADMISSION = analyze(_SOURCES)


def _resolve(dotted: str) -> type:
    module, _, name = dotted.rpartition(".")
    return getattr(importlib.import_module(module), name)


def test_every_registered_class_exists_and_is_an_exception() -> None:
    for dotted in sorted(VALUE_FREE_CLASSES):
        cls = _resolve(dotted)
        assert isinstance(cls, type) and issubclass(cls, BaseException), dotted
        assert f"{cls.__module__}.{cls.__qualname__}" == dotted, dotted


def test_every_registered_class_passes_the_rule() -> None:
    dropped = sorted(d for d in VALUE_FREE_CLASSES if d.rpartition(".")[2] in _ADMISSION.bad)
    assert not dropped, (
        "a raise of these classes interpolates an exception or a data value, or sits in a "
        f"function that copies exception text; fix the raise or remove the class: {dropped}"
    )


def test_every_registered_class_is_defined_in_the_engine() -> None:
    # By simple name: a class re-exported under another module keeps its runtime module as key.
    assert {d.rpartition(".")[2] for d in VALUE_FREE_CLASSES} <= set(_ADMISSION.classes)


def test_registered_special_methods_expose_no_value() -> None:
    found: list[str] = []
    for dotted in sorted(VALUE_FREE_CLASSES):
        for cls in _resolve(dotted).__mro__:
            if cls.__module__.startswith("decoy_engine"):
                found += special_method_findings(_SOURCES, cls.__module__, cls.__name__)
    assert not found, f"__str__/__repr__ of a registered class or base exposes a value: {found}"


# -- the rule itself: each case is a mutation the real walk would catch ------------------------


def _admission(**modules: str) -> Admission:
    return analyze(modules)


def test_rule_admits_a_clean_raise() -> None:
    adm = _admission(
        m="class E(Exception): pass\ndef f(n):\n    raise E('column count is fixed')\n"
    )
    assert "E" in adm.clean and "E" in adm.uncoded


@pytest.mark.parametrize(
    "body",
    [
        "raise E(f'bad {value}')",
        "raise E('bad ' + str(row))",
        "raise E('bad %s' % cell)",
        "raise E(msg)",
        "raise E(detail=value)",
    ],
)
def test_rule_drops_a_class_whose_raise_carries_a_value(body: str) -> None:
    prelude = "msg = f'x {value}'\n" if body.endswith("(msg)") else ""
    src = f"class E(Exception): pass\ndef f(value, row, cell, detail):\n    {prelude}    {body}\n"
    assert "E" in _admission(m=src).bad


def test_rule_drops_a_class_raised_beside_an_exception_copy() -> None:
    src = (
        "class E(Exception): pass\n"
        "def f():\n    try:\n        g()\n    except ValueError as exc:\n"
        "        log(str(exc))\n        raise E('fixed text')\n"
    )
    assert "E" in _admission(m=src).bad


def test_rule_follows_a_factory_to_its_class() -> None:
    src = (
        "class E(Exception): pass\n"
        "def _refuse(value):\n    return E(f'bad {value}')\n"
        "def f(value):\n    raise _refuse(value)\n"
    )
    adm = _admission(m=src)
    assert "E" in adm.uncoded


def test_rule_counts_a_factory_raise_with_a_value_argument() -> None:
    src = (
        "class E(Exception): pass\n"
        "def _refuse(text):\n    return E(text)\n"
        "def f(value):\n    raise _refuse(f'bad {value}')\n"
    )
    assert "E" in _admission(m=src).bad


def test_rule_does_not_count_a_coded_raise_as_uncoded() -> None:
    src = "class E(Exception): pass\ndef f():\n    raise E('x', code='some_code')\n"
    assert "E" not in _admission(m=src).uncoded


def test_special_methods_walk_catches_a_value() -> None:
    src = (
        "class E(Exception):\n"
        "    def __str__(self):\n        return f'bad {self.value}'\n"
        "class F(Exception):\n"
        "    def __repr__(self):\n        value = self.args[0]\n        return f'F({value})'\n"
        "class G(Exception):\n"
        "    def __str__(self):\n        return f'G {self.code}'\n"
    )
    sources = {"m": src}
    assert special_method_findings(sources, "m", "E") == []  # a self attribute is the raise's
    assert special_method_findings(sources, "m", "F")
    assert special_method_findings(sources, "m", "G") == []
