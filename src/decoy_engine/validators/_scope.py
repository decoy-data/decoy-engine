"""What leak_check checks: the scope of one entry, planned from the config alone.

``plan_scope`` is the one place that decides, for each (table, column) a ``leak_check`` entry
covers, whether the column is checked or skipped and why. The validator fold reads the plan at
run time, and ``decoy validate`` calls the same function, so a config that names a column the
check cannot see is reported before any data is read.

Strategy classification is the false-positive control (trap T1). The three frozensets are
exhaustive over ``SCALAR_HANDLERS`` (``execution/_strategies/__init__.py``);
``tests/unit/validators/test_leak_check.py::TestDriftSentry`` fails the build if a strategy is
added without a classification decision.

A skip that depends on the data (a column missing from the output or source, fewer than
``min_rows`` non-null cells, a table the run did not produce) is recorded by the fold, not here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from decoy_engine import reasons
from decoy_engine.config import classify_table_kinds
from decoy_engine.validators._types import SkippedColumn

if TYPE_CHECKING:
    from decoy_engine.validators._types import ValidationReport

# ---------------------------------------------------------------------------
# Strategy classification (D3). Exhaustive over SCALAR_HANDLERS; the drift
# sentry test asserts this.
# ---------------------------------------------------------------------------

TRANSFORMATIVE: frozenset[str] = frozenset(
    {"hash", "fpe", "tokenize", "redact", "text_redact", "faker", "code_set"}
)

SHAPE_PRESERVING: frozenset[str] = frozenset(
    {
        "bucketize",
        "bucket_perturb",
        "categorical",
        "date_shift",
        "derived",
        "derived_aggregate",
        "formula",
        "geo_generalize",
        "group_key",
        "grouped_series",
        "joint_mask",
        "nested",
        "shuffle",
        "text_mask",
        "top_code",
        "truncate",
        "windowed_date",
    }
)

EXCLUDED: frozenset[str] = frozenset({"passthrough"})

# Composite bundle generators (execution/_strategies/_composite.py's explicit
# provider dispatch, mirrored here rather than re-derived). A column whose
# `provider` is one of these is a composite-bundle member; see the GATE note
# in the module docstring for the TRANSFORMATIVE classification rationale.
_COMPOSITE_PROVIDERS: frozenset[str] = frozenset(
    {
        "composite_name_email",
        "composite_city_state_zip",
        "composite_person",
        "composite_address",
        "composite_provider",
        "composite_custom",
    }
)


def _fk_child_columns(config: Mapping[str, Any]) -> set[tuple[str, str]]:
    """(table, column) pairs that are FK children: values come from the
    parent's masked key map, not the declared strategy. A leaking parent is
    caught on the parent column instead."""
    out: set[tuple[str, str]] = set()
    for rel in config.get("relationships") or []:
        if not isinstance(rel, dict):
            continue
        for child in rel.get("children") or []:
            if not isinstance(child, dict):
                continue
            table_name = child.get("table")
            if not isinstance(table_name, str):
                continue
            for col in child.get("columns") or []:
                if isinstance(col, str):
                    out.add((table_name, col))
    return out


def _column_entries(config: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """(table, column) -> column config entry, for every mask-kind table."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for table in config.get("tables") or []:
        if not isinstance(table, dict) or not isinstance(table.get("name"), str):
            continue
        table_name = table["name"]
        for col in table.get("columns") or []:
            if isinstance(col, dict) and isinstance(col.get("name"), str):
                out[(table_name, col["name"])] = col
    return out


@dataclass(frozen=True)
class ScopedColumn:
    """One column a leak_check entry covers.

    ``skip`` is the registered code when the config alone rules the column out. ``kind`` says
    how the verdict reads the column: ``transformative`` columns are checked at both tiers,
    ``shape`` columns only for a strategy that changed nothing, and ``unclassified`` fails closed
    when the column is reached.
    """

    table: str
    column: str
    strategy: str | None
    kind: Literal["transformative", "shape", "unclassified"]
    skip: str | None


