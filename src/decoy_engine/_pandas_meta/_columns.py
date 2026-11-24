"""Column facts read from the `b"pandas"` footer blob of an Arrow schema.

Four readers answer four questions about one schema: which fields the blob marks as stored
index columns, which names remain once those are dropped, which fields it marks as pandas
nullable dtypes, and (for the bounded profile) which physical fields carry which dtype hint.
Profile and execution both import them from here, so neither reaches into the other's package
for a schema fact. The blob is producer-controlled bytes: it is decoded once per call, any
malformation reads as no metadata, and no text from it is ever returned (a hint is a label this
module derives from the field's own Arrow type). Imports only `pyarrow` and the descriptor table.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, NoReturn

import pyarrow as pa

from decoy_engine._pandas_meta._descriptors import pairs_for

_PANDAS_NULLABLE_DTYPES = frozenset(
    (
        *(f"Int{w}" for w in (8, 16, 32, 64)),
        *(f"UInt{w}" for w in (8, 16, 32, 64)),
        *(f"Float{w}" for w in (32, 64)),
        "boolean",
        "string",
    )
)
_EXTENSION_FAMILIES = frozenset({"pandas.period", "pandas.interval"})


def _refuse_constant(name: str) -> NoReturn:
    raise ValueError(name)


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def decode_pandas_blob(raw: object) -> dict[str, Any] | None:
    """The blob as a dict, or `None` when it is absent, not JSON, nested too deep, has a
    duplicate key or a non-finite number, or its root is not an object. Never raises and never
    reports blob text, so a hostile footer cannot stop a profile or leak into an error."""
    if not isinstance(raw, (bytes, bytearray, str)):
        return None
    try:
        blob = json.loads(
            raw,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_refuse_constant,
        )
    except (ValueError, RecursionError):  # JSONDecodeError and UnicodeDecodeError are ValueError
        return None
    return blob if isinstance(blob, dict) else None


def _blob_of(schema: pa.Schema) -> dict[str, Any] | None:
    return decode_pandas_blob((schema.metadata or {}).get(b"pandas"))


def _stored_index(blob: dict[str, Any] | None) -> set[str]:
    """Names in `index_columns`; a range descriptor or any non-string item names no field."""
    index = (blob or {}).get("index_columns")
    return {c for c in index if isinstance(c, str)} if isinstance(index, list) else set()


def stored_index_fields(schema: pa.Schema) -> set[str]:
    """Physical fields the `pandas` metadata marks as index columns."""
    return _stored_index(_blob_of(schema))


def arrow_columns(schema: pa.Schema) -> tuple[str, ...]:
    """Column names of an Arrow schema, without a stored pandas index field."""
    index = stored_index_fields(schema)
    return tuple(n for n in schema.names if n not in index)


def pandas_nullable_columns(schema: pa.Schema) -> frozenset[str]:
    """Field names the schema's `b"pandas"` metadata marks as pandas nullable dtypes.

    A frame written from `Int8`, `boolean` and the like carries a validity mask even
    when no value is null, and pandas reads it back as the nullable extension dtype.
    Malformed metadata marks nothing.
    """
    blob = _blob_of(schema)
    if blob is None:
        return frozenset()
    try:
        return frozenset(
            str(c.get("field_name") or c["name"])
            for c in blob["columns"]
            if c.get("numpy_type") in _PANDAS_NULLABLE_DTYPES
        )
    except (KeyError, TypeError, AttributeError):
        return frozenset()


def column_entries(columns: object) -> Iterator[tuple[str, dict[str, Any]]]:
    """Each `columns` entry that names its physical field with a string `field_name`, in blob
    order. The key is never coerced and the display `name` is never used in its place."""
    if not isinstance(columns, list):
        return
    for entry in columns:
        if isinstance(entry, dict) and isinstance(entry.get("field_name"), str):
            yield entry["field_name"], entry


def _hint(arrow_type: pa.DataType, entry: dict[str, Any]) -> str | None:
    """The pandas dtype label `entry` asserts for a field of `arrow_type`, or `None`.

    A hint counts only when its `(pandas_type, numpy_type)` pair is one pyarrow writes for the
    physical type; the label is rebuilt from the Arrow type, never copied from the blob."""
    kind, numpy = entry.get("pandas_type"), entry.get("numpy_type")
    if not isinstance(kind, str) or not isinstance(numpy, str):
        return None
    if isinstance(arrow_type, pa.BaseExtensionType):
        # pandas' own period and interval types: the extension type names its dtype exactly.
        if arrow_type.extension_name not in _EXTENSION_FAMILIES:
            return None
        label = str(arrow_type.to_pandas_dtype())
        return label if (kind, numpy) == ("object", label) else None
    registered = pairs_for(arrow_type)
    if not registered:
        return None
    if (kind, numpy) in registered and numpy in _PANDAS_NULLABLE_DTYPES:
        return numpy
    token = f"{arrow_type}[pyarrow]"  # a pandas ArrowDtype column
    if numpy == token:
        return "string" if pa.types.is_string(arrow_type) else token
    return None


def bounded_column_facts(schema: pa.Schema) -> tuple[tuple[str, ...], dict[str, str]]:
    """What the bounded profile needs from the pandas blob: the physical data fields in order
    (stored index fields dropped) and the dtype hint for each field that has a valid one.

    Hints follow the current physical names: a renamed or reordered field keeps no stale hint
    and an index flag follows its name. A field with two entries has no hint (ambiguous). Reads
    the blob once. Never raises."""
    blob = _blob_of(schema)
    index = _stored_index(blob)
    names = tuple(n for n in schema.names if n not in index)
    seen: dict[str, dict[str, Any]] = {}
    ambiguous: set[str] = set()
    for key, entry in column_entries((blob or {}).get("columns")):
        if key in seen:
            ambiguous.add(key)
        seen.setdefault(key, entry)
    hints: dict[str, str] = {}
    for field in schema:
        entry = seen.get(field.name)
        usable = entry is not None and field.name not in index and field.name not in ambiguous
        label = _hint(field.type, entry) if usable and entry is not None else None
        if label is not None:
            hints[field.name] = label
    return names, hints
