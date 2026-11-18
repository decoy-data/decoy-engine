"""Prohibitions of the pipeline `policy` block, checked on the explicit result.

A prohibition runs after every mask field has its decision, so it sees a column's own level 1
strategy as well as an expanded one. `forbid` refuses a field whose strategy is in the list;
`require` refuses a field whose strategy is not. A prohibition that selects no field is not an
error: it is reported with `matched: 0`. Only config names and strategy names are read.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from decoy_engine.config.policy._policy import Prohibition
from decoy_engine.config.policy._selectors import FieldFacts, matches

__all__ = ["ProhibitionMatch", "Violation", "evaluate_prohibitions"]


@dataclass(frozen=True)
class ProhibitionMatch:
    """How many mask fields one prohibition selected."""

    id: str
    matched: int


@dataclass(frozen=True)
class Violation:
    """One field a prohibition refuses. `index` is the prohibition's place in `policy.prohibit`."""

    index: int
    id: str
    field: str
    strategy: str


def _refused(prohibition: Prohibition, strategy: str) -> bool:
    if prohibition.forbid is not None:
        return strategy in prohibition.forbid
    return strategy not in (prohibition.require or ())


def evaluate_prohibitions(
    prohibitions: Sequence[tuple[int, Prohibition]],
    decided: Sequence[tuple[FieldFacts, str]],
) -> tuple[tuple[ProhibitionMatch, ...], tuple[Violation, ...]]:
    """Match each `(index, prohibition)` against every `(facts, decided strategy)` field."""
    found: list[ProhibitionMatch] = []
    violations: list[Violation] = []
    for index, prohibition in prohibitions:
        hits = [
            (facts, strategy) for facts, strategy in decided if matches(prohibition.select, facts)
        ]
        found.append(ProhibitionMatch(prohibition.id, len(hits)))
        violations.extend(
            Violation(index, prohibition.id, f"{facts.table}.{facts.column}", strategy)
            for facts, strategy in hits
            if _refused(prohibition, strategy)
        )
    return tuple(found), tuple(violations)
