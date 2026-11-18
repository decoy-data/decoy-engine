"""X0 (freeze batch plan 4.1 item 4, AT-X0b): the docstring marker matches the registry both ways.

An experimental class or function starts its docstring with `EXPERIMENTAL_MARKER`. An experimental
constant has no docstring of its own, so its defining module's docstring starts with the marker
and names the constant. No frozen or internal object may carry the marker.
"""

from __future__ import annotations

import importlib

import pytest

from decoy_engine.contracts import stability as st
from tests.sentry.release import _census as census


@pytest.fixture(scope="module")
def tiered() -> list[tuple[census.Export, str]]:
    exports, _ = census.load()
    tiers = census.classify(exports)
    return [(e, tiers[(e.module, e.name)]) for e in exports if e.obj is not None]


def _doc(obj: object) -> str:
    return (getattr(obj, "__doc__", None) or "").lstrip()


def test_every_experimental_callable_starts_with_the_marker(tiered) -> None:
    bad = {
        f"{e.module}.{e.name}"
        for e, tier in tiered
        if tier == st.EXPERIMENTAL
        and not census.is_constant(e.obj)
        and not _doc(e.obj).startswith(st.EXPERIMENTAL_MARKER)
    }
    assert not bad, f"experimental names without the docstring marker: {sorted(bad)}"


def test_every_experimental_constant_is_named_in_its_module_docstring() -> None:
    module, names = st.EXPERIMENTAL_CONSTANTS
    doc = _doc(importlib.import_module(module))
    assert doc.startswith(st.EXPERIMENTAL_MARKER), f"{module} docstring lacks the marker"
    assert [n for n in names if n not in doc] == [], "constants missing from the module docstring"


def test_no_frozen_or_internal_object_carries_the_marker(tiered) -> None:
    bad = {
        f"{e.module}.{e.name}"
        for e, tier in tiered
        if tier != st.EXPERIMENTAL
        and not census.is_constant(e.obj)
        and _doc(e.obj).startswith(st.EXPERIMENTAL_MARKER)
    }
    assert not bad, f"marker on a name the registry does not list: {sorted(bad)}"


def test_the_marker_check_sees_a_seeded_miss() -> None:
    """The sentry is not vacuous: a function with no marker fails the same predicate."""

    def plain() -> None:
        """Does a thing."""

    assert not _doc(plain).startswith(st.EXPERIMENTAL_MARKER)
