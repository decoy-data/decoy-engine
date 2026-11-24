"""Which columns a run may write, per table: the one answer execution and verification share.

`written_columns_by_table` reads the same declarations the chunked carry honors
(`column_access`), so a column a handler writes beyond its own (a joint mask's siblings, a
composite's bundle) counts as written here as it does there. A table whose writes cannot be
named is `Unknown`, and a caller treats it as "any column may be written". A table the result
does not name proves nothing either.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from decoy_engine.plan.column_access._declarations import (
    PASSTHROUGH_OUTPUT_IS_INPUT,
    column_access,
    provider_is_composite,
)


@dataclass(frozen=True)
class KnownEmpty:
    """No entry, transform or cascade writes any column of the table."""


@dataclass(frozen=True)
class KnownSet:
    """Exactly these columns may be written; every other column is the source column."""

    columns: frozenset[str]


@dataclass(frozen=True)
class Unknown:
    """Some writer cannot be named, so any column of the table may be written."""


TableWrites = KnownEmpty | KnownSet | Unknown


class ChildKey(Protocol):
    """The part of a relationship edge the query reads: the child end. A parent end is only
    looked up, so it writes nothing."""

    @property
    def child_table(self) -> str: ...

    @property
    def child_columns(self) -> tuple[str, ...]: ...


def may_write(writes: Mapping[str, TableWrites], table: str, column: str) -> bool:
    """Whether `column` of `table` may have been written. Only a known state proves it was not."""
    state = writes.get(table)
    if isinstance(state, KnownEmpty):
        return False
    if isinstance(state, KnownSet):
        return column in state.columns
    return True


def written_columns_by_table(
    config: Mapping[str, Any],
    *,
    schemas: Mapping[str, Sequence[str]],
    edges: Sequence[ChildKey],
    registry: Any,
) -> dict[str, TableWrites]:
    """The write state of every configured table, every table in `schemas` and every edge child.

    Written: each entry's own target unless its handler leaves the cell as it is (passthrough,
    whatever its `when:`), every column a declaration writes besides its own (joint mask
    siblings, composite bundles, `coherent_with` members), every `derive` target and every
    child key column of `edges`. `registry` is the one the run builds its work list with, so a
    composite it binds is a composite here. An entry whose writes cannot be named makes its table
    `Unknown`; a read that cannot be named does not.
    """
    tables_cfg = config.get("tables") or []
    configured: dict[str, Mapping[str, Any]] = {}
    malformed = not isinstance(tables_cfg, list)
    for table in tables_cfg if not malformed else ():
        if isinstance(table, Mapping) and isinstance(table.get("name"), str):
            configured[table["name"]] = table
        else:
            malformed = True
    names = dict.fromkeys([*configured, *schemas, *(e.child_table for e in edges)])
    if malformed:  # a table entry with no name may describe any table
        return {name: Unknown() for name in names}
    cascaded: dict[str, set[str]] = {}
    for edge in edges:
        cascaded[edge.child_table] = cascaded.get(edge.child_table, set()) | set(edge.child_columns)
    result: dict[str, TableWrites] = {}
    for name in names:
        written = _table_writes(configured.get(name), registry)
        if written is None:
            result[name] = Unknown()
            continue
        columns = written | cascaded.get(name, set())
        result[name] = KnownSet(frozenset(columns)) if columns else KnownEmpty()
    return result


def _table_writes(table: Mapping[str, Any] | None, registry: Any) -> frozenset[str] | None:
    if table is None:
        return frozenset()
    entries = table.get("columns") or []
    ops = table.get("transforms") or []
    if not isinstance(entries, list) or not isinstance(ops, list):
        return None
    written = _entry_writes(entries, registry)
    targets = _derive_targets(ops)
    if written is None or targets is None:
        return None
    return written | targets


def _entry_writes(entries: Iterable[Any], registry: Any) -> frozenset[str] | None:
    written: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("name"), str):
            return None
        access = column_access(entry, registry)
        if access.writes_unknown:
            return None
        written |= access.writes
        if not _leaves_cell(entry, registry):
            written.add(entry["name"])
    return frozenset(written)


def _leaves_cell(entry: Mapping[str, Any], registry: Any) -> bool:
    """A passthrough entry writes nothing, `when:` or not: both branches keep the cell. The
    provider decides a composite first, as `build_work_list` does."""
    if provider_is_composite(entry.get("provider"), registry):
        return False
    return entry.get("strategy") == "passthrough" and PASSTHROUGH_OUTPUT_IS_INPUT


# The transform ops that move or drop rows and columns and write no cell. `derive` writes its
# target. Any other op is unclassified, so its table is `Unknown` until it is added to one side.
NON_WRITING_OPS: frozenset[str] = frozenset({"filter", "sort", "limit", "dedupe", "drop_column"})


def _derive_targets(ops: Iterable[Any]) -> frozenset[str] | None:
    """Every `derive` target, or None when some op is malformed or not a known op."""
    targets: set[str] = set()
    for op in ops:
        if not isinstance(op, Mapping):
            return None
        kind = op.get("op")
        if kind == "derive":
            column = op.get("column")
            if not isinstance(column, str):
                return None
            targets.add(column)
        elif kind not in NON_WRITING_OPS:
            return None
    return frozenset(targets)


def config_child_keys(config: Mapping[str, Any]) -> tuple[ChildKey, ...] | None:
    """The relationship edges a run compiles from `config` alone, through the expansion the
    profile uses (`profile_relationships_from_config`), or None when some entry does not parse.
    A caller with no compiled graph (the standalone post-scan) uses this. None is not an empty
    list: the caller makes every table `Unknown`."""
    from decoy_engine.profile import profile_relationships_from_config

    declared = config.get("relationships") or []
    if not isinstance(declared, list):
        return None
    expected = 0
    for rel in declared:
        children = rel.get("children") if isinstance(rel, Mapping) else None
        if not isinstance(children, list):
            return None
        expected += len(children)
    edges = profile_relationships_from_config(declared)
    return edges if len(edges) == expected else None
