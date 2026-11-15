"""The one table of local file formats, and the lazy source builder that reads it.

A format has a resident builder (a `ProfileSource` for profiling) and, where one exists, a lazy
builder (a `LazySource` for bounded batch reads). `_readers._build_file_source` and
`build_lazy_source` both look the format up in `FILE_FORMATS`, so a format added later lands in
one place and the lazy column is an explicit choice (`None` means no lazy backend).

Building opens no data row. The facts pass runs when routing asks for facts. The one read at
build time is the CSV dialect resolver's `column_names_file`, listed in the declaration-gate
sentry.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from decoy_engine import fileaccess
from decoy_engine._lexeme import LEXEME_KEY
from decoy_engine.profile._csv_reader import resolve_csv_dialect
from decoy_engine.profile._lazy_csv import CsvLazySource
from decoy_engine.profile._lazy_fixed_width import FixedWidthLazySource
from decoy_engine.profile._readers import (
    CsvFileSource,
    FixedWidthFileSource,
    LazySource,
    ParquetFileSource,
    ProfileSource,
    _at,
)

if TYPE_CHECKING:
    from decoy_engine.fileaccess import FileAccess

# Suffixes pandas decompresses on its own (`compression="infer"`); a lazy CSV read has no
# decompressing path, so these stay on the resident read.
_COMPRESSED_SUFFIXES = (".gz", ".bz2", ".zip", ".xz", ".zst", ".tar", ".tgz")


@dataclass(frozen=True)
class FileFormat:
    """One local file format: its resident builder and its lazy builder or `None`."""

    resident: Callable[[dict[str, Any], str, str], ProfileSource]
    lazy: Callable[[str, dict[str, Any], FileAccess | None], LazySource | None] | None


def descriptor_path(descriptor: dict[str, Any], field_key: str) -> str:
    path = descriptor.get("path")
    if not isinstance(path, str):
        raise ValueError(
            "profile_source: file source missing string `path`, got "
            f"{fileaccess.shown(repr(path), _at(field_key, 'path'))}"
        )
    return path


def _layout(descriptor: dict[str, Any], field_key: str) -> dict[str, Any]:
    layout = descriptor.get("layout")
    if not isinstance(layout, dict):
        raise ValueError(
            "profile_source: fixed_width file source missing `layout`, got "
            f"{fileaccess.shown(repr(layout), _at(field_key, 'layout'))}"
        )
    return layout


def _resident_csv(descriptor: dict[str, Any], field_key: str, table: str) -> ProfileSource:
    dialect = resolve_csv_dialect(descriptor, table=table)
    return CsvFileSource(
        Path(descriptor_path(descriptor, field_key)),
        has_header=dialect.has_header,
        column_names=None if dialect.column_names is None else list(dialect.column_names),
        delimiter=dialect.delimiter,
        lexeme_columns=tuple(descriptor.get(LEXEME_KEY) or ()),
        field_key=field_key,
        table=table,
    )


def _resident_parquet(descriptor: dict[str, Any], field_key: str, table: str) -> ProfileSource:
    return ParquetFileSource(Path(descriptor_path(descriptor, field_key)), field_key=field_key)


def _resident_fixed_width(descriptor: dict[str, Any], field_key: str, table: str) -> ProfileSource:
    path = descriptor_path(descriptor, field_key)
    return FixedWidthFileSource(Path(path), _layout(descriptor, field_key), field_key=field_key)


def _lazy_csv(
    table: str, descriptor: dict[str, Any], file_access: FileAccess | None
) -> LazySource | None:
    path = descriptor_path(descriptor, f"sources.{table}.path")
    if path.lower().endswith(_COMPRESSED_SUFFIXES):
        return None
    return CsvLazySource.from_descriptor(
        descriptor, table=table, file_access=file_access, field_key=f"sources.{table}.path"
    )


def _lazy_parquet(
    table: str, descriptor: dict[str, Any], file_access: FileAccess | None
) -> LazySource | None:
    field_key = f"sources.{table}.path"
    return LazySource(Path(descriptor_path(descriptor, field_key)), file_access, field_key)


def _lazy_fixed_width(
    table: str, descriptor: dict[str, Any], file_access: FileAccess | None
) -> LazySource | None:
    field_key = f"sources.{table}.path"
    descriptor_path(descriptor, field_key)
    _layout(descriptor, field_key)
    return FixedWidthLazySource.from_descriptor(
        descriptor, table=table, file_access=file_access, field_key=field_key
    )


FILE_FORMATS: dict[str, FileFormat] = {
    "csv": FileFormat(_resident_csv, _lazy_csv),
    "parquet": FileFormat(_resident_parquet, _lazy_parquet),
    "fixed_width": FileFormat(_resident_fixed_width, _lazy_fixed_width),
}


def file_format(fmt: object) -> FileFormat | None:
    """The table entry for a descriptor's `format`, or `None` for an unknown or unhashable one."""
    return FILE_FORMATS.get(fmt) if isinstance(fmt, str) else None


@fileaccess.entry_point
def build_lazy_source(
    table: str, descriptor: dict[str, Any], *, file_access: FileAccess | None = None
) -> LazySource | None:
    """The lazy backend for config table `table`, or `None` when its source has none.

    Read under the config position `sources.<table>.path`, as `build_declared_source` is. `None`
    covers a cloud descriptor, an unknown type or format, and a compressed CSV; the caller then
    keeps its resident read. Opens no data row."""
    if descriptor.get("type") != "file":
        return None
    entry = file_format(descriptor.get("format"))
    if entry is None or entry.lazy is None:
        return None
    return entry.lazy(table, descriptor, file_access)
