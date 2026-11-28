"""Completed-execution evidence for the unified-slice lane (D7), assembled purely.

`assemble_node_evidence` turns the coordinator's per-node operator evidence and the
timing collector's records into the JSON-safe `nodes` leaf under
`quality_metrics["unified_slice_activation"]`. It takes no context, so every invariant
is unit-testable without running a pipeline. Each node entry carries structured plan
attribution (`table`, `columns`, `strategy`, read from the plan node, not parsed from
`node_id`, whose separators column names may themselves contain), the fields the chunked
route publishes per column (`planned_backend`, `executed_backend`, `calls`), and the
original three, and the executed backend comes from the one rule the chunked route also
uses (`_chunked_evidence.executed_backend`). Elapsed time is NOT published here: as
on the chunked route (`_pipeline_auto_chunk._without_elapsed`), it lives only in
`ExecutionResult.timings` so `quality_metrics` stays deterministic. The timing records are
still checked one-to-one against the nodes, which guarantees every node has exactly one
`timings` entry under its `(strategy, column)`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import numpy as np
import pyarrow as pa

from decoy_engine._execution_error import source_column_unrepresentable
from decoy_engine.execution import _unified_slice_admission as _admission
from decoy_engine.execution._operator_registry import OPERATORS
from decoy_engine.execution._unified_slice import UnifiedSliceInvariantError
from decoy_engine.execution.native import _chunked_evidence
from decoy_engine.execution.native._operator_params import FakerParams
from decoy_engine.execution.pipeline._source_types import table_from_pandas_keeping_source_types
from decoy_engine.internal.pandas_compat import arrow_to_series

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping

    import pandas as pd

    from decoy_engine.execution.physical._plan import PhysicalNode
    from decoy_engine.execution.physical._shadow_operators import OperatorCallEvidence
    from decoy_engine.instrumentation.timing import StrategyTimingRecord

__all__ = ["assemble_node_evidence", "reconstruct_source_shaped_output"]

# Operators whose "the compiled kernel really ran" claim must be observed, not
# inferred: a completed node of one of these without positive evidence is an
# admission bug, unless it saw no rows (the position-keyed Faker never calls its kernel
# on an empty table, so it reports `arrow_python` like an idle chunked column). The
# value-dependent kernels (bucket_perturb, date_shift, group_key) are deliberately absent:
# running no compiled call on idle input is legitimate and is reported as `arrow_python`
# instead of failing.
# Derived from the operator registry (`positive_kernel_evidence`); edit the registry.
_POSITIVE_KERNEL_EVIDENCE_OPERATOR_IDS: Final = frozenset(
    spec.operator_id for spec in OPERATORS.values() if spec.positive_kernel_evidence
)


def _is_positional_faker(binding: Any) -> bool:
    # A positional Faker draw on zero rows never calls the kernel; every other operator
    # still must, so an idle kernel on an empty table stays a defect for them.
    return isinstance(binding.params, FakerParams) and binding.params.positional


def _timing_by_node(
    nodes: Iterable[PhysicalNode], timing_records: Iterable[StrategyTimingRecord]
) -> dict[str, float]:
    """Check the collector's records are one-to-one with the nodes on `(strategy, column)`.

    Production calls this only for the check; the returned node-to-elapsed mapping
    exists so the attribution can be tested directly.

    The coordinator opens one `timed_strategy(node.strategy, ",".join(node.columns))`
    scope per node, and admission makes each pair unique, so anything but exactly one
    record per node (and no record without a node) is a bug."""
    keys = {node.node_id: (node.strategy, ",".join(node.columns)) for node in nodes}
    by_key: dict[tuple[str, str], float] = {}
    for record in timing_records:
        key = (record.strategy_type, record.column)
        if key in by_key:
            raise UnifiedSliceInvariantError(
                f"unified slice: duplicate timing record for {key!r}; admitted nodes are "
                "unique per (strategy, column)."
            )
        by_key[key] = record.elapsed_ms
    missing = sorted(set(keys.values()) - set(by_key))
    extra = sorted(set(by_key) - set(keys.values()))
    if missing or extra:
        raise UnifiedSliceInvariantError(
            f"unified slice: timing records do not match the admitted nodes "
            f"(missing={missing}, unexpected={extra})."
        )
    return {node_id: by_key[key] for node_id, key in keys.items()}


def assemble_node_evidence(
    nodes: Iterable[PhysicalNode],
    route_evidence: Mapping[str, OperatorCallEvidence],
    timing_records: Iterable[StrategyTimingRecord],
) -> dict[str, dict[str, Any]]:
    """Validate completed execution against the admitted plan and return per-node evidence.

    Raises `UnifiedSliceInvariantError` for a missing or not-executed node, an operator
    mismatch, a hash or Faker node that saw rows without positive kernel evidence, or timing
    records that are not one-to-one with the nodes."""
    nodes = tuple(nodes)
    _timing_by_node(nodes, timing_records)
    node_evidence: dict[str, dict[str, Any]] = {}
    for node in nodes:
        binding = node.execution
        if binding is None:  # pragma: no cover - excluded by resident_contract_admission
            raise UnifiedSliceInvariantError(
                f"unified slice: node {node.node_id!r} lost its admitted binding "
                "between admission and execution."
            )
        evidence = route_evidence.get(node.node_id)
        if (
            evidence is None
            or not evidence.executed
            or evidence.actual_operator != binding.operator_id
        ):
            raise UnifiedSliceInvariantError(
                f"unified slice: node {node.node_id!r} completed without matching "
                "completed-execution evidence."
            )
        if (
            binding.operator_id in _POSITIVE_KERNEL_EVIDENCE_OPERATOR_IDS
            and not evidence.compiled_kernel_executed
            and not (evidence.rows_seen == 0 and _is_positional_faker(binding))
            # A `when:` node whose mask selected nothing never calls its kernel.
            and evidence.rows_selected != 0
        ):
            raise UnifiedSliceInvariantError(
                f"unified slice: {binding.operator_id} node {node.node_id!r} completed "
                "without positive compiled-kernel evidence."
            )
        planned = _admission.BACKEND_BY_OPERATOR_ID[binding.operator_id]
        # Arrow operators never run a compiled kernel, so they are never "idle".
        kernel_idle = planned != _chunked_evidence.ARROW_PYTHON and not (
            evidence.compiled_kernel_executed
        )
        node_evidence[node.node_id] = {
            # Structured attribution from the plan node (OBS-2a). The node_id
            # concatenates these with `:`/`+` separators that column names may
            # themselves contain, so a consumer must read them here, not split
            # the id. table/columns/strategy are schema identifiers, not values.
            "table": node.table,
            "columns": list(node.columns),
            "strategy": node.strategy,
            "operator": evidence.actual_operator,
            "executed": evidence.executed,
            "compiled_kernel_executed": evidence.compiled_kernel_executed,
            "planned_backend": planned,
            "executed_backend": _chunked_evidence.executed_backend(
                planned, native_admitted=True, kernel_idle=kernel_idle
            ),
            "calls": evidence.batches_run,
            **(
                {"preserved_rows": evidence.preserved_rows}
                if evidence.preserved_rows is not None
                else {}
            ),
        }
    return node_evidence


def _when_mask_of(
    node: PhysicalNode, when_selected: Mapping[str, np.ndarray[Any, np.dtype[np.bool_]]] | None
) -> np.ndarray[Any, np.dtype[np.bool_]]:
    mask = (when_selected or {}).get(node.node_id)
    if mask is None:
        raise UnifiedSliceInvariantError(
            f"unified slice: when node {node.node_id!r} reached reconstruction without a mask."
        )
    return mask


def _write_back_when(
    frame: pd.DataFrame,
    column: str,
    masked_col: pa.ChunkedArray,
    selected: np.ndarray[Any, np.dtype[np.bool_]],
) -> None:
    """Replay the oracle's `when:` gate on the frame: the handler writes a list onto a copy of
    the selected rows, and `.loc` copies that back, so the column keeps its own dtype and
    unselected rows keep their source values. A mask that selects nothing leaves the frame
    untouched, as the gate returns it."""
    if not selected.any():
        return
    sub = frame.loc[selected].copy()
    sub[column] = masked_col.filter(pa.array(selected, type=pa.bool_())).to_pylist()
    frame.loc[selected, column] = sub[column]


def reconstruct_source_shaped_output(
    *,
    table: str,
    frame: pd.DataFrame,
    source: pa.Table,
    untouched: Collection[str],
    masked_table: pa.Table,
    nodes: Iterable[PhysicalNode],
    when_selected: Mapping[str, np.ndarray[Any, np.dtype[np.bool_]]] | None = None,
    degenerate_pin: frozenset[str] = frozenset(),
) -> dict[str, pa.Table]:
    # Source-shaped reconstruction: `source_frame` is the same source-aware pandas conversion
    # the full-frame adapter does, a masked column's `to_pylist()` is assigned positionally as
    # each tokenizing handler does, and the one assembler writes the table: untouched columns
    # come from the source Arrow column, the rest through `from_pandas`.
    # A zero-row overlay of `to_pylist()` would give pandas `float64`, so an empty table assigns
    # `to_pandas()`, which carries the coordinator's empty dtype for the column.
    empty = masked_table.num_rows == 0
    for node in nodes:
        if node.strategy == "passthrough":
            continue
        column = node.columns[0]
        masked_col = masked_table.column(column)
        if node.execution is not None and node.execution.when_expression is not None:
            _write_back_when(frame, column, masked_col, _when_mask_of(node, when_selected))
            continue
        frame[column] = (
            arrow_to_series(
                masked_col, on_unrepresentable=source_column_unrepresentable(), name=column
            )
            if empty
            else masked_col.to_pylist()
        )
    from decoy_engine.execution._faker_degenerate_pin import pin_degenerate_to_string

    # C5c-ii option A: an all-null/empty admitted deterministic-Faker column over bool/int/uint is
    # `string` here too, matching the full-frame oracle so the flag-on/flag-off D9 parity holds.
    out = pin_degenerate_to_string(
        table_from_pandas_keeping_source_types(frame, source, untouched), degenerate_pin
    )
    return {table: out}
