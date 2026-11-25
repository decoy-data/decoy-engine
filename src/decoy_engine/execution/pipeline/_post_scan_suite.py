"""Which resident tables the post-scan column suite compares, and the frames it compares them as.

The required and the deferred gate build the suite's input here, so both read the same cells:
nullable integers stay exact, as the staged batch reader keeps them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd
import pyarrow as pa

from decoy_engine.internal.pandas_compat import table_to_pandas_exact_ints


def suite_tables(
    names: Iterable[str],
    sources: Mapping[str, Any],
    table_kinds: Mapping[str, str] | None = None,
) -> list[str]:
    """The tables the column suite compares: those the run masked that also have a source. A
    generated table has no source to compare against."""
    return [
        n
        for n in names
        if n in sources and (table_kinds is None or table_kinds.get(n, "mask") == "mask")
    ]


def exact_frames(tables: Mapping[str, pa.Table]) -> dict[str, pd.DataFrame]:
    """Each table as a frame. Plain `to_pandas` widens a nullable integer column to float, so a
    nine-digit SSN would read as `123456701.0` and its detector would miss it."""
    return {n: table_to_pandas_exact_ints(t, t.column_names) for n, t in tables.items()}
