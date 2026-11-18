"""AT-EW1-5: file bytes are identical on every OS (Windows plan E22, EW1).

`os.open` on Windows defaults to text mode: 0x0A becomes CRLF and 0x1A ends a read. A payload
with each of those bytes is written through the stage's `create_file`, read back through
`open_file` and through the arrow, serial and polars adapters, and compared byte for byte
against the file on disk.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import polars as pl
import pyarrow as pa

from decoy_engine.fileaccess import _local
from decoy_engine.fileaccess._types import OutputTxn
from decoy_engine.fileaccess.adapters import arrow, serial
from decoy_engine.fileaccess.adapters import polars as polars_adapter

PAYLOAD = b"a\nb\rc\x1ad\r\n"


def _read_all(fd: int) -> bytes:
    chunks = []
    try:
        while chunk := os.read(fd, 65536):
            chunks.append(chunk)
    finally:
        os.close(fd)
    return b"".join(chunks)


def _stage(tmp_path: Path) -> _local._LocalStageDir:
    return _local.handed_stage_dir(tmp_path, "engine.test")  # type: ignore[return-value]


def test_raw_descriptor_round_trip_is_byte_exact(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    fd = stage.create_file("raw.bin")
    assert os.write(fd, PAYLOAD) == len(PAYLOAD)
    os.close(fd)
    assert (tmp_path / "raw.bin").read_bytes() == PAYLOAD
    assert _read_all(stage.open_file("raw.bin")) == PAYLOAD


def test_serial_writers_are_byte_exact(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    serial.write_bytes(stage, "w.bin", PAYLOAD)
    serial.write_durable(stage.create_file("d.bin"), PAYLOAD)
    for name in ("w.bin", "d.bin"):
        assert (tmp_path / name).read_bytes() == PAYLOAD
        assert _read_all(stage.open_file(name)) == PAYLOAD


def test_arrow_and_polars_tables_round_trip_the_bytes(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    table = pa.table({"b": pa.array([PAYLOAD], type=pa.binary())})
    arrow.write_table(table, stage, "a.parquet")
    polars_adapter.write_parquet(
        pl.DataFrame({"b": pl.Series([PAYLOAD], dtype=pl.Binary)}),
        cast("OutputTxn", stage),  # a stage has everything the writer reads: create_file, display
        "p.parquet",
    )
    for name in ("a.parquet", "p.parquet"):
        with arrow.staged_parquet(stage.open_file(name)) as parquet:
            assert parquet.read().column("b").to_pylist() == [PAYLOAD]
    fd = stage.create_file("t.arrow")
    with os.fdopen(fd, "wb") as fh, pa.ipc.new_file(fh, table.schema) as writer:
        writer.write_table(table)
    assert arrow.ipc_read_file(stage, "t.arrow").column("b").to_pylist() == [PAYLOAD]
