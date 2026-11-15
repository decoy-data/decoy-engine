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

import pandas as pd
import pytest
from pandas.io.common import infer_compression

from decoy_engine.profile._csv_reader import csv_is_compressed

SUFFIXES = [
    ".csv",
    ".CSV",
    ".csv.gz",
    ".CSV.GZ",
    ".csv.bz2",
    ".csv.zip",
    ".csv.xz",
    ".csv.zst",
    ".csv.tar",
    ".csv.tar.gz",
    ".csv.tar.bz2",
    ".csv.tar.xz",
    ".csv.tgz",
    ".csv.zz",
    ".txt",
]


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_the_decision_agrees_with_pandas_inference(suffix: str) -> None:
    path = f"data{suffix}"
    assert csv_is_compressed(path) is (infer_compression(path, "infer") is not None)


def test_tgz_is_not_compressed_because_pandas_does_not_infer_it() -> None:
    assert csv_is_compressed("a.csv.tgz") is False
    assert csv_is_compressed("a.csv.tar.gz") is True


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
def test_the_decision_matches_what_pandas_really_reads(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"data{suffix}"
    path.write_bytes(WRITERS[suffix](RAW))
    frame = pd.read_csv(path, dtype=str)
    assert list(frame.columns) == ["a", "b"]
    assert csv_is_compressed(str(path)) is (suffix != ".csv")
