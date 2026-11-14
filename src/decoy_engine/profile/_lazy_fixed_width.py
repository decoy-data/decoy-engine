"""`FixedWidthLazySource`: a fixed-width file read as bounded batches, behind `LazySource`.

Routing, the planner and the chunked input test `isinstance(src, LazySource)`, so a backend that
is a subclass is admitted with no fixed-width branch. Every read goes through
`iter_fixed_width_records`, the engine's one fixed-width parser and the one place the file is
opened; this module slices, casts and decodes nothing itself.

The schema comes from the layout, not from the data, so an empty file keeps its declared types.
The facts come from one counting pass (framing checks only, no casts, one record in memory at a
time). The file's identity (device, inode, size, mtime) is taken around the pass and around the
batch read: a file replaced or edited in between is refused with `lazy_source_changed`.

Bad data never raises where the data is held: the collectors below return the parser's value-free
message, and the raise happens in a frame whose batch and record locals are gone.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from decoy_engine.config import FixedWidthLayout
from decoy_engine.profile._fixed_width_reader import (
    RecordFailure,
    _collect_records,
    _raise_failure,
    _resolve_layout,
    count_fixed_width_records,
    iter_fixed_width_records,
)
from decoy_engine.profile._lazy_identity import LazyFileIdentity, check_batch_rows
from decoy_engine.profile._readers import FooterFacts, LazySource, OpenedLazyBatches

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

    from decoy_engine.fileaccess import FileAccess

_ARROW_TYPES: dict[str, pa.DataType] = {
    "str": pa.string(),
    "int": pa.int64(),
    "float": pa.float64(),
}

_TO_TABLE_ROWS = 65_536


def _to_batch(
    rows: list[dict[str, Any]], schema: pa.Schema, first: int
) -> tuple[pa.RecordBatch | None, str | None]:
    """The rows as one batch, or `(None, message)` when a value does not fit its Arrow type
    (an integer beyond 64 bits). A float NaN becomes null, as `pa.Table.from_pandas` does for
    the resident read. The `except` only sets a flag, so the raise (and the cleared rows) happen
    outside any exception context; the message names the column and the record range, no value."""
    arrays: list[pa.Array] = []
    bad: str | None = None
    for field_ in schema:
        try:
            values = [row[field_.name] for row in rows]
            arrays.append(pa.array(values, type=field_.type, from_pandas=True))
        except (OverflowError, pa.ArrowInvalid, pa.ArrowTypeError):
            bad = field_.name
        if bad is not None:
            break
    if bad is not None:
        count = len(rows)
        rows.clear()
        return None, (
            f"records {first} to {first + count - 1}: column {bad!r} has a value that does not "
            "fit its declared type (an integer outside the 64-bit range)"
        )
    return pa.RecordBatch.from_arrays(arrays, schema=schema), None


def _next_batch(
    parser: Iterator[dict[str, Any] | RecordFailure], schema: pa.Schema, batch_rows: int, first: int
) -> tuple[pa.RecordBatch | None, str | None]:
    """Up to `batch_rows` records as one batch: `(batch, None)`, `(None, None)` at the end of
    the file, or `(None, message)`. The parse failure and its clearing live in the one shared
    collector; this adds only the Arrow conversion."""
    rows, failure = _collect_records(parser, batch_rows)
    if failure is not None or not rows:
        return None, failure
    return _to_batch(rows, schema, first)


class OpenedFixedWidthBatches(OpenedLazyBatches):
    """The fixed-width counterpart of `OpenedLazyBatches`: same attributes, no Parquet handle.

    Built from facts the caller already holds, so no second counting pass runs. `close()` is
    idempotent and closes the batch generator, which closes the parser and the file."""

    # Does not call the Parquet constructor: there is no ParquetFile to hand it.
    def __init__(self, facts: FooterFacts, batches: Generator[pa.RecordBatch, None, None]) -> None:
        self._closed = False
        self._stream = batches
        self.facts = facts
        self.batches = batches

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._stream.close()


@dataclass(frozen=True)
class FixedWidthLazySource(LazyFileIdentity, LazySource):
    """A batch-readable handle onto one on-disk fixed-width file, declared by `layout`."""

    layout: FixedWidthLayout = field(kw_only=True, hash=False)
    table: str = field(default="source", compare=False, kw_only=True)
    # Facts and the identity they were taken under, from the last `footer_facts()` call.
    _seen: dict[str, Any] = field(default_factory=dict, compare=False, repr=False, kw_only=True)

    @classmethod
    def from_descriptor(
        cls,
        descriptor: Mapping[str, Any],
        *,
        table: str,
        file_access: FileAccess | None = None,
        field_key: str = "source.path",
    ) -> FixedWidthLazySource:
        """Build from a validated `format: fixed_width` source descriptor."""
        path = Path(descriptor["path"])
        layout = _resolve_layout(descriptor["layout"], path=str(path))
        return cls(path, access=file_access, field_key=field_key, layout=layout, table=table)

    @property
    def schema(self) -> pa.Schema:
        return pa.schema([(c.name, _ARROW_TYPES[c.type]) for c in self.layout.columns])

    def _measure(self) -> FooterFacts:
        """One framing pass: no casts, one record in memory at a time."""
        with self._handle() as handle:
            count = count_fixed_width_records(handle, self.layout)
        return FooterFacts(
            num_rows=count,
            schema=self.schema,
            # A framing pass cannot see a float "nan", which reads as null: unknown, not zero.
            null_counts=tuple(
                (c.name, None if c.type == "float" else 0) for c in self.layout.columns
            ),
            row_groups=0,
            max_row_group_rows=0,
        )

    @property
    def num_rows(self) -> int:
        return self.footer_facts().num_rows

    def column_null_counts(self) -> dict[str, int | None]:
        return dict(self.footer_facts().null_counts)

    def _projection(self, batch_rows: int, columns: Sequence[str] | None) -> pa.Schema:
        """The batch schema, checked before any generator exists so a bad call fails at the call."""
        check_batch_rows(batch_rows)
        full = self.schema
        if columns is None:
            return full
        if not columns:
            raise ValueError(f"table {self.table!r}: columns must not be empty")
        for name in columns:
            if name not in full.names:
                raise ValueError(f"table {self.table!r}: unknown column {name!r}")
        return pa.schema([full.field(name) for name in columns])

    def _stream(
        self, schema: pa.Schema, batch_rows: int, verify: Callable[[], None] | None
    ) -> Generator[pa.RecordBatch, None, None]:
        failure: str | None = None
        done = 1  # record ordinal of the next batch's first record
        with self._handle() as handle:
            parser = iter_fixed_width_records(handle, self.layout)
            try:
                while True:
                    batch, failure = _next_batch(parser, schema, batch_rows, done)
                    if batch is None:
                        break
                    done += batch.num_rows
                    yield batch
            finally:
                parser.close()
        if failure is not None:
            _raise_failure(failure)  # `batch` is None here: no record is reachable
        if verify is not None:
            verify()

    def iter_batches(
        self, batch_rows: int, *, columns: list[str] | None = None
    ) -> Generator[pa.RecordBatch, None, None]:
        """Yield the file's rows (or just `columns`) as batches of at most `batch_rows`."""
        return self._stream(self._projection(batch_rows, columns), batch_rows, None)

    def open_batches(
        self,
        batch_rows: int,
        *,
        pre_buffer: bool | None = None,
        buffer_size: int = 0,
        use_threads: bool = True,
        columns: Sequence[str] | None = None,
    ) -> OpenedLazyBatches:
        """Facts and a batch iterator for one read. The facts are the ones routing took when
        the file is unchanged since; the batch iterator checks the identity again when it is
        exhausted. The Parquet buffering arguments do not apply and are ignored."""
        del pre_buffer, buffer_size, use_threads
        schema = self._projection(batch_rows, columns)
        facts, verify = self._open_facts()

        return OpenedFixedWidthBatches(facts, self._stream(schema, batch_rows, verify))

    def to_table(self, columns: list[str] | None = None) -> pa.Table:
        """Read the file (or just `columns`) into memory. Fallback for small jobs."""
        schema = self._projection(_TO_TABLE_ROWS, columns)
        return pa.Table.from_batches(
            list(self._stream(schema, _TO_TABLE_ROWS, None)), schema=schema
        )


__all__ = ["FixedWidthLazySource", "OpenedFixedWidthBatches"]
