"""C5c-ii: pin an admitted deterministic-Faker column's degenerate output to Arrow `string`.

A deterministic Faker column over a bool/int/uint source draws from a string-output provider, so
a value-bearing output is always `string`. Its DEGENERATE output (all-null or empty) would be the
type pandas infers at the Arrow boundary instead: Arrow `null` for all-null, `double` for empty.
Decision (Cam 2026-10-09, option A): pin that degenerate output to `string` on every route, as
positional Faker and C1 categorical already do on the chunked legs, since the string-output
provider makes `string` the honest type and `double`/`null` are empty/all-null inference artifacts.

The pin set is a CONFIG + SOURCE-FAMILY predicate, independent of native admission or the chunked
stream guarantee: an otherwise pin-eligible column that declines native acceleration (no producer
guarantee) is still pinned, so both routes agree. A `when:` predicate can leave value-bearing
cells, so a `when:`-bearing column is never pinned. An FK key column the join resolution overrides
is never pinned either: the Faker pool does not own that column's output.

`pin_degenerate_to_string` is applied AFTER `pa.Table.from_pandas` on the full-frame oracle and
unified routes (a cast alone leaves pandas' `pandas_type` float64/empty, so it also rewrites the
`b"pandas"` metadata entry to unicode/object). The chunked route reaches the same result through
`_chunked_schema_rule`'s `string_columns` cast, which carries no pandas metadata by contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pyarrow as pa

from decoy_engine.execution._adapter import provider_config_to_dict
from decoy_engine.execution._operator_registry import OPERATORS
from decoy_engine.execution.native._faker_deterministic_admission import (
    DETERMINISTIC_FAKER_SOURCE_TYPES,
    is_effective_deterministic_faker,
)
from decoy_engine.execution.native._provider_class import draws_computed_string
from decoy_engine.providers_v2 import ProviderRegistry
from decoy_engine.safe_output import attach_output_metadata

# The string-output provider allowlist: only these providers draw guaranteed-string values, so
# only they are pinned (a non-string-output provider like person_dob over an int source must keep
# its own output type). Mirrors the admission classifier's allowlist.
_FAKER_PROVIDER_ALLOWLIST = OPERATORS["faker"].provider_allowlist or frozenset()

__all__ = [
    "apply_degenerate_faker_pin",
    "deterministic_faker_pin_columns",
    "deterministic_faker_pin_columns_from_plan",
    "pin_degenerate_to_string",
    "pin_frame_outputs",
]


def _has_when(col: Mapping[str, Any]) -> bool:
    when = col.get("when")
    return isinstance(when, str) and bool(when.strip())


def _fk_child_columns(config: Mapping[str, Any], table: str) -> set[str]:
    """Every column of `table` declared as an FK child key in `config["relationships"]`; the
    join resolution writes these, so the Faker pool does not own their output."""
    out: set[str] = set()
    for rel in config.get("relationships") or ():
        if not isinstance(rel, Mapping):
            continue
        for child in rel.get("children") or ():
            if isinstance(child, Mapping) and child.get("table") == table:
                out.update(str(c) for c in child.get("columns") or [])
    return out


def deterministic_faker_pin_columns(
    config: Mapping[str, Any],
    table: str,
    source_schema: pa.Schema,
    registry: ProviderRegistry | None = None,
) -> frozenset[str]:
    """The columns of `table` whose degenerate deterministic-Faker output is pinned to `string`.

    Effective-deterministic Faker over a bool/int/uint source, not `when:`-bearing and not an FK
    child key. The string-output provider / pool content is validated by the route's own pool
    check, not here. `registry` is the run's live registry: a rebound computed provider decides
    its own output type, so the pin never reads the stock binding when the run holds another."""
    table_cfg = next(
        (
            t
            for t in config.get("tables") or []
            if isinstance(t, Mapping) and t.get("name") == table
        ),
        None,
    )
    if table_cfg is None:
        return frozenset()
    fk_children = _fk_child_columns(config, table)
    source_names = set(source_schema.names)
    pinned: set[str] = set()
    for col in table_cfg.get("columns") or []:
        if not isinstance(col, Mapping):
            continue
        name = col.get("name")
        if not isinstance(name, str) or name not in source_names or name in fk_children:
            continue
        if _has_when(col):
            continue
        if col.get("strategy") == "faker" and draws_computed_string(
            col.get("provider"), col.get("provider_config"), registry
        ):
            pinned.add(name)
            continue
        if not is_effective_deterministic_faker(col):
            continue
        if col.get("provider") not in _FAKER_PROVIDER_ALLOWLIST:
            continue
        if source_schema.field(name).type in DETERMINISTIC_FAKER_SOURCE_TYPES:
            pinned.add(name)
    return frozenset(pinned)


def deterministic_faker_pin_columns_from_plan(
    plan: Any,
    table: str,
    source_schema: pa.Schema,
    *,
    relationship_graph: Any = None,
    registry: ProviderRegistry | None = None,
) -> frozenset[str]:
    """`deterministic_faker_pin_columns` from the compiled plan's column seeds, for the full-frame
    oracle routes that work from the plan rather than the raw config. The `allow_collisions` alias
    is already folded into `seed.deterministic` by the seed envelope; a `when:`-bearing seed and an
    FK child key (from `relationship_graph`) are excluded, matching the config-based predicate."""
    table_seed = next((ts for (name, ts) in plan.seed_envelope.per_table if name == table), None)
    if table_seed is None:
        return frozenset()
    fk_children: set[str] = set()
    for edge in getattr(relationship_graph, "edges", ()) or ():
        if edge.child_table == table:
            fk_children.update(edge.child_columns)
    source_names = set(source_schema.names)
    pinned: set[str] = set()
    for name, seed in table_seed.per_column:
        if name not in source_names or name in fk_children:
            continue
        if seed.strategy != "faker" or seed.when:
            continue
        if draws_computed_string(
            seed.provider, provider_config_to_dict(seed.provider_config), registry
        ):
            pinned.add(name)
            continue
        if not seed.deterministic:
            continue
        if seed.provider not in _FAKER_PROVIDER_ALLOWLIST:
            continue
        if source_schema.field(name).type in DETERMINISTIC_FAKER_SOURCE_TYPES:
            pinned.add(name)
    return frozenset(pinned)


def pin_frame_outputs(
    outputs: Mapping[str, pa.Table],
    plan: Any,
    sources: Mapping[str, pa.Table],
    *,
    relationship_graph: Any = None,
    registry: ProviderRegistry | None = None,
) -> dict[str, pa.Table]:
    """Apply the degenerate pin to each from_pandas output using the plan and the pre-mask source
    schema. A table absent from `sources` (a generate echo) is returned unchanged."""
    return {
        t: pin_degenerate_to_string(
            out,
            deterministic_faker_pin_columns_from_plan(
                plan, t, sources[t].schema, relationship_graph=relationship_graph, registry=registry
            )
            if t in sources
            else frozenset(),
        )
        for t, out in outputs.items()
    }


def apply_degenerate_faker_pin(
    outputs: Mapping[str, pa.Table],
    plan: Any,
    sources: Mapping[str, pa.Table],
    *,
    relationship_graph: Any = None,
    registry: ProviderRegistry | None = None,
    enabled: bool,
) -> dict[str, pa.Table]:
    """Full-frame route hook for C5c-ii option A. When `enabled`, pin each admitted
    deterministic-Faker column's empty/all-null output to Arrow `string`, matching the native
    routes; otherwise return `outputs` unchanged. Full-frame callers only: the chunked legs pin
    through `_chunked_schema_rule`'s `string_columns`, and the legacy kill-switch lane keeps the
    oracle's own inferred type (a pandas round trip there would re-introduce schema metadata the
    chunked contract strips)."""
    if not enabled:
        return dict(outputs)
    return pin_frame_outputs(
        outputs, plan, sources, relationship_graph=relationship_graph, registry=registry
    )


def pin_degenerate_to_string(table: pa.Table, columns: frozenset[str]) -> pa.Table:
    """Retype each column in `columns` whose output is all-null or empty to Arrow `string`,
    rewriting its `b"pandas"` metadata to the string shape. Value-bearing columns (already
    `string`) and unrelated columns are untouched; an empty `columns` set is a no-op."""
    if not columns:
        return table
    degenerate: list[int] = []
    for i, field in enumerate(table.schema):
        if field.name not in columns or field.type == pa.string():
            continue
        if table.num_rows == 0 or table.column(i).null_count == table.num_rows:
            degenerate.append(i)
    if not degenerate:
        return table
    for i in degenerate:
        field = table.schema.field(i)
        column = table.column(i).cast(pa.string())
        table = table.set_column(
            i, pa.field(field.name, pa.string(), nullable=field.nullable), column
        )
    # The sanitizer rebuilds the blob from the output schema: a column now `string` takes the
    # string pair, so no hand patch of the source blob is left.
    # Cast columns were rebuilt bare above; every other column is the source field.
    schema = attach_output_metadata(
        table.schema.remove_metadata(), table.schema.metadata, carried=table.schema.names
    )
    return table.cast(schema)
