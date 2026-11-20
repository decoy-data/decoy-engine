"""Arrow-to-pandas descriptor foundation: the one table of what pyarrow writes into the
`b"pandas"` footer blob for each Arrow type.

Native admission reads `PLAIN_PAIRS` and `COLUMN_INDEX_ENTRY` to decide which source metadata it
can prove an identity conversion for. The output sanitizer (`safe_output`) reads `pairs_for` and
`column_metadata` to rebuild the blob of an output file from the output schema alone. Each keeps
its own policy; this package holds only the facts. Imports only `pyarrow`.
"""

from __future__ import annotations

from decoy_engine._pandas_meta._descriptors import (
    COLUMN_INDEX_ENTRY,
    PLAIN_PAIRS,
    column_metadata,
    pairs_for,
)

__all__ = ["COLUMN_INDEX_ENTRY", "PLAIN_PAIRS", "column_metadata", "pairs_for"]
