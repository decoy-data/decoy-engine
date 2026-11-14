"""`inherit`: a child column that copies a column of the parent row its foreign key points at.

`claims.member_state` with `via: member_id` and `column: state` holds, on every row, the `state`
of the `members` row that the row's `member_id` names. A null foreign key gives a null; a parent
row whose value is null gives a null; nothing is drawn.

Pattern: a lookup join, the SQL `LEFT JOIN parent ON child.fk = parent.key` on a unique parent key
(ISO/IEC 9075-2, `<joined table>`), and the parent-to-child propagation of SDV's HMA1 model
(N. Patki, R. Wedge, K. Veeramachaneni, "The Synthetic Data Vault", IEEE DSAA 2016): a child
row carries values of the one parent row its foreign key names, so a denormalized attribute
agrees with its parent on every row. The row is found by `_parent_lookup.lookup_parent_values`,
the one parent lookup, so a null key, a key with no parent row and a repeated parent key follow
its rules and codes; the key's uniqueness is validated by the same rule
(`config.parent_key_problem`).

Both inputs come resolved from `config.iter_generate_input_refs`: `via` as an edge to the
child's own foreign key column, and `column` as an edge into the parent table that carries the
parent key (`source_key`). This module never follows `via` to its parent table, so a column of
any other table with the parent column's name is never read, and the table read at run is the
one the checks judged.

The copy keeps the parent column's Arrow type (`inherit_types`): an all-null copy or a decimal
parent would infer another type from its values.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pyarrow as pa

from decoy_engine.config import GenerateInputRef, iter_generate_input_refs
from decoy_engine.generation.relational._parent_lookup import lookup_parent_values

__all__ = ["inherit_types", "inherit_values"]


def _edges(
    table_name: str, columns: Sequence[Mapping[str, Any]], col: Mapping[str, Any]
) -> tuple[GenerateInputRef | None, GenerateInputRef | None]:
    """The resolved `via` and `column` inputs of the `inherit` column `col`, None when absent."""
    edges = iter_generate_input_refs({"name": table_name, "generate_columns": columns}, col)
    via = next((e for e in edges if e.option == "via"), None)
    source = next((e for e in edges if e.option == "column" and e.source_key), None)
    return via, source


def _source(
    table_name: str,
    columns: Sequence[Mapping[str, Any]],
    col: Mapping[str, Any],
    pools: Mapping[str, pa.Table],
) -> tuple[GenerateInputRef, GenerateInputRef] | None:
    """Both inputs of `col` when its parent table is finished and holds the key and the column."""
    via, source = _edges(table_name, columns, col)
    if via is None or source is None or source.source_table not in pools:
        return None
    names = pools[source.source_table].column_names
    if source.source_key not in names or source.source_column not in names:
        return None
    return via, source


def inherit_values(
    col: Mapping[str, Any],
    table_name: str,
    generated: Mapping[str, list[Any]],
    pools: Mapping[str, pa.Table],
    columns: Sequence[Mapping[str, Any]],
) -> list[Any]:
    """The parent value of each row of the `inherit` column `col` of table `table_name`.

    `generated` holds the table's columns drawn so far, `pools` the finished tables and
    `columns` the table's column configs. Raises the parent lookup's `GenerationError` for a key
    with no parent row or a repeated parent key.
    """
    found = _source(table_name, columns, col, pools)
    # Validation and the plan check refuse each of these; a caller that skipped both gets a
    # typed refusal that names the column only.
    if found is None or found[0].source_column not in generated:
        raise ValueError(
            f"generate column {table_name!r}.{col.get('name')!r}: "
            "the inherited column's inputs do not resolve to a generated parent table"
        )
    via, source = found
    return lookup_parent_values(
        dict(pools),
        parent_table=source.source_table,
        key_column=source.source_key,
        value_column=source.source_column,
        foreign_keys=list(generated[via.source_column]),
        child_table=table_name,
        child_column=via.source_column,
    ).values


def inherit_types(
    table_name: str, columns: Sequence[Mapping[str, Any]], pools: Mapping[str, pa.Table]
) -> dict[str, pa.DataType]:
    """The Arrow type of each `inherit` column of the table: its parent column's type."""
    types: dict[str, pa.DataType] = {}
    for col in columns:
        if col.get("type") != "inherit":
            continue
        found = _source(table_name, columns, col, pools)
        if found is not None:
            parent = pools[found[1].source_table]
            types[str(col.get("name"))] = parent.schema.field(found[1].source_column).type
    return types