@dataclass(frozen=True)
class ScopePlan:
    """The tables and columns of one leak_check entry, in scope order."""

    columns: tuple[ScopedColumn, ...]

    @property
    def tables(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(c.table for c in self.columns))

    def config_skips(self) -> tuple[SkippedColumn, ...]:
        """Columns the config rules out, with their codes (no data needed)."""
        return tuple(SkippedColumn(c.table, c.column, c.skip) for c in self.columns if c.skip)


def plan_scope(config: Mapping[str, Any], entry: Mapping[str, Any]) -> ScopePlan:
    """Plan one leak_check entry.

    Default scope (no `columns:` on the entry): every column of every mask-kind table. An
    explicit `columns:` entry that names a generate-kind table is a config error (no source can
    ever exist for it), raised rather than skipped.

    Raises:
        ValueError: An explicit `columns:` entry names a generate-kind table.
    """
    params: dict[str, Any] = entry.get("params") or {}
    exempt: dict[str, list[str]] = params.get("exempt") or {}
    exempt_set = {(table, col) for table, cols in exempt.items() for col in cols}
    table_kinds = classify_table_kinds(dict(config))
    fk_children = _fk_child_columns(config)
    col_entries = _column_entries(config)

    explicit: dict[str, list[str]] = entry.get("columns") or {}
    if explicit:
        scope: dict[str, list[str]] = {}
        for table_name, cols in explicit.items():
            if table_kinds.get(table_name) == "generate":
                raise ValueError(
                    f"leak_check: columns: explicitly names {table_name!r}, which is a "
                    "generate-kind table (no source column exists to compare against). "
                    "Remove it from leak_check's columns: scope."
                )
            scope[table_name] = list(cols)
    else:
        scope = {
            table_name: [c["name"] for c in table.get("columns") or [] if isinstance(c, dict)]
            for table in (config.get("tables") or [])
            if isinstance(table, dict)
            and isinstance(table.get("name"), str)
            and (table_name := table["name"]) in table_kinds
            and table_kinds[table_name] == "mask"
        }

    planned: list[ScopedColumn] = []
    for table_name, col_names in scope.items():
        for col_name in col_names:
            col_entry = col_entries.get((table_name, col_name), {})
            strategy = col_entry.get("strategy")
            provider = col_entry.get("provider")
            when = col_entry.get("when")
            skip: str | None = None
            if (table_name, col_name) in exempt_set:
                skip = reasons.warning.LEAK_CHECK_SKIP_EXEMPT
            elif (table_name, col_name) in fk_children:
                skip = reasons.warning.LEAK_CHECK_SKIP_FK_CHILD
            elif isinstance(when, str) and when.strip():
                skip = reasons.warning.LEAK_CHECK_SKIP_WHEN
            elif strategy in EXCLUDED:
                skip = reasons.warning.LEAK_CHECK_SKIP_PASSTHROUGH
            kind: Literal["transformative", "shape", "unclassified"] = "unclassified"
            if strategy in TRANSFORMATIVE or provider in _COMPOSITE_PROVIDERS:
                kind = "transformative"
            elif strategy in SHAPE_PRESERVING:
                kind = "shape"
            planned.append(ScopedColumn(table_name, col_name, strategy, kind, skip))
    return ScopePlan(tuple(planned))


def unchecked_named_columns(
    config: Mapping[str, Any], report: ValidationReport
) -> tuple[SkippedColumn, ...]:
    """Columns a leak_check entry names in ``columns:`` and then did not check.

    A column that comes from the default scope is not named, so skipping it is not a surprise;
    one the config names explicitly is, and the run reports it as a warning.
    """
    entries = config.get("validators") or []
    named: list[SkippedColumn] = []
    for result in report.results:
        if result.validator != "leak_check" or result.entry_index >= len(entries):
            continue
        if not (entries[result.entry_index] or {}).get("columns"):
            continue
        named.extend(skip for skip in result.skipped if skip.column is not None)
    return tuple(named)
