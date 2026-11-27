"""Which `when:` columns the chunked native route can run, from config and the first chunk.

One verdict (`when_native_rejection`) for every consumer: the route decision
(`_dispatch.plan_native_route`), the output-type pin (`_chunked_schema_rule`) and the
auto-chunk planner. The row mask itself comes from the oracle's own predicate function
(`_when_mask`), so any predicate in the closed grammar qualifies; what this module decides
is whether the COLUMN around it is one the masked kernel step reproduces exactly:

1. the strategy is hash, redact, truncate, deterministic categorical, text_redact, bucket_perturb
   or date_shift, and its own config
   passes the same config-only gate the native route already applies;
2. the target source type is `string`, because the masked step selects between two string
   arrays;
3. the predicate parses under the closed grammar (a raw-dict predicate outside it declines);

A predicate may read a column an earlier work node masks: every route evaluates it on the
original values (WHEN-READS-SOURCE), and the native row mask reads the raw chunk.

Rule 1 and 2 keep the long-standing `when_predicate_not_native:<column>` code.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pyarrow as pa

from decoy_engine import reasons
from decoy_engine.execution._column_access import has_when
from decoy_engine.execution.native._route_decline_codes import (
    CodedDecline,
    RouteDeclineCode,
    coded,
)
from decoy_engine.expressions._when_parser import (
    WhenExpr,
    parse_when,
    when_column_refs,
)

NOT_NATIVE_CODE = reasons.runtime.WHEN_PREDICATE_NOT_NATIVE
OUTSIDE_SUBSET_CODE = reasons.runtime.WHEN_PREDICATE_OUTSIDE_NATIVE_SUBSET

ADMITTED_WHEN_STRATEGIES = frozenset(
    {"hash", "redact", "truncate", "categorical", "text_redact", "bucket_perturb", "date_shift"}
)


def table_column_entries(config: Mapping[str, Any], table: str) -> list[Mapping[str, Any]]:
    """The dict column entries of `table` in the raw config, in config order."""
    for table_cfg in config.get("tables") or ():
        if isinstance(table_cfg, dict) and table_cfg.get("name") == table:
            return [c for c in table_cfg.get("columns") or () if isinstance(c, dict)]
    return []


def parsed_when(entry: Mapping[str, Any]) -> WhenExpr | None:
    """The entry's predicate under the closed grammar, or None when it is outside it."""
    from decoy_engine.errors import ValidationError

    try:
        return parse_when(str(entry.get("when")))
    except ValidationError:
        return None


def when_native_rejection(
    column: str,
    entries: Sequence[Mapping[str, Any]],
    registry: Any,
    *,
    table: str,
    schema: pa.Schema | None,
) -> str | None:
    """The coded reason `column`'s `when:` cannot run natively, or None when it can.

    `schema` is the first chunk's (or the planner's source) schema; None means the target
    type is unknown, which declines.
    """
    from decoy_engine.execution.native._categorical_positional import positional_config_of_entry
    from decoy_engine.execution.native._faker_positional_admission import (
        positional_faker_config_of_entry,
    )
    from decoy_engine.execution.native._plan import _column_rejection

    if registry is None:
        from decoy_engine.providers_v2 import get_default_registry

        registry = get_default_registry()
    entry = next((e for e in entries if e.get("name") == column), None)
    if entry is None or not has_when(entry):
        return f"{NOT_NATIVE_CODE}:{column}"
    # The two position-keyed draws are admitted by their own config classification, not the
    # value-keyed membership + `_column_rejection` gate (which legitimately declines a
    # non-deterministic categorical). Both routes read this one verdict (C8-iii-d-2).
    positional = (
        positional_config_of_entry(dict(entry)) is not None
        or positional_faker_config_of_entry(entry) is not None
    )
    if not positional and (
        entry.get("strategy") not in ADMITTED_WHEN_STRATEGIES
        or _column_rejection(dict(entry), registry, table=table, profile=None) is not None
    ):
        return f"{NOT_NATIVE_CODE}:{column}"
    if schema is None or column not in schema.names or schema.field(column).type != pa.string():
        return f"{NOT_NATIVE_CODE}:{column}"
    ast = parsed_when(entry)
    if ast is None:
        return f"{OUTSIDE_SUBSET_CODE}:{column}"
    refs = when_column_refs(ast)
    if positional:
        # Every predicate reference must be a chunk-stable `string`: the chunked native leg
        # evaluates the predicate per chunk, where a numeric reference can widen and select
        # different rows than the whole frame. The unified route reuses this verdict, so a
        # numeric reference there falls to the full-frame oracle (= d-1), never natively.
        for read in refs:
            ref = read.column
            if ref not in schema.names or schema.field(ref).type != pa.string():
                return f"{NOT_NATIVE_CODE}:{column}"
    return None


