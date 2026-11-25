"""Which field names repeat in a source schema or frame.

The shared scan behind every duplicate-name refusal: the run entry and ingest guards
(`execution._guards`), the profile walks and the name-keyed carry and slice admission. The
wording is shared too (`duplicate_names_message`); each boundary keeps its own exception.
Dependency-free on purpose, so profile and execution can both import it.
"""

from __future__ import annotations

from collections.abc import Iterable


class DuplicateFieldNamesError(ValueError):
    """A profiled source repeats a field name. Its text is `duplicate_names_message`; the type
    is how a boundary that strips other failures to a label tells this one apart by identity,
    not by its words."""


def repeated_names(names: Iterable[str]) -> frozenset[str]:
    """The names that appear more than once, empty when every name is unique."""
    seen: set[str] = set()
    repeated: set[str] = set()
    for name in names:
        (repeated if name in seen else seen).add(name)
    return frozenset(repeated)


def duplicate_names_message(table: str, names: Iterable[str]) -> str | None:
    """The refusal text for a source whose names repeat, or `None` when they are unique.

    It carries the table (a config key) and a count, never the names: a header is
    producer-controlled text, so no engine message may repeat it."""
    repeated = repeated_names(names)
    if not repeated:
        return None
    return f"table {table!r} has {len(repeated)} duplicated field name(s)"
