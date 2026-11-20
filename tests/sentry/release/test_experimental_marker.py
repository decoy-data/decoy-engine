"""X0 (freeze batch plan 4.1 item 4, AT-X0b): the docstring marker matches the registry both ways.

An experimental class or function starts its docstring with `EXPERIMENTAL_MARKER`. An experimental
constant has no docstring of its own, so the docstring of the module that defines it starts with
the marker and names the constant. No frozen or internal object may carry the marker.
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


def test_every_callable_marker_matches_its_tier(tiered) -> None:
    problems = census.marker_problems(tiered)
    assert not problems, f"docstring markers disagree with the registry: {sorted(problems)}"


def test_every_experimental_constant_is_named_in_its_module_docstring(tiered) -> None:
    """The constants `sdk.py` assigns are named in its module docstring, which has the marker."""
    names = sorted(
        {e.name for e, tier in tiered if tier == st.EXPERIMENTAL and census.is_constant(e.obj)}
    )
    assert len(names) >= 7, "the experimental constants were not found"
    doc = (importlib.import_module(st.EXPERIMENTAL_MODULE).__doc__ or "").lstrip()
    assert doc.startswith(st.EXPERIMENTAL_MARKER), "the sdk module docstring lacks the marker"
    assert [n for n in names if n not in doc] == [], "constants missing from the module docstring"


def test_the_marker_check_sees_seeded_misses() -> None:
    """The sentry's own predicate, run over seeded data: a miss and a stray marker are both found."""

    def plain() -> None:
        """Does a thing."""

    def marked() -> None:
        """Experimental: does a thing."""

    rows = [
        (census.Export("m", "plain", plain, False), st.EXPERIMENTAL),
        (census.Export("m", "marked", marked, False), st.FROZEN),
        (census.Export("m", "good", marked, False), st.EXPERIMENTAL),
    ]
    assert census.marker_problems(rows) == [
        "m.plain: experimental without the marker",
        "m.marked: marker on a frozen name",
    ]
