"""A retired reason may name no successor, but every successor it names is a live reason."""

from __future__ import annotations

from dataclasses import replace

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
