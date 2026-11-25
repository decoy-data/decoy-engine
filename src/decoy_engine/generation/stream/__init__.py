"""Streamed batch assembly for the unified generation core (`generation/_streamed.py`).

`_batches.py` turns each column stream's draws into one Arrow `RecordBatch` per batch, on an
Arrow path that never builds a Python list when nothing downstream needs the values.
`_siblings.py` holds the one rule for which earlier column a column reads; callers use
`stream.sibling_input` so the rule has a single definition.
"""

from decoy_engine.generation.stream._siblings import sibling_input

__all__ = ["sibling_input"]
