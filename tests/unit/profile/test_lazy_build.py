"""AT-E4 (RUN-STREAM): `build_lazy_source` is the one public lazy builder.

Written before the implementation. Do not delete one, add a skip or xfail, or weaken a
comparison to make a case pass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from decoy_engine.profile import (
    FixedWidthLazySource,
    LazySource,
    build_declared_source,
    build_lazy_source,
)
from decoy_engine.profile._lazy_csv import CsvLazySource
from decoy_engine.profile._readers import (
    CsvFileSource,
    FixedWidthFileSource,
    ParquetFileSource,
)
from tests.sentry.source_config import test_declaration_gate as gate

LAYOUT: dict[str, Any] = {"columns": [{"name": "s", "start": 0, "width": 4}]}


def _descriptor(fmt: str, path: str, **extra: Any) -> dict[str, Any]:
    descriptor: dict[str, Any] = {"type": "file", "format": fmt, "path": path, **extra}
    if fmt == "fixed_width":
        descriptor.setdefault("layout", LAYOUT)
    return descriptor


def test_parquet_gives_the_plain_lazy_source(tmp_path: Path) -> None:
    src = build_lazy_source("t", _descriptor("parquet", str(tmp_path / "a.parquet")))
    assert type(src) is LazySource
    assert src.field_key == "sources.t.path"


def test_csv_gives_the_csv_backend_with_the_resolved_dialect(tmp_path: Path) -> None:
    src = build_lazy_source("t", _descriptor("csv", str(tmp_path / "a.csv"), delimiter=";"))
    assert isinstance(src, CsvLazySource)
    assert src.dialect.delimiter == ";"
    assert src.table == "t"
    assert src.field_key == "sources.t.path"


def test_fixed_width_gives_the_fixed_width_backend(tmp_path: Path) -> None:
    src = build_lazy_source("t", _descriptor("fixed_width", str(tmp_path / "a.txt")))
    assert isinstance(src, FixedWidthLazySource)
    assert src.table == "t"
    assert src.field_key == "sources.t.path"


@pytest.mark.parametrize(
    "name",
    ["a.csv.gz", "a.csv.bz2", "a.csv.zip", "a.csv.xz", "a.csv.zst", "a.CSV.GZ", "a.tar.gz"],
)
def test_a_compressed_csv_has_no_lazy_backend(tmp_path: Path, name: str) -> None:
    assert build_lazy_source("t", _descriptor("csv", str(tmp_path / name))) is None


@pytest.mark.parametrize(
    "descriptor",
    [
        {"type": "s3", "format": "csv", "bucket": "b", "key": "k.csv"},
        {"type": "gcs", "format": "parquet", "bucket": "b", "key": "k.parquet"},
        {"type": "sftp", "format": "csv", "path": "x.csv"},
        {"type": "file", "format": "xlsx", "path": "x.xlsx"},
        {"type": "file", "format": ["csv"], "path": "x.csv"},
        {"type": "file", "path": "x.csv"},
    ],
)
def test_cloud_and_unknown_return_none(descriptor: dict[str, Any]) -> None:
    assert build_lazy_source("t", descriptor) is None


@pytest.mark.parametrize("fmt", ["csv", "parquet", "fixed_width"])
def test_building_opens_nothing(tmp_path: Path, fmt: str) -> None:
    """The files do not exist: a build that opened one, or read a row, would raise."""
    assert build_lazy_source("t", _descriptor(fmt, str(tmp_path / "missing.dat"))) is not None


def test_a_column_names_file_is_read_under_its_own_position(tmp_path: Path) -> None:
    names = tmp_path / "names.txt"
    names.write_text("a,b\n", encoding="utf-8")
    src = build_lazy_source(
        "t",
        _descriptor(
            "csv", str(tmp_path / "missing.csv"), has_header=False, column_names_file=str(names)
        ),
    )
    assert isinstance(src, CsvLazySource)
    assert src.dialect.column_names == ("a", "b")


def test_the_declaration_gate_sentry_lists_the_builder_and_the_names_file_read() -> None:
    assert "build_lazy_source" in gate.READER_NAMES
    assert "resolve_csv_dialect" in gate.READER_NAMES
    assert ("profile/_lazy_build.py", "build_lazy_source", "resolve_csv_dialect") in gate.READERS or (
        "profile/_lazy_build.py",
        "_lazy_csv",
        "resolve_csv_dialect",
    ) in gate.READERS or any(
        rel == "profile/_lazy_csv.py" and reader == "resolve_csv_dialect"
        for rel, _, reader in gate.READERS
    )


@pytest.mark.parametrize(
    ("descriptor", "tail"),
    [
        ({"type": "file", "format": "csv", "path": 7}, "sources.t.path"),
        ({"type": "file", "format": "parquet", "path": None}, "sources.t.path"),
        ({"type": "file", "format": "fixed_width", "path": ["x"]}, "sources.t.path"),
        ({"type": "file", "format": "fixed_width", "path": "x.txt"}, "sources.t.layout"),
    ],
)
def test_a_refusal_names_the_config_position(descriptor: dict[str, Any], tail: str) -> None:
    with pytest.raises(ValueError, match=tail.replace(".", r"\.")) as err:
        build_lazy_source("t", descriptor)
    assert "x.txt" not in str(err.value)


def test_the_resident_builder_keeps_its_classes_and_refusals(tmp_path: Path) -> None:
    def build(fmt: str) -> object:
        return build_declared_source("t", _descriptor(fmt, str(tmp_path / "a.dat")))

    assert type(build("csv")) is CsvFileSource
    assert type(build("parquet")) is ParquetFileSource
    assert type(build("fixed_width")) is FixedWidthFileSource
    with pytest.raises(NotImplementedError, match=r"sources\.t\.format"):
        build_declared_source("t", {"type": "file", "format": "xlsx", "path": "x"})
    with pytest.raises(ValueError, match=r"sources\.t\.path"):
        build_declared_source("t", {"type": "file", "format": "csv", "path": 3})


def test_both_builders_read_the_one_format_table() -> None:
    from decoy_engine.profile import _lazy_build

    table = _lazy_build.FILE_FORMATS
    assert set(table) == {"csv", "parquet", "fixed_width"}
    for entry in table.values():
        assert callable(entry.resident)
        assert entry.lazy is None or callable(entry.lazy)
