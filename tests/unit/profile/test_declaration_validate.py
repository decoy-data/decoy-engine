"""G5c: the validate form of the declaration request never opens an `s3` or `gcs` source.

`decoy validate` is an offline gate and must not need cloud credentials. The request names the
sources it left unchecked so the caller can warn; the run form still checks them before a row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import reasons
from decoy_engine.errors import PipelineValidationError
from decoy_engine.profile import DeclarationRequest, prepare_declared_sources
from decoy_engine.profile import _cloud_readers as cloud


def _config(sources: dict[str, Any], *tables: str) -> dict[str, Any]:
    return {
        "version": 2,
        "global_settings": {"seed": 1},
        "sources": sources,
        "tables": [
            {"name": t, "columns": [{"name": "email", "strategy": "passthrough"}]} for t in tables
        ],
        "relationships": [],
    }


S3 = {"type": "s3", "format": "csv", "bucket": "b", "key": "k.csv"}
GCS = {"type": "gcs", "format": "parquet", "bucket": "b", "key": "k.parquet"}


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every cloud client entry fails the test and records the call."""
    calls: list[str] = []

    def boom(label: str) -> Any:
        def fail(*_a: Any, **_k: Any) -> Any:
            calls.append(label)
            raise AssertionError(f"network call: {label}")

        return fail

    monkeypatch.setattr(cloud, "_s3_for", boom("s3"))
    monkeypatch.setattr(cloud, "_gcs_blob", boom("gcs"))
    return calls


def test_validate_request_skips_remote_sources_and_names_them(no_network: list[str]) -> None:
    config = _config({"a": S3, "b": GCS}, "a", "b")
    request = DeclarationRequest.for_validate(config)
    assert request.remote_sources == ("a", "b")
    prepare_declared_sources(request)  # nothing local to read, nothing to refuse
    assert no_network == []


def test_validate_request_still_checks_local_files(tmp_path: Path, no_network: list[str]) -> None:
    path = tmp_path / "t.csv"
    path.write_text("other\nx\n", encoding="utf-8")
    local = {"type": "file", "format": "csv", "path": str(path), "has_header": True}
    request = DeclarationRequest.for_validate(_config({"t": local, "r": S3}, "t", "r"))
    assert request.remote_sources == ("r",)
    with pytest.raises(PipelineValidationError) as exc:
        prepare_declared_sources(request)
    assert exc.value.code == reasons.config.SOURCE_FILE_UNDECLARED_COLUMN
    assert no_network == []


def test_run_request_still_refuses_a_remote_source_before_any_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[str] = []
    monkeypatch.setattr(
        cloud.S3CsvSource, "schema", lambda self: pa.schema([("other", pa.string())])
    )
    for name in ("sample_frame", "to_frame"):
        monkeypatch.setattr(
            cloud.S3CsvSource, name, lambda *a, _n=name, **k: rows.append(_n) or None
        )
    with pytest.raises(PipelineValidationError) as exc:
        prepare_declared_sources(DeclarationRequest.for_descriptors(_config({"a": S3}, "a")))
    assert exc.value.code == reasons.config.SOURCE_FILE_UNDECLARED_COLUMN
    assert rows == []
