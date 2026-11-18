"""Canary sources and a metadata-aware finder for output Parquet files (OUTPUT-METADATA-LEAK).

Field metadata lives only inside the base64 `ARROW:schema` footer value, so a raw-bytes search
cannot see it. `canaries_in` looks in four places: the raw bytes, every footer key and value, the
decoded `ARROW:schema` schema (schema and every field, recursive), and the parsed pandas blob.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA = "DCY-CANARY-SCHEMA"
ATTRS = "DCY-CANARY-ATTRS"
FIELD = "DCY-CANARY-FIELD"
COLIDX = "DCY-CANARY-COLIDX"
NESTED = "DCY-CANARY-NESTED"
EXT = "DCY-CANARY-EXT"
RIDX = "DCY-CANARY-RIDX"
SKEY = "DCY-CANARY-SKEY"
FKEY = "DCY-CANARY-FKEY"
CREATOR = "DCY-CANARY-CREATOR"
PDVER = "DCY-CANARY-PDVER"

ALL_CANARIES = (
    SCHEMA,
    ATTRS,
    FIELD,
    COLIDX,
    NESTED,
    EXT,
    RIDX,
    SKEY,
    FKEY,
    CREATOR,
    PDVER,
)

_ARROW_SCHEMA_KEY = b"ARROW:schema"


def _walk_type(typ: pa.DataType) -> Iterator[pa.Field]:
    """Every field nested under `typ`, at any depth."""
    for i in range(typ.num_fields):
        child = typ.field(i)
        yield child
        yield from _walk_type(child.type)
    value_type = getattr(typ, "value_type", None)
    if isinstance(typ, pa.DictionaryType) and value_type is not None:
        yield from _walk_type(value_type)


def _schema_texts(schema: pa.Schema) -> list[bytes]:
    """Every metadata key and value of the schema and of every field, plus the field names."""
    texts: list[bytes] = []

    def meta(m: dict[bytes, bytes] | None) -> None:
        for k, v in (m or {}).items():
            texts.extend((k, v))

    meta(schema.metadata)
    fields = list(schema)
    for f in list(fields):
        fields.extend(_walk_type(f.type))
    for f in fields:
        meta(f.metadata)
        texts.append(f.name.encode())
    return texts


def _footer_texts(path: Path) -> list[bytes]:
    texts: list[bytes] = []
    footer = pq.ParquetFile(path).metadata.metadata or {}
    for k, v in footer.items():
        texts.extend((k, v))
        if k == _ARROW_SCHEMA_KEY:
            decoded = base64.b64decode(v)
            texts.append(decoded)
            texts.extend(_schema_texts(pa.ipc.read_schema(pa.py_buffer(decoded))))
        if k == b"pandas":
            texts.append(json.dumps(json.loads(v)).encode())
    return texts


def canaries_in(path: Path | str) -> set[str]:
    """The canaries present in the file, in any of the four places."""
    p = Path(path)
    blobs = [p.read_bytes(), *_footer_texts(p)]
    return {c for c in ALL_CANARIES if any(c.encode() in b for b in blobs)}


def assert_engine_wrote(
    path: Path | str, run_start: float, *, not_written_by_test: set[Path]
) -> None:
    """The file is a committed output the engine wrote during the run, not one the test made."""
    p = Path(path)
    assert p.is_file(), "the route published no file at the reported path"
    assert p.resolve() not in {x.resolve() for x in not_written_by_test}, "path is a test source"
    assert os.stat(p).st_mtime >= run_start, "file predates the run"


def _pandas_blob(df: pd.DataFrame, *, preserve_index: bool | None) -> bytes:
    table = pa.Table.from_pandas(df, preserve_index=preserve_index)
    blob = json.loads((table.schema.metadata or {})[b"pandas"])
    blob["creator"] = {"library": CREATOR, "version": CREATOR}
    blob["pandas_version"] = PDVER
    return json.dumps(blob).encode()


def canary_table(
    columns: dict[str, pa.Array],
    *,
    field_meta_on: tuple[str, ...] | None = None,
    extension_column: str | None = None,
) -> pa.Table:
    """A table whose schema carries one canary per carrier.

    `field_meta_on` defaults to every column; `extension_column` marks a storage column with the
    unregistered `ARROW:extension:*` keys.
    """
    frame = pd.DataFrame({k: v.to_pylist() for k, v in columns.items()})
    frame.attrs["note"] = ATTRS
    frame.columns.name = COLIDX
    frame.index.name = RIDX
    base = pa.Table.from_pandas(frame, preserve_index=None)
    meta = dict(base.schema.metadata or {})
    meta[b"pandas"] = _pandas_blob(frame, preserve_index=None)
    meta[b"table_comment"] = SCHEMA.encode()
    meta[SKEY.encode()] = b"x"
    fields = []
    for name, arr in columns.items():
        f = pa.field(name, arr.type)
        if field_meta_on is None or name in field_meta_on:
            f = f.with_metadata({b"comment": FIELD.encode(), FKEY.encode(): b"x"})
        if name == extension_column:
            f = f.with_metadata(
                {
                    **(f.metadata or {}),
                    b"ARROW:extension:name": EXT.encode(),
                    b"ARROW:extension:metadata": EXT.encode(),
                }
            )
        fields.append(f)
    schema = pa.schema(fields, metadata=meta)
    return pa.Table.from_arrays([columns[n] for n in columns], schema=schema)


def write_canary_parquet(path: Path, table: pa.Table) -> str:
    pq.write_table(table, path)
    return str(path)
