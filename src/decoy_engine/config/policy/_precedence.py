"""The one precedence registry of the pipeline `policy` block.

Five levels, lowest number wins. `selector_level` is the only function that assigns a level to a
rule selector: it walks `_SELECTOR_LEVELS`, first match wins, and the last entry is a catch-all.
The column's own strategy is always level 1, the disguise rule for the column's classification is
level 4 and `policy.default` is level 5; neither is a selector, so they are not in the registry.

Specificity ordering follows CSS specificity and dbt's config hierarchy; a tie at equal level is
refused by the expansion instead of broken by order.
"""

from __future__ import annotations

import enum
from collections.abc import Callable

from decoy_engine.config.policy._selectors import Selector, has_glob

__all__ = ["PrecedenceLevel", "selector_level"]


class PrecedenceLevel(enum.IntEnum):
    """Lower value wins. `.label` is the stable name an explanation prints."""

    EXACT_FIELD = 1
    EXACT_OBJECT_OR_CLASSIFICATION = 2
    SCOPED_PATTERN = 3
    CLASSIFICATION_DEFAULT = 4
    GLOBAL_DEFAULT = 5

    @property
    def label(self) -> str:
        return self.name.lower()


def _literal(value: str | None) -> bool:
    return value is None or not has_glob(value)


def _column_without_table(selector: Selector) -> bool:
    return selector.column is not None and selector.table is None


def _exact_field(selector: Selector) -> bool:
    """A literal column, with a literal table when one is given, and nothing else."""
    return (
        selector.column is not None
        and selector.present_keys() <= {"table", "column"}
        and _literal(selector.table)
        and _literal(selector.column)
    )


def _exact_object_or_classification(selector: Selector) -> bool:
    """A literal table alone, a classification alone, or both, with no glob."""
    return selector.present_keys() in (
        frozenset({"table"}),
        frozenset({"classification"}),
        frozenset({"table", "classification"}),
    ) and _literal(selector.table)


def _anything(selector: Selector) -> bool:
    return True


# (predicate, level), first match wins. A column literal with no table is a pattern over all
# tables, so it sits above the exact-field entry, which accepts any literal column.
_SELECTOR_LEVELS: tuple[tuple[Callable[[Selector], bool], PrecedenceLevel], ...] = (
    (_column_without_table, PrecedenceLevel.SCOPED_PATTERN),
    (_exact_field, PrecedenceLevel.EXACT_FIELD),
    (_exact_object_or_classification, PrecedenceLevel.EXACT_OBJECT_OR_CLASSIFICATION),
    (_anything, PrecedenceLevel.SCOPED_PATTERN),
)


def selector_level(selector: Selector) -> PrecedenceLevel:
    """The level of a rule with this selector."""
    for predicate, level in _SELECTOR_LEVELS:
        if predicate(selector):
            return level
    raise AssertionError("the registry ends with a catch-all")
