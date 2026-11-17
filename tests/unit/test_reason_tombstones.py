"""Every retired reason identity links to a live replacement."""

from __future__ import annotations

from decoy_engine import reasons


def test_no_tombstone_without_a_live_replacement() -> None:
    for spec in reasons.specs():
        if spec.deprecated_in is None:
            continue
        assert spec.replaced_by is not None, f"{spec.identity} is retired with no replacement"
        end = reasons.get(*spec.replaced_by)
        seen = {spec.identity, end.identity}
        for _ in range(3):  # a tombstone's shipped pin cannot move, so a chain may be a few links
            if end.deprecated_in is None or end.replaced_by is None:
                break
            end = reasons.get(*end.replaced_by)
            assert end.identity not in seen, f"{spec.identity} chain loops"
            seen.add(end.identity)
        assert end.deprecated_in is None, f"{spec.identity} chain has no live end"
