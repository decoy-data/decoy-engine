"""Streamed batch assembly for the unified generation core (`generation/_streamed.py`).

`_batches.py` turns each column stream's draws into one Arrow `RecordBatch` per batch, on an
Arrow path that never builds a Python list when nothing downstream needs the values.
"""

__all__: list[str] = []
