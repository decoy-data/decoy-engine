"""What the post-scan column suite compares: which tables, and their source/output frames.

Split from the gate so `_post_scan` stays under its size cap. A column pandas cannot hold fails
with a coded error that carries no value.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from decoy_engine._execution_error import post_scan_not_inspectable
from decoy_engine.execution._pipeline_sources import materialize_source
from decoy_engine.internal.pandas_compat import arrow_to_frame_pair, exact_int_types_mapper

if TYPE_CHECKING:
    import pandas as pd


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


def suite_frames(
    sources: Mapping[str, Any], outputs: Mapping[str, pa.Table], tables: Iterable[str]
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """The source and output frames of the suite tables. A column pandas cannot hold fails the
    gate with `post_scan_column_not_inspectable`: the check never passes a column it did not read."""
    src: dict[str, pd.DataFrame] = {}
    out: dict[str, pd.DataFrame] = {}
    for name in tables:
        # Physical field names, never the pandas index metadata: a stored index (named or not) is a
        # column the batch gate reads by name, so the frame checks must read it the same way. The batch
        # reader's integer mapper keeps a null-bearing integer column exact beyond 2**53.
        src[name], out[name] = arrow_to_frame_pair(
            materialize_source(sources[name]),
            outputs[name],
            on_unrepresentable=post_scan_not_inspectable(name),
            ignore_metadata=True,
            types_mapper=exact_int_types_mapper,
        )
    return src, out
