"""PREFLIGHT-ARROW-PROFILE S1b: a memory-shaped Arrow error keeps its memory class at every site.

Arrow's value-conversion failure under a cap quotes a cell in its text. The bounded profile must
classify it (fixed text, same type, no chain) whichever policy is active and whichever call
raised it, including the pandas conversion that the temporal recovery otherwise swallows as a
`ValueError`.
"""

from __future__ import annotations

import os
import traceback
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import fileaccess, reason_adapter
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.fileaccess import FileRole, Root, RootedFileAccess
from decoy_engine.fileaccess._openat2 import openat2_usable
from tests.unit.profile.arrow_profile.support import bounded_profile

MARKER = "123456789"


def _leaky() -> pa.ArrowInvalid:
    return pa.ArrowInvalid(f"Unknown error: Wrapping {MARKER} failed")


def _formatted(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc)) + repr(exc) + str(exc)


class _FailingColumn:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def to_pandas(self, **_kw: Any) -> Any:
        raise self._exc


class _FailingTable:
    """A table whose pandas conversion raises, whole or per selected column."""

    def __init__(self, inner: pa.Table, whole: BaseException, column: BaseException | None):
        self._inner, self._whole, self._column = inner, whole, column

    def __len__(self) -> int:
        return len(self._inner)

    @property
    def schema(self) -> pa.Schema:
        return self._inner.schema

    @property
    def num_rows(self) -> int:
        return self._inner.num_rows

    def to_pandas(self, **_kw: Any) -> Any:
        raise self._whole

    def select(self, names: list[str]) -> Any:
        if self._column is None:
            return self._inner.select(names)
        return _FailingTable(self._inner.select(names), self._column, None)

    @property
    def column_names(self) -> list[str]:
        return self._inner.column_names

    def column(self, index: int) -> Any:
        if self._column is not None:
            return _FailingColumn(self._column)
        return self._inner.column(index)


class _Reader:
    def __init__(self, table: pa.Table, failing: _FailingTable) -> None:
        self._table, self._failing = table, failing

    def row_count(self) -> Any:
        from decoy_engine.profile._readers import RowCount

        return RowCount(self._table.num_rows, True)

    def schema(self) -> pa.Schema:
        return self._table.schema

    def sample_table(self, sample_rows: int) -> Any:
        return self._failing

    def sample_frame(self, sample_rows: int) -> Any:  # pragma: no cover - never read
        raise AssertionError("the bounded profile reads the sample as a table")


def _reader(whole: BaseException, column: BaseException | None, *, temporal: bool = True) -> Any:
    table = (
        pa.table({"t": pa.array([1], pa.time64("ns")), "a": [1]})
        if temporal
        else pa.table({"a": [1]})
    )
    return _Reader(table, _FailingTable(table, whole, column))


def _assert_classified(exc: BaseException, original: BaseException) -> None:
    assert isinstance(exc, pa.ArrowInvalid)
    assert exc is not original
    assert fileaccess.is_memory_failure(exc)
    assert exc.__cause__ is None and exc.__context__ is None
    assert MARKER not in _formatted(exc)


def test_a_memory_failure_from_the_whole_table_conversion_is_classified() -> None:
    leaky = _leaky()
    with pytest.raises(pa.ArrowInvalid) as caught:
        bounded_profile(_reader(leaky, None, temporal=False), "local")
    _assert_classified(caught.value, leaky)


def test_a_memory_failure_from_a_column_conversion_is_classified() -> None:
    leaky = _leaky()
    with pytest.raises(pa.ArrowInvalid) as caught:
        bounded_profile(_reader(ValueError("not memory"), leaky), "local")
    _assert_classified(caught.value, leaky)


def test_an_ordinary_conversion_failure_is_still_a_label() -> None:
    # #799: a whole-sample failure no single column reproduces is the coded, value-free error.
    with pytest.raises(ExecutionError) as caught:
        bounded_profile(_reader(ValueError(MARKER), None, temporal=False), "local")
    assert caught.value.code == "source_column_unrepresentable"
    assert MARKER not in _formatted(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.fixture
def rooted(tmp_path: Path) -> Iterator[tuple[RootedFileAccess, Path]]:
    if not openat2_usable():
        pytest.skip("rooted file access needs Linux openat2")
    root = tmp_path / "root"
    root.mkdir()
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    roots = [
        Root(
            "main", fd, frozenset({FileRole.SOURCE}), frozenset({"read", "stat"}), prefix=str(root)
        )
    ]
    try:
        yield RootedFileAccess(roots), root
    finally:
        os.close(fd)


def test_a_memory_failure_is_classified_under_a_strict_policy(
    rooted: tuple[RootedFileAccess, Path],
) -> None:
    policy, _ = rooted
    leaky = _leaky()
    with fileaccess.scope(policy), pytest.raises(pa.ArrowInvalid) as caught:
        bounded_profile(_reader(leaky, None, temporal=False), "local")
    _assert_classified(caught.value, leaky)


@pytest.mark.parametrize("strict", [False, True])
def test_capacity_hides_a_cell_quoted_by_a_memory_failure(
    strict: bool,
    rooted: tuple[RootedFileAccess, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under a strict policy the memory class is kept (the caller classifies it) but the
    exception raised is a fresh one with fixed text; under the CLI policy it is wrapped."""
    from decoy_engine.execution._errors import ExecutionError
    from decoy_engine.execution.capacity import estimate_job_capacity
    from decoy_engine.profile import _readers

    leaky = _leaky()

    def leak(self: Any, sample_rows: int) -> Any:
        raise leaky

    monkeypatch.setattr(_readers.ParquetFileSource, "sample_table", leak)
    policy, root = rooted
    base = root if strict else tmp_path
    pq.write_table(pa.table({"a": [1, 2]}), base / "t.parquet")
    path = base / "t.parquet"
    config = {
        "version": 2,
        "global_settings": {"job_name": "j", "seed": 7},
        "sources": {"t": {"type": "file", "path": str(path), "format": "parquet"}},
        "targets": {
            "t": {
                "type": "file",
                "path": str(base / "o.parquet"),
                "format": "parquet",
            }
        },
        "tables": [{"name": "t", "columns": [{"name": "a", "strategy": "passthrough"}]}],
    }
    if strict:
        with fileaccess.scope(policy), pytest.raises(pa.ArrowInvalid) as caught:
            estimate_job_capacity(config, base, file_access=policy)
        _assert_classified(caught.value, leaky)
    else:
        with pytest.raises(ExecutionError) as wrapped:
            estimate_job_capacity(config, base)
        assert MARKER not in _formatted(wrapped.value)


def test_the_duplicate_name_refusal_passes_through_by_the_reason_registry() -> None:
    """The duplicate-field-name refusal keeps its type, and the reason adapter registers it."""
    from decoy_engine._field_names import DuplicateFieldNamesError
    from decoy_engine.profile._source import _passes_through

    assert DuplicateFieldNamesError in reason_adapter.loaded_families()
    assert _passes_through(DuplicateFieldNamesError("m"))
