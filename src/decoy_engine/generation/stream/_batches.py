"""One table's `RecordBatch` stream, assembled from its persistent per-column streams.

A column normally arrives as a Python list: the stream draws values, `restore_declared` parses
text cells of a numeric column, `cast_output_values` applies a declared `output_type`, and
`pa.array(values, type=...)` builds the Arrow column. A stream that can hand over an Arrow array
directly (`supports_array`, today the pooled Faker stream and a null mask over it) skips the
list when nothing needs the Python values:

- a declared `output_type` casts Python values;
- a key collector (`reference` parent) reads Python values;
- a later column reads it as a sibling list (`stream.sibling_input`: a `windowed_date`
  anchor, a `condition_on` parent);
- the array's type must equal the schema's, otherwise the list path parses and casts it, so a
  numeric column fed by text cells is converted exactly as before.

The null mask, width check and values are the same on both paths, so the bytes do not depend on
which one a column takes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.compute as pc

from decoy_engine import reasons
from decoy_engine.generation import stream as gen_stream
from decoy_engine.generation._budget_ledger import GenerationBudgetExceeded
from decoy_engine.generation._column_streams import draw_batch, supports_array
from decoy_engine.generation._numeric_typing import restore_declared
from decoy_engine.generation.kinds import cast_output_values, output_types

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

    from decoy_engine.generation._column_streams import ColumnStream, KeyPool


def check_width(arr: pa.Array, bound: int, column: str) -> None:
    if not (pa.types.is_string(arr.type) or pa.types.is_large_string(arr.type)):
        return
    longest = pc.max(pc.binary_length(arr)).as_py()  # type: ignore[attr-defined, unused-ignore]
    if longest is not None and longest > bound:
        raise GenerationBudgetExceeded(
            code=reasons.runtime.VALUE_EXCEEDS_DECLARED_BOUND,
            message=f"column {column!r} produced a value wider than its declared {bound}-byte bound.",
        )


def sibling_read_names(cols: Sequence[dict[str, Any]]) -> frozenset[str]:
    """The columns a later column of the batch reads as a sibling list (`sibling_input`)."""
    return frozenset(n for c in cols if (n := gen_stream.sibling_input(c)) is not None)


def array_columns(
    cols: Sequence[dict[str, Any]],
    streams: Sequence[ColumnStream],
    declared: Mapping[str, Any],
    collectors: Mapping[str, KeyPool],
) -> list[bool]:
    """Per column, whether its batch may stay an Arrow array (no consumer needs Python values)."""
    read = sibling_read_names(cols)
    return [
        supports_array(stream)
        and c["name"] not in declared
        and c["name"] not in collectors
        and c["name"] not in read
        for c, stream in zip(cols, streams, strict=True)
    ]


def table_batches(
    table: dict[str, Any],
    schema: pa.Schema,
    sizes: Iterable[int],
    streams: Sequence[ColumnStream],
    widths: Mapping[str, int],
    collectors: Mapping[str, KeyPool],
    generated: Sequence[pa.DataType | None],
) -> Iterator[pa.RecordBatch]:
    offset = 0
    cols = table["generate_columns"]
    names = [c["name"] for c in cols]
    declared = output_types(cols)
    array_ok = array_columns(cols, streams, declared, collectors)
    for size in sizes:
        arrays = []
        # Columns emitted so far in THIS batch, post-null-mask (legacy `generated`): date anchors.
        emitted: dict[str, list[Any]] = {}
        for col, name, stream, field_, gen_type, may_skip_list in zip(
            cols, names, streams, schema, generated, array_ok, strict=True
        ):
            arr: pa.Array | None = None
            values: list[Any] | None = None
            if may_skip_list:
                drawn = stream.next_array(offset, size)  # type: ignore[attr-defined, unused-ignore]
                if drawn.type == field_.type:
                    arr = drawn
                else:
                    values = drawn.to_pylist()
            if arr is None:
                if values is None:
                    values = draw_batch(stream, offset, size, emitted)
                # Parse text cells to the GENERATED type; the output_type cast comes after, so
                # the provider's text never reaches `int()` just because the column is emitted
                # as int.
                values = restore_declared(col, values, gen_type)
                emitted[name] = values  # siblings read the generator's values, not the typed ones
                if name in declared:
                    values = cast_output_values(
                        values, declared[name], table=str(table["name"]), column=name
                    )
                arr = pa.array(values, type=field_.type)
            if name in widths:
                check_width(arr, widths[name], name)
            if values is not None and name in collectors:
                collectors[name].add(values)
            arrays.append(arr)
        yield pa.RecordBatch.from_arrays(arrays, schema=schema)
        offset += size
