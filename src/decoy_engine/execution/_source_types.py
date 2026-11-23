"""The one output assembler: a masked pandas frame becomes an output table here and nowhere else.

Columns no strategy changed are written from the source Arrow column as stored, so pandas never
changes their type on any route (UF-DOMAIN S1, plan 2026-11-22-uf-domain.md).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

import pandas as pd
import pyarrow as pa

from decoy_engine.safe_output import attach_output_metadata


def _with_source_types(
    table: pa.Table, schema: pa.Schema | None, names: Collection[str]
) -> pa.Table:
    """Give each named column its source Arrow type back where pandas lost it.

    A date strategy hands pandas ``datetime.date`` cells, which Arrow reads as ``date32`` (so a
    ``date64`` source changes type) and, for an all-null chunk, as ``null`` (so chunk schemas
    differ). Only those two losses are repaired; any other type difference is left as it is.
    """
    if schema is None:
        return table
    for name in names:
        if name not in table.column_names or name not in schema.names:
            continue
        want = schema.field(name).type
        have = table.schema.field(name).type
        if have != want and (
            pa.types.is_null(have) or (pa.types.is_date64(want) and have == pa.date32())
        ):
            position = table.schema.get_field_index(name)
            table = table.set_column(position, name, table.column(position).cast(want))
    return table


def _index_keeps_source_order(index: pd.Index, stored: bool) -> bool:
    """True when `index` is still the source's row order: the stored index the source carries, or
    a unit-step range (pandas metadata may start it above zero). A reordered or filtered frame
    carries an integer index that is neither."""
    return stored or (isinstance(index, pd.RangeIndex) and index.step == 1)


def table_from_pandas_keeping_source_types(
    frame: pd.DataFrame,
    source: pa.Table | None,
    untouched: Collection[str],
    keep_types: Collection[str] = (),
    arrow_columns: Mapping[str, pa.Array | pa.ChunkedArray] | None = None,
) -> pa.Table:
    """The one place a masked pandas frame becomes an output table.

    The output has the source's row count and column order. Each `untouched` column (the columns
    no strategy changed, `_chunked_carry.untouched_columns`) is the source column as stored, so
    pandas never gets to change its type (decimal precision, nullable ints, `large_string`,
    nested types). Each `arrow_columns` entry is that array as given. Every other column comes
    from the frame through `from_pandas`, as a masked column always did; `keep_types` names the
    date columns whose source type is restored after that conversion.

    The frame must still be the source's rows: same count and an index still in source order (no row
    dropped or reordered since the source was read), and its remaining columns in source order. A
    mismatch raises before any output exists; the message carries counts and names only.
    With `source=None` there is nothing to keep, and the whole frame converts."""
    if source is None:
        return pa.Table.from_pandas(frame, preserve_index=False)
    given = dict(arrow_columns or {})
    n_rows = source.num_rows
    # A source that stores its pandas index as a column reads back with that column as the frame
    # index, never as a frame column, and the output has never carried it.
    stored_index = {
        c
        for c in (source.schema.pandas_metadata or {}).get("index_columns", [])
        if isinstance(c, str)
    }
    if frame.shape[0] != n_rows or not _index_keeps_source_order(frame.index, bool(stored_index)):
        raise RuntimeError(
            f"output assembly: frame has {frame.shape[0]} rows or a reordered index, "
            f"source has {n_rows} rows"
        )
    names = [c for c in source.schema.names if c not in stored_index]
    source_names = set(names)
    carried = {c for c in names if c in untouched or c in given}
    # Source columns keep the source's order. A column the frame holds and the source does not
    # (a created target) sits where the frame put it.
    in_frame = [c for c in names if c in frame.columns]
    if [c for c in frame.columns if c in source_names] != in_frame or any(
        c not in frame.columns and c not in carried for c in names
    ):
        raise RuntimeError(
            f"output assembly: frame columns do not match the source columns in order "
            f"({frame.shape[1]} frame columns, {len(names)} source columns)"
        )
    order = list(frame.columns)
    previous: str | None = None
    for name in names:
        if name in frame.columns:
            previous = name
            continue
        order.insert(0 if previous is None else order.index(previous) + 1, name)
        previous = name
    from_frame = [c for c in frame.columns if c not in carried]
    built = pa.Table.from_pandas(frame[from_frame], preserve_index=False)
    built = _with_source_types(built, source.schema, keep_types)
    fields: list[pa.Field] = []
    columns: list[pa.Array | pa.ChunkedArray] = []
    for name in order:
        if name in given:
            columns.append(given[name])
            fields.append(pa.field(name, given[name].type))
        elif name in carried:
            columns.append(source.column(name))
            fields.append(source.schema.field(name))
        else:
            columns.append(built.column(name))
            fields.append(built.schema.field(name))
    # Row count comes from the source: from_pandas of a zero-column frame has zero rows.
    schema = attach_output_metadata(pa.schema(fields), built.schema.metadata, carried=carried)
    return pa.Table.from_arrays(columns, schema=schema)


__all__ = ["table_from_pandas_keeping_source_types"]
