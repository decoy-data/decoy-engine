"""A retired reason may name no successor, but every successor it names is a live reason."""

from __future__ import annotations

from collections.abc import Iterable

from decoy_engine import reasons
from decoy_engine.reasons._types import ReasonSpec


def tombstone_problems(specs: Iterable[ReasonSpec]) -> list[str]:
    by_id = {spec.identity: spec for spec in specs}
    problems: list[str] = []
    for spec in by_id.values():
        if spec.deprecated_in is None or spec.replaced_by is None:
            continue  # live, or retired with no successor
        end = by_id.get(spec.replaced_by)
        seen = {spec.identity}
        for _ in range(3):  # a tombstone's shipped pin cannot move, so a chain may be a few links
            if end is None or end.deprecated_in is None or end.replaced_by is None:
                break
            if end.identity in seen:
                problems.append(f"{spec.identity} chain loops")
                break
            seen.add(end.identity)
            end = by_id.get(end.replaced_by)
        if end is None:
            problems.append(f"{spec.identity} links to a code that does not exist")
        elif end.deprecated_in is not None:
            problems.append(f"{spec.identity} chain has no live end")
    return problems


def test_every_successor_a_tombstone_names_is_live() -> None:
    assert tombstone_problems(reasons.specs()) == []


def test_a_reason_may_retire_with_no_successor() -> None:
    specs = {s.identity: s for s in reasons.specs()}
    spec = specs[("route", "when_reads_masked_column")]
    assert spec.deprecated_in is not None and spec.replaced_by is None
    assert tombstone_problems([spec]) == []


def test_a_successor_that_is_missing_or_retired_is_rejected() -> None:
    from dataclasses import replace

    live = next(s for s in reasons.specs() if s.deprecated_in is None)
    retired = next(s for s in reasons.specs() if s.deprecated_in and s.replaced_by is None)
    missing = replace(retired, replaced_by=("nowhere", "x"))
    assert "does not exist" in " ".join(tombstone_problems([missing]))
    dead_end = replace(live, replaced_by=None, deprecated_in="9.9.9", code="dead_end")
    pointing = replace(retired, replaced_by=dead_end.identity)
    assert "no live end" in " ".join(tombstone_problems([pointing, dead_end]))