def first_when_rejection(
    config: Mapping[str, Any],
    registry: Any,
    *,
    table: str,
    schema: pa.Schema | None,
) -> str | None:
    """The first config-order `when:` column of `table` that cannot run natively, as its
    code, or None when the table has no `when:` or every one of them can."""
    decline = first_when_decline(config, registry, table=table, schema=schema)
    return None if decline is None else decline.reason


_WHEN_DECLINE_CODES: dict[str, RouteDeclineCode] = {
    NOT_NATIVE_CODE: RouteDeclineCode.WHEN_PREDICATE_NOT_NATIVE,
    OUTSIDE_SUBSET_CODE: RouteDeclineCode.WHEN_OUTSIDE_SUBSET,
}


def first_when_decline(
    config: Mapping[str, Any],
    registry: Any,
    *,
    table: str,
    schema: pa.Schema | None,
) -> CodedDecline | None:
    """`first_when_rejection` with its structured record. The column is the `when:` entry under
    test; the code is the verdict's own leading token (a fixed vocabulary, never config text)."""
    entries = table_column_entries(config, table)
    for entry in entries:
        if has_when(entry):
            column = str(entry.get("name", "?"))
            reason = when_native_rejection(column, entries, registry, table=table, schema=schema)
            if reason is not None:
                code = _WHEN_DECLINE_CODES.get(reason.split(":", 1)[0], RouteDeclineCode.OTHER)
                return coded(reason, code, table, column)
    return None


def admitted_when_columns(
    config: Mapping[str, Any],
    registry: Any,
    *,
    table: str,
    schema: pa.Schema | None,
) -> frozenset[str]:
    """The `when:` columns of `table` that pass `when_native_rejection`."""
    entries = table_column_entries(config, table)
    return frozenset(
        str(e["name"])
        for e in entries
        if has_when(e)
        and isinstance(e.get("name"), str)
        and when_native_rejection(e["name"], entries, registry, table=table, schema=schema) is None
    )


def _stable_when_reference(field: pa.Field, facts: Any) -> bool:
    """Whether the per-chunk pandas conversion of this reference has one dtype in every chunk.

    Measured under `to_pandas_fk_safe`: string, float, timestamp, date32 and date64 keep one
    dtype whether or not a chunk holds nulls. An integer or bool widens (to float64, to
    object) only in a chunk that holds a null, so it qualifies only when the whole column is
    KNOWN to have none; an unknown count (`None`) never qualifies. time32, time64 and
    duration are left out because their eval comparisons raise or coerce differently.
    """
    typ = field.type
    if pa.types.is_integer(typ) or pa.types.is_boolean(typ):
        return facts.null_count(field.name) == 0
    return bool(
        pa.types.is_string(typ)
        or pa.types.is_large_string(typ)
        or pa.types.is_floating(typ)
        or pa.types.is_timestamp(typ)
        or pa.types.is_date32(typ)
        or pa.types.is_date64(typ)
    )


def planner_relaxed_when_columns(
    config: Mapping[str, Any],
    registry: Any,
    table: str,
    source_tables: Mapping[str, Any] | None,
    source_facts: dict[str, Any],
) -> frozenset[str]:
    """The `when:` columns the auto-chunk planner may chunk: admitted natively (rules 1, 3 and 4)
    with a `string` target and every referenced column of a type whose per-chunk conversion
    is stable (`_stable_when_reference`).

    Auto-chunking must equal the WHOLE-FRAME run, not only the chunked oracle. A reference
    whose pandas dtype changes with the nulls a chunk happens to hold (int64 to float64) can
    select differently per chunk than on the whole frame above 2**53, so those need a known
    zero null count. A static classification (no loaded source) has no schema and relaxes
    nothing.
    """
    from decoy_engine.execution._chunked_input import facts_for

    src = (source_tables or {}).get(table)
    if src is None:
        return frozenset()
    facts = facts_for(source_facts, src, table)
    schema = facts.schema
    entries = table_column_entries(config, table)
    relaxed: set[str] = set()
    for name in admitted_when_columns(config, registry, table=table, schema=schema):
        entry = next(e for e in entries if e.get("name") == name)
        ast = parsed_when(entry)
        refs = () if ast is None else when_column_refs(ast)
        if refs and all(
            r.column in schema.names and _stable_when_reference(schema.field(r.column), facts)
            for r in refs
        ):
            relaxed.add(name)
    return frozenset(relaxed)


__all__ = [
    "ADMITTED_WHEN_STRATEGIES",
    "NOT_NATIVE_CODE",
    "OUTSIDE_SUBSET_CODE",
    "admitted_when_columns",
    "first_when_decline",
    "first_when_rejection",
    "parsed_when",
    "planner_relaxed_when_columns",
    "table_column_entries",
    "when_native_rejection",
]
