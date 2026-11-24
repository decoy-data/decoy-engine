"""Column facts read from the `b"pandas"` footer blob of an Arrow schema.

Three readers answer three questions about one schema: which fields the blob marks as stored
index columns, which names remain once those are dropped, and which fields it marks as pandas
nullable dtypes. Profile and execution both import them from here, so neither reaches into the
other's package for a schema fact. Imports only `pyarrow`.
"""

from __future__ import annotations

import json

import pyarrow as pa

_PANDAS_NULLABLE_DTYPES = frozenset(
    (
        *(f"Int{w}" for w in (8, 16, 32, 64)),
        *(f"UInt{w}" for w in (8, 16, 32, 64)),
        *(f"Float{w}" for w in (32, 64)),
        "boolean",
        "string",
    )
)


def stored_index_fields(schema: pa.Schema) -> set[str]:
    """Physical fields the `pandas` metadata marks as index columns."""
    meta = schema.pandas_metadata or {}
    return {c for c in meta.get("index_columns", []) if isinstance(c, str)}


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
    raw = (schema.metadata or {}).get(b"pandas")
    if raw is None:
        return frozenset()
    try:
        columns = json.loads(raw)["columns"]
        return frozenset(
            str(c.get("field_name") or c["name"])
            for c in columns
            if c.get("numpy_type") in _PANDAS_NULLABLE_DTYPES
        )
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return frozenset()
