"""The group_key sibling gate of the unified-slice admission predicate, split out of
`_unified_slice_admission.py` (pure move) to hold its size census. The per-strategy
target-type domains are on the operator registry (`OperatorSpec.resident_type_domain`)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pyarrow as pa

if TYPE_CHECKING:
    from decoy_engine.execution.physical._plan import PhysicalTable


def _group_key_sibling_admitted(
    binding: Any, physical_table: PhysicalTable, source: pa.Table
) -> bool:
    """Whether a bound group_key node's `group_by` SIBLING column is admissible:
    resident, an admitted type (v1: `{string, int64, bool}` via
    `group_key_sibling_type_admitted`), matching the binding's input_schema, and
    NOT itself masked by another node in the table (the order-dependence
    decline).

    Runs on the SIBLING, not the target: the oracle keys on `df[group_by]` at
    group_key's execution point, so native parity holds only when
    `batch.column(group_by)` (the original source value) equals what the oracle
    reads -- which requires the sibling to be resident, safe-typed, and left
    UNMASKED (a passthrough node). A masked sibling means the pandas adapter
    would have mutated that column in the frame before group_key reads it, so
    native declines to the oracle (v1 does not model the effective-input
    dependency)."""
    from decoy_engine.execution.native._operator_config_rejections import (
        group_key_sibling_type_admitted,
    )

    group_by = binding.group_key_sibling
    if not isinstance(group_by, str) or not group_by:
        return False
    if group_by not in source.schema.names:
        # A non-resident sibling declines cleanly (never a raising KeyError).
        return False
    sibling_type = source.schema.field(group_by).type
    if not group_key_sibling_type_admitted(sibling_type):
        # float / decimal / dictionary (and any unlisted type) decline.
        return False
    # Track A Option 2 guard reconciliation: `execution_binding_for_slice_node`
    # now builds `input_schema` from this SAME resident sibling type (not a
    # profile re-read), so comparing the two types here would always be true --
    # a tautology, not a check. What is still load-bearing is the STRUCTURAL
    # shape (exactly one field, named `group_by`): a binding of any other shape
    # would be a compiler bug, not a resident-type question.
    input_schema = binding.input_schema
    if len(input_schema) != 1 or input_schema.names != [group_by]:
        return False
    # Order-dependence: the sibling must be an UNMASKED (passthrough) node. Any
    # other node masking it means the oracle would key on the mutated value.
    for other in physical_table.nodes:
        if group_by in other.columns and other.strategy != "passthrough":
            return False
    return True
