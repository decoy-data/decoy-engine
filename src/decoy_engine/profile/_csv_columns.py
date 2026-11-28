"""Column projection and ordering for `read_csv_source(columns=...)`.

Split out of `_csv_reader`: pandas ignores the order of `usecols`, so the requested order is
restored here for every frame and chunk. No message here quotes a column name.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from decoy_engine.profile._csv_reader import CsvDialect


def _ordered(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    """`frame` holding exactly `columns`, in that order. pandas ignores the order of `usecols`,
    so the requested order is restored here, once, for every frame and chunk."""
    if len(frame.columns) != len(columns) or set(frame.columns) != set(columns):
        raise ValueError("read_csv_source: columns names a column the file does not have")
    return frame[list(columns)]


def _shaped(result: Any, columns: Sequence[str]) -> Any:
    """`_ordered` over one frame, or lazily over each chunk of an iterator."""
    if isinstance(result, pd.DataFrame):
        return _ordered(result, columns)
    return _shaped_chunks(result, columns)


def _shaped_chunks(
    chunks: Iterator[pd.DataFrame], columns: Sequence[str]
) -> Iterator[pd.DataFrame]:
    # A generator expression would reach `chunks` only through reference counting when it is
    # closed; the finally closes the file handle at the call that closes this.
    try:
        for chunk in chunks:
            yield _ordered(chunk, columns)
    finally:
        close = getattr(chunks, "close", None)
        if close is not None:
            close()


def _projection(
    dialect: CsvDialect, columns: Sequence[str]
) -> tuple[dict[str, Any], list[str] | None]:
    """The pandas `usecols` for `columns`, and the names the kept columns carry in file order
    (headerless only; with a header pandas names them itself).

    With a header a callable keeps a missing name from raising a pandas error that quotes it;
    `_ordered` then refuses the mismatch with a fixed message."""
    if not columns:
        raise ValueError("read_csv_source: columns names no column")
    if len(set(columns)) != len(columns):
        raise ValueError("read_csv_source: columns names a column more than once")
    if dialect.has_header:
        wanted = frozenset(columns)
        return {"usecols": lambda name: name in wanted}, None
    declared = list(dialect.column_names or ())
    if any(c not in declared for c in columns):
        raise ValueError("read_csv_source: columns names a column the file does not have")
    positions = sorted(declared.index(c) for c in columns)
    return {"usecols": positions}, [declared[p] for p in positions]
