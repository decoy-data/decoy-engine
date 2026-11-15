"""One engine-owned answer to "does pandas decompress this CSV path", and it is pandas'.

The lazy builder declines a compressed CSV; the decision must not drift from what
`pd.read_csv(compression="infer")` actually does, so it is derived from pandas' own inference.
Written before the implementation; do not weaken a case to make it pass.
"""

from __future__ import annotations

import bz2
import gzip
import io
import lzma
import tarfile
import zipfile
from pathlib import Path

import pytest

from decoy_engine.fileaccess import LocalFileAccess
from decoy_engine.profile._csv_reader import CsvDialect, csv_is_compressed, read_csv_source

# Expected answers for the locked pandas, written out so a pandas change shows up here.
EXPECTED: dict[str, bool] = {
    ".csv": False,
    ".CSV": False,
    ".txt": False,
    ".csv.gz": True,
    ".CSV.GZ": True,
    ".csv.bz2": True,
    ".csv.zip": True,
    ".csv.xz": True,
    ".csv.zst": True,
    ".csv.tar": True,
    ".csv.tar.gz": True,
    ".csv.tar.bz2": True,
    ".csv.tar.xz": True,
    ".csv.tgz": False,
}


@pytest.mark.parametrize(("suffix", "expected"), sorted(EXPECTED.items()))
def test_the_decision_for_each_suffix(suffix: str, expected: bool) -> None:
    assert csv_is_compressed(f"data{suffix}") is expected


def _tar(raw: bytes, mode: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=mode) as tar:
        info = tarfile.TarInfo("inner.csv")
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))
    return buf.getvalue()


def _zip(raw: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("inner.csv", raw)
    return buf.getvalue()


RAW = b"a,b\n1,x\n2,y\n"
WRITERS = {
    ".csv": lambda raw: raw,
    ".csv.gz": gzip.compress,
    ".CSV.GZ": gzip.compress,
    ".csv.bz2": bz2.compress,
    ".csv.xz": lzma.compress,
    ".csv.zip": _zip,
    ".csv.tar": lambda raw: _tar(raw, "w"),
    ".csv.tar.gz": lambda raw: _tar(raw, "w:gz"),
}


@pytest.mark.parametrize("suffix", sorted(WRITERS))
def test_the_decision_matches_what_read_csv_source_reads(tmp_path: Path, suffix: str) -> None:
    """Under the local policy the reader hands pandas the real path, so pandas' inference
    applies and the decision says whether the file is read through a decompressor."""
    path = tmp_path / f"data{suffix}"
    path.write_bytes(WRITERS[suffix](RAW))
    frame = read_csv_source(path, CsvDialect(), table="t", dtype=str, file_access=LocalFileAccess())
    assert list(frame.columns) == ["a", "b"]
    assert list(frame["a"]) == ["1", "2"]
    assert csv_is_compressed(str(path)) is EXPECTED[suffix]
