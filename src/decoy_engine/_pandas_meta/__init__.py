"""Arrow-to-pandas descriptor foundation: the one table of what pyarrow writes into the
`b"pandas"` footer blob for each Arrow type.

Native admission reads `PLAIN_PAIRS` and `COLUMN_INDEX_ENTRY` to decide which source metadata it
can prove an identity conversion for. Profile and execution read the stored-index, nullable and
bounded-profile column facts from `_columns`, which also decodes the blob for the sanitizer. The
output sanitizer (`safe_output`) reads `pairs_for` and `column_metadata` to rebuild the blob of an
output file from the output schema alone. Each keeps its own policy; this package holds only the
facts. Imports `pyarrow` and `_canonical`.
"""

from __future__ import annotations

from decoy_engine._pandas_meta._columns import (
    arrow_columns,
    bounded_column_facts,
    column_entries,
    decode_pandas_blob,
    pandas_nullable_columns,
    stored_index_fields,
)
from decoy_engine._pandas_meta._descriptors import (
    COLUMN_INDEX_ENTRY,
    PLAIN_PAIRS,
    column_metadata,
    pairs_for,
)

__all__ = [
    "COLUMN_INDEX_ENTRY",
    "PLAIN_PAIRS",
    "arrow_columns",
    "bounded_column_facts",
    "column_entries",
    "column_metadata",
    "decode_pandas_blob",
    "pairs_for",
    "pandas_nullable_columns",
    "stored_index_fields",
]
