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

from decoy_engine._execution_error import lazy_source_changed
from decoy_engine.config._fixed_width import FixedWidthLayout
from decoy_engine.profile._fixed_width_reader import (
    RecordFailure,
    _raise_failure,
    _resolve_layout,
    iter_fixed_width_records,
)
from decoy_engine.profile._readers import FooterFacts, LazySource, OpenedLazyBatches

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

    from decoy_engine.fileaccess import FileAccess

_ARROW_TYPES: dict[str, pa.DataType] = {
    "str": pa.string(),
    "int": pa.int64(),
    "float": pa.float64(),
}

_Identity = tuple[int, int, int, int]


def _next_batch(
    parser: Iterator[dict[str, Any] | RecordFailure], schema: pa.Schema, batch_rows: int
) -> tuple[pa.RecordBatch | None, str | None]:
    """Up to `batch_rows` records as one batch: `(batch, None)`, `(None, None)` at the end of
    the file, or `(None, message)` on a bad record. A failure clears the partial rows first, so
    the caller raises from a frame that holds none."""
    rows: list[dict[str, Any]] = []
    for _ in range(batch_rows):
        item = next(parser, None)
        if item is None:
            break
        if isinstance(item, RecordFailure):
            rows.clear()
            return None, item.message
        rows.append(item)
    if not rows:
        return None, None
    return pa.RecordBatch.from_pylist(rows, schema=schema), None


class OpenedFixedWidthBatches(OpenedLazyBatches):
    """The fixed-width counterpart of `OpenedLazyBatches`: same attributes, no Parquet handle.

    Built from facts the caller already holds, so no second counting pass runs. `close()` is
    idempotent and closes the batch generator, which closes the parser and the file."""

    # Does not call the Parquet constructor: there is no ParquetFile to hand it.
    def __init__(self, facts: FooterFacts, batches: Generator[pa.RecordBatch, None, None]) -> None:
        self._closed = False
        self.facts = facts
        self.batches = batches

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.batches.close()  # type: ignore[attr-defined]


@dataclass(frozen=True)
class FixedWidthLazySource(LazySource):
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

    def _identity(self) -> _Identity:
        with self._handle() as handle:
            st = handle.stat()
        return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)

    @property
    def schema(self) -> pa.Schema:
        return pa.schema([(c.name, _ARROW_TYPES[c.type]) for c in self.layout.columns])

    def footer_facts(self) -> FooterFacts:
        """Schema, exact row count and zero null counts. The snapshot is reused while a single
        stat says the file is the one it describes; otherwise one counting pass refreshes it."""
        if "facts" in self._seen and self._identity() == self._seen["identity"]:
            facts: FooterFacts = self._seen["facts"]
            return facts
        return self._count_pass()

    def _count_records(self) -> tuple[int | None, str | None]:
        count = 0
        with self._handle() as handle:
            parser = iter_fixed_width_records(handle, self.layout, cast_values=False)
            try:
                for item in parser:
                    if isinstance(item, RecordFailure):
                        return None, item.message
                    count += 1
            finally:
                parser.close()
        return count, None

    def _count_pass(self) -> FooterFacts:
        before = self._identity()
        count, failure = self._count_records()
        if failure is not None:
            _raise_failure(failure)  # this frame holds no record
        if self._identity() != before:
            raise lazy_source_changed(self.table, "the file changed while its facts were read")
        schema = self.schema
        facts = FooterFacts(
            num_rows=count or 0,
            schema=schema,
            null_counts=tuple((name, 0) for name in schema.names),
            row_groups=0,
            max_row_group_rows=0,
        )
        self._seen["facts"] = facts
        self._seen["identity"] = before
        return facts

    @property
    def num_rows(self) -> int:
        return self.footer_facts().num_rows

    def column_null_counts(self) -> dict[str, int | None]:
        return dict(self.footer_facts().null_counts)

    def _read(
        self, batch_rows: int, columns: Sequence[str] | None, verify: Callable[[], None] | None
    ) -> Generator[pa.RecordBatch, None, None]:
        if batch_rows < 1:
            raise ValueError(f"batch_rows must be >= 1, got {batch_rows}")
        full = self.schema
        schema = full if columns is None else pa.schema([full.field(name) for name in columns])
        failure: str | None = None
        with self._handle() as handle:
            parser = iter_fixed_width_records(handle, self.layout)
            try:
                while True:
                    batch, failure = _next_batch(parser, schema, batch_rows)
                    if batch is None:
                        break
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
        return self._read(batch_rows, columns, None)

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
        if "facts" in self._seen and self._identity() != self._seen["identity"]:
            raise lazy_source_changed(self.table, "the file changed since its facts were read")
        facts: FooterFacts = self._seen["facts"] if "facts" in self._seen else self.footer_facts()
        identity: _Identity = self._seen["identity"]

        def verify() -> None:
            if self._identity() != identity:
                raise lazy_source_changed(self.table, "the file changed while it was read")

        return OpenedFixedWidthBatches(facts, self._read(batch_rows, columns, verify))

    def to_table(self, columns: list[str] | None = None) -> pa.Table:
        """Read the file (or just `columns`) into memory. Fallback for small jobs."""
        names = self.schema.names if columns is None else columns
        schema = pa.schema([self.schema.field(name) for name in names])
        return pa.Table.from_batches(list(self._read(65_536, columns, None)), schema=schema)


__all__ = ["FixedWidthLazySource", "OpenedFixedWidthBatches"]
