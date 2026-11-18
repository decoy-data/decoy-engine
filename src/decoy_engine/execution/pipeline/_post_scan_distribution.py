"""The glue between the post-scan gate and the distribution check (`post_scan.distribution`).

The gate owns the run's sources, casting and quarantine; the check itself is pure
(`verification.postmask.distribution`). This module holds what sits between them, so the gate
module gains calls and no logic:

- `distribution_refusal` decides, at bind time, whether the run can be checked at all. A mask table
  that declares transforms no longer lines up with its source, and a deferred gate (a loader run, or
  inputs the gate cannot read back) has no source to compare against. Both are refused before any
  route read, only when the check is asked for.
- `DistributionState` keeps the run's tolerance and the rows D8 quarantine removed from each table,
  which the gate cannot recover from a streamed source, and builds the check's input.

Counts and names only: nothing here reads or keeps a cell value.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping
from typing import TYPE_CHECKING, Any, Final, NoReturn

from decoy_engine import reasons
from decoy_engine.config import post_scan_distribution_tolerance
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution._transforms_gate import transform_bearing_mask_tables
from decoy_engine.reasons import ReasonCode
from decoy_engine.verification.postmask.distribution import DistributionInput, preserved_facts

if TYPE_CHECKING:
    from decoy_engine.execution._pipeline_context import PipelineRunContext
    from decoy_engine.verification.postmask import TableBatches

__all__ = [
    "DistributionState",
    "distribution_refusal",
    "refuse_transformed_integrity",
    "refuse_unchecked_distribution",
]

_ROW_ONLY: Final = frozenset({"row_count"})


def distribution_refusal(ctx: PipelineRunContext, *, deferred: bool) -> ReasonCode | None:
    """Why a run that asks for the distribution check must be refused before it starts, or `None`.

    A transform-bearing mask table comes first (the existing integrity refusal); a loader run or a
    deferred gate is refused with its own code. A run without the check is never refused here."""
    if post_scan_distribution_tolerance(ctx.config) is None or not ctx.has_mask_table:
        return None
    if transform_bearing_mask_tables(ctx.config):
        return reasons.runtime.POST_SCAN_INTEGRITY_TRANSFORMS_UNSUPPORTED
    if deferred or ctx.source_loader is not None:
        return reasons.runtime.POST_SCAN_DISTRIBUTION_DEFERRED
    return None


def refuse_transformed_integrity() -> NoReturn:
    """Refuse a run whose mask table declares transforms: the suite compares output with the raw
    source and a transformed table's rows no longer line up with it. The one raise of this code,
    for the staged commit and for the distribution check."""
    raise ExecutionError(
        code=reasons.runtime.POST_SCAN_INTEGRITY_TRANSFORMS_UNSUPPORTED,
        message=reasons.get(
            "runtime", reasons.runtime.POST_SCAN_INTEGRITY_TRANSFORMS_UNSUPPORTED
        ).summary,
    )


def refuse_unchecked_distribution(ctx: PipelineRunContext, *, deferred: bool) -> None:
    """Raise the refusal `distribution_refusal` names, with an empty exception chain. Literal
    symbols keep the ad-hoc-code sentry satisfied; the predicate keeps the two in step."""
    refusal = distribution_refusal(ctx, deferred=deferred)
    if refusal == reasons.runtime.POST_SCAN_INTEGRITY_TRANSFORMS_UNSUPPORTED:
        refuse_transformed_integrity()
    if refusal == reasons.runtime.POST_SCAN_DISTRIBUTION_DEFERRED:
        raise ExecutionError(
            code=reasons.runtime.POST_SCAN_DISTRIBUTION_DEFERRED,
            message=reasons.get("runtime", reasons.runtime.POST_SCAN_DISTRIBUTION_DEFERRED).summary,
        )


def _provider_config(column: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    raw = column.get("provider_config")
    return tuple(raw.items()) if isinstance(raw, Mapping) else ()


def _when(column: Mapping[str, Any]) -> bool:
    value = column.get("when")
    return isinstance(value, str) and bool(value.strip())


class DistributionState:
    """One run's distribution check: its tolerance and the D8 removals counted so far."""

    def __init__(self, tolerance_pct: float) -> None:
        self.tolerance_pct = tolerance_pct
        self._quarantined: dict[str, int] = {}

    @classmethod
    def for_run(cls, config: Mapping[str, Any]) -> DistributionState | None:
        tolerance = post_scan_distribution_tolerance(config)
        return None if tolerance is None else cls(tolerance)

    def note_quarantined(self, table: str, removed: Collection[int]) -> None:
        """Count rows D8 quarantine removed from `table`; the source side keeps them, so the
        expected output row count is the source count minus this."""
        if removed:
            self._quarantined[table] = self._quarantined.get(table, 0) + len(removed)

    def build(
        self,
        config: Mapping[str, Any],
        tables: Iterable[str],
        source_of: Callable[[str], TableBatches],
        *,
        cast_run: Any = None,
    ) -> DistributionInput:
        """The check's input for the mask `tables` the run output. Only a column the config names
        is checked, on the facts its strategy keeps; a generated table has no source and is not
        in `tables`. A table the run's declared cast reads may drop quarantined rows on read."""
        wanted = set(tables)
        columns: dict[str, dict[str, frozenset[Any]]] = {}
        for entry in config.get("tables") or ():
            if not isinstance(entry, Mapping) or entry.get("name") not in wanted:
                continue
            checked: dict[str, frozenset[Any]] = {}
            for column in entry.get("columns") or ():
                if not isinstance(column, Mapping) or not isinstance(column.get("name"), str):
                    continue
                facts = preserved_facts(
                    column.get("strategy"), _provider_config(column), conditional=_when(column)
                )
                if facts != _ROW_ONLY:
                    checked[column["name"]] = facts
            columns[str(entry["name"])] = checked
        return DistributionInput(
            tolerance_pct=self.tolerance_pct,
            columns=columns,
            sources={name: source_of(name) for name in columns},
            quarantined=dict(self._quarantined),
            cast_tables=frozenset(cast_run.tables() if cast_run is not None else ())
            & columns.keys(),
        )
