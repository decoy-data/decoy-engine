"""Streamed batch assembly for the unified generation core (`generation/_streamed.py`).

`_batches.py` turns each column stream's draws into one Arrow `RecordBatch` per batch, on an
Arrow path that never builds a Python list when nothing downstream needs the values.
`_siblings.py` holds the one rule for which earlier column a column reads; callers use
`stream.sibling_input` so the rule has a single definition. `check_width` and `table_batches` are
exported for the streamed run, loaded lazily.
"""

from typing import TYPE_CHECKING, Any

from decoy_engine.generation.stream._siblings import sibling_input

if TYPE_CHECKING:
    from decoy_engine.generation.stream._batches import check_width, table_batches

_LAZY = ("check_width", "table_batches")


def __getattr__(name: str) -> Any:
    """Load `_batches` on first use: it imports `_column_streams`, which imports this package for
    `sibling_input`, so an eager import here would make the three modules a cycle."""
    if name in _LAZY:
        from decoy_engine.generation.stream import _batches

        value = getattr(_batches, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["check_width", "sibling_input", "table_batches"]
