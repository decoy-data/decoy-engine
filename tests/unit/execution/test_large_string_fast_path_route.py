"""LARGE-STRING-FAST: a `large_string` source takes the same masking path as `string`.

A Parquet file written with `large_string` columns (what Polars and pandas
`string[pyarrow]` produce) goes through the native auto-chunk lane. The output must equal the
`string` run, and the per-row reference kernels must not run for either file.
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.config import PipelineConfig
from decoy_engine.execution import run_pipeline
from decoy_engine.kernel import _scalar
from tests._declared_schema import declare_rest

_ROWS = 60
# Captured at import: a second `_run` in one test must wrap the real reference, not the first
# run's spy (that would credit the second run's calls to the first run's list).
_REDACT_REFERENCE = _scalar._redact_array_reference
_TRUNCATE_REFERENCE = _scalar._truncate_array_reference


def _config(path: Any) -> dict:
    return PipelineConfig.model_validate(
        declare_rest(
            {
                "version": 2,
                "global_settings": {"seed": 42},
                "sources": {"t": {"type": "file", "format": "parquet", "path": str(path)}},
                "tables": [
                    {
                        "name": "t",
                        "columns": [
                            {"name": "secret", "strategy": "redact"},
                            {
                                "name": "zip",
                                "strategy": "truncate",
                                "provider_config": {"length": 3, "keep": "head"},
                            },
                        ],
                    }
                ],
                "targets": {"t": {"type": "file", "format": "parquet", "path": "/dev/null"}},
            }
        )
    ).model_dump()


def _run(tmp_path: Any, typ: pa.DataType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DECOY_SUBSTRATE", raising=False)
    values = pa.array([f"user{i}@example.com" if i % 7 else None for i in range(_ROWS)])
    path = tmp_path / f"{typ}.parquet"
    pq.write_table(pa.table({"secret": values.cast(typ), "zip": values.cast(typ)}), path)
    table = pq.read_table(path)
    assert table.schema.field("secret").type == typ
    calls: list[str] = []

    def spy_r(*a: Any, **k: Any) -> pa.Array:
        calls.append("redact")
        return _REDACT_REFERENCE(*a, **k)

    def spy_t(*a: Any, **k: Any) -> pa.Array:
        calls.append("truncate")
        return _TRUNCATE_REFERENCE(*a, **k)

    monkeypatch.setattr(_scalar, "_redact_array_reference", spy_r)
    monkeypatch.setattr(_scalar, "_truncate_array_reference", spy_t)
    result = run_pipeline(
        _config(path),
        sources={"t": table},
        engine_version="large-string-fast",
        auto_chunk_threshold_rows=10,
        chunk_size_rows=16,
    )
    return result, calls


def test_large_string_source_matches_string_without_the_reference(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    small, small_calls = _run(tmp_path, pa.string(), monkeypatch)
    large, large_calls = _run(tmp_path, pa.large_string(), monkeypatch)
    assert small.quality_metrics["auto_chunk"]["mode"] == "chunked"
    assert large.quality_metrics["auto_chunk"]["mode"] == "chunked"
    assert small_calls == []
    assert large_calls == []
    for col in ("secret", "zip"):
        assert (
            large.outputs["t"].column(col).to_pylist() == small.outputs["t"].column(col).to_pylist()
        )
