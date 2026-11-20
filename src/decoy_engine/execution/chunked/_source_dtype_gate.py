"""The planner's source-dtype gate for the chunked lane.

A source column the pandas round trip alters per chunk keeps a table off the lane. A carried
passthrough column (`_chunked_carry.carried_columns`) never reaches pandas, so its type cannot
alter anything and the gate skips it. A masked column is skipped only when its (strategy, type
class) pair is in `CHUNK_STABLE_MASKED_SOURCE_TYPES`: the strategy reads that source type
exactly on every chunk and its output type is pinned by the chunked schema rule.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.types as pat

from decoy_engine.execution._chunked_carry import read_set
from decoy_engine.execution._column_access import has_when
from decoy_engine.execution._strategies._redact import redact_with_is_string
from decoy_engine.execution.native._faker_deterministic_admission import (
    is_effective_deterministic_faker,
)

if TYPE_CHECKING:
    from decoy_engine.execution._chunked_input import SourceFacts

INT_WITH_NULLS = "int_with_nulls"
DECIMAL = "decimal"
BINARY = "binary"

# strategy -> the source type classes it reads exactly on every chunk. A row needs a green
# parity cell (tests/parity/test_nonfk_dtype_matrix.py derives its cells from this table); a
# row whose cell is red is removed, never relaxed.
CHUNK_STABLE_MASKED_SOURCE_TYPES: Mapping[str, frozenset[str]] = {
    "hash": frozenset({INT_WITH_NULLS, DECIMAL, BINARY}),
    "redact": frozenset({INT_WITH_NULLS, DECIMAL, BINARY}),
    "faker": frozenset({INT_WITH_NULLS}),
}


def type_class(arrow_type: pa.DataType, null_count: int) -> str | None:
    """The admission class of a source type, or None when it has none."""
    if pat.is_integer(arrow_type) and null_count > 0:
        return INT_WITH_NULLS
    if pat.is_decimal(arrow_type):
        return DECIMAL
    if (
        pat.is_binary(arrow_type)
        or pat.is_large_binary(arrow_type)
        or pat.is_fixed_size_binary(arrow_type)
    ):
        return BINARY
    return None


def _config_admits(entry: Mapping[str, Any]) -> bool:
    """The configuration under which a table row holds: no `when:`, a string `redact_with`, a
    deterministic faker (the shared faker predicate). Membership of the strategy in the table is checked by the caller."""
    strategy = entry.get("strategy")
    if has_when(entry):
        return False  # a gated entry sees a per-chunk frame, and gated hash is not exact-int
    if strategy == "redact":
        return redact_with_is_string(entry.get("provider_config") or {})
    if strategy == "faker":
        return is_effective_deterministic_faker(entry)
    return True


def admitted_masked_columns(
    facts: SourceFacts, entries: Iterable[Mapping[str, Any]], registry: Any
) -> frozenset[str]:
    """Masked columns whose (strategy, type class) pair is admitted and that no other entry
    reads, so no `when:` predicate or sibling reference sees the per-chunk pandas dtype."""
    entries = list(entries)
    types = {f.name: f.type for f in facts.schema}
    # `read_set` is the one membership rule (NFKC-normalised names, fail closed when a
    # declaration cannot be computed), shared with the carried exemption.
    read = read_set(entries, types, registry)
    admitted: set[str] = set()
    for entry in entries:
        name = entry.get("name")
        strategy = entry.get("strategy")
        if not isinstance(name, str) or name not in types or name in read:
            continue
        classes = (
            CHUNK_STABLE_MASKED_SOURCE_TYPES.get(strategy) if isinstance(strategy, str) else None
        )
        if classes is None or not _config_admits(entry):
            continue
        if type_class(types[name], facts.null_count(name) or 0) in classes:
            admitted.add(name)
    return frozenset(admitted)


def unstable_source_columns(
    facts: SourceFacts,
    *,
    declared_stable: Collection[str] = (),
    declared_bad: Collection[str] = (),
    carried: Collection[str] = (),
    masked_ok: Collection[str] = (),
) -> list[str]:
    """Labels of the source columns whose pandas round trip is not chunk-stable.

    `declared_*` are the F06 declared-cast columns, judged by the type the cast leaves; a
    `carried` column is exempt, whatever its type, and so is a `masked_ok` column."""
    unstable = [f"{n} (declared, no output_format)" for n in sorted(declared_bad)]
    skip = {*declared_stable, *declared_bad, *carried, *masked_ok}
    for schema_field in facts.schema:
        t = schema_field.type
        if schema_field.name in skip:
            continue
        if pat.is_integer(t):
            # pandas widens int+null to float PER FRAME, so a null-free chunk keeps int64
            # while a null-bearing one becomes float64; only a null-free integer column
            # round-trips chunk-stably.
            if (facts.null_count(schema_field.name) or 0) > 0:
                unstable.append(f"{schema_field.name} (integer with nulls)")
        elif not (
            pat.is_string(t)
            or pat.is_large_string(t)
            or pat.is_floating(t)
            or pat.is_boolean(t)
            or pat.is_temporal(t)
            or pat.is_null(t)
        ):
            unstable.append(f"{schema_field.name} ({t})")
    return unstable
