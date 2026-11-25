"""A retired reason may name no successor, but every successor it names is a live reason."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise

from decoy_engine import reasons


def test_every_successor_a_tombstone_names_is_live() -> None:
    assert reasons.check_integrity() == []


def test_a_reason_may_retire_with_no_successor() -> None:
    specs = {s.identity: s for s in reasons.specs()}
    spec = specs[("route", "when_reads_masked_column")]
    assert spec.deprecated_in is not None and spec.replaced_by is None
    assert reasons.check_integrity([spec]) == []


def test_a_successor_that_is_missing_or_retired_is_rejected() -> None:
    live = next(s for s in reasons.specs() if s.deprecated_in is None)
    retired = next(s for s in reasons.specs() if s.deprecated_in and s.replaced_by is None)
    missing = replace(retired, replaced_by=("nowhere", "x"))
    assert "not a declared identity" in " ".join(reasons.check_integrity([missing]))
    dead_end = replace(live, replaced_by=None, deprecated_in="9.9.9", code="dead_end")
    pointing = replace(retired, replaced_by=dead_end.identity)
    assert "has no live end" in " ".join(reasons.check_integrity([pointing, dead_end]))


def test_a_five_link_replacement_chain_is_consistent() -> None:
    live = next(s for s in reasons.specs() if s.deprecated_in is None)
    ids = [f"link_{i}" for i in range(5)] + [live.code]
    links = [
        replace(live, code=c, deprecated_in="9.9.9", replaced_by=(live.namespace, n))
        for c, n in pairwise(ids)
    ]
    assert reasons.check_integrity([*links, live]) == []


def test_a_replacement_chain_that_loops_is_reported() -> None:
    live = next(s for s in reasons.specs() if s.deprecated_in is None)
    a = replace(live, code="loop_a", deprecated_in="9.9.9", replaced_by=(live.namespace, "loop_b"))
    b = replace(live, code="loop_b", deprecated_in="9.9.9", replaced_by=(live.namespace, "loop_a"))
    problems = " ".join(reasons.check_integrity([a, b]))
    assert "replacement chain loops" in problems
    assert "no live end" not in problems


def test_a_duplicate_identity_is_rejected_in_either_order() -> None:
    live = next(s for s in reasons.specs() if s.deprecated_in is None)
    broken = replace(live, rules=())
    for catalog in ([live, broken], [broken, live]):
        assert "duplicate identity" in " ".join(reasons.check_integrity(catalog))
