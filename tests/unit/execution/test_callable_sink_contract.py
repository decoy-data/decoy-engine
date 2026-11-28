"""One whole-table contract decides what a transactional writer is, on every route.

A callable object that carries only a `.write` attribute is a plain callable: sequential
execution and resident delivery both hand it every table through the call, not through `.write`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.execution import run_pipeline
from decoy_engine.execution._transactional_sink import has_whole_table_contract
from tests._declared_schema import declare_rest
from tests.acceptance._f06_support import column, config, text_table, write_csv


class _WriteOnlyCallable:
    """Callable with a `.write` attribute and no commit or abort."""

    def __init__(self) -> None:
        self.received: list[str] = []

    def __call__(self, table: str, data: pa.Table) -> None:
        self.received.append(table)

    def write(self, table: str, data: pa.Table) -> None:  # pragma: no cover - must not be used
        raise AssertionError("a write-only callable is a plain callable")


def test_write_only_callable_is_not_a_whole_table_sink() -> None:
    assert not has_whole_table_contract(_WriteOnlyCallable())


@pytest.mark.parametrize("mode", ["full_frame", "sequential"])
def test_a_write_only_callable_receives_every_table_on_both_routes(
    tmp_path: Path, mode: str
) -> None:
    src = write_csv(tmp_path / "g.csv", ["id", "v"], [["1", "a"]])
    raw = config([column("id"), column("v")], source_path=src)
    sink = _WriteOnlyCallable()
    result: Any = run_pipeline(
        declare_rest(raw),
        {"people": text_table(id=["1", "2"], v=["a", "b"])},
        engine_version="probe",
        sink=sink,
        execution_mode=mode,  # type: ignore[arg-type]
    )
    assert result is not None
    assert sink.received == ["people"]
