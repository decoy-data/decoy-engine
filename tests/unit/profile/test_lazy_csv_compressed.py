"""AT-E6a and AT-E6b (RUN-STREAM): a compressed CSV gets the lazy backend.

Written before the implementation. Do not delete one, add a skip or xfail, or weaken a
comparison to make a case pass.
"""

from __future__ import annotations

import bz2
import gzip
import lzma
import os
import sys
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from decoy_engine import reasons
from decoy_engine.execution import ExecutionError
from decoy_engine.execution import _chunked_input as ci
from decoy_engine.fileaccess import FileAccess, FileRole, LocalFileAccess, Root, RootedFileAccess
from decoy_engine.fileaccess._openat2 import openat2_usable
from decoy_engine.profile import _csv_reader as csv_reader
from decoy_engine.profile import build_lazy_source
from decoy_engine.profile._csv_reader import CsvDialect, read_csv_source
from decoy_engine.profile._lazy_csv import CsvLazySource

CORPUS: dict[str, bytes] = {
    "plain": b"a,b\n1,x\n2,y\n3,\n",
    "quotes": b'a,b\n"1,5","he said ""hi"""\n2,y\n',
    "embedded_newline": b'a,b\n1,"line one\nline two"\n2,y\n',
    "header_only": b"a,b\n",
}
CODECS: dict[str, Callable[[bytes], bytes]] = {
    ".csv.gz": gzip.compress,
    ".csv.bz2": bz2.compress,
    ".csv.xz": lzma.compress,
}
CANARY = "LEAKCELL"


def _rooted(root: Path) -> tuple[FileAccess, int]:
    if not openat2_usable():
        pytest.skip("rooted file access needs Linux openat2")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    roots = [Root("main", fd, frozenset({FileRole.SOURCE}), frozenset({"read", "stat"}))]
    return RootedFileAccess(roots), fd


@pytest.fixture(params=["default", "rooted"])
def policy(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[tuple[Path, FileAccess | None]]:
    """The directory the sources live in, and the policy that reads them."""
    if request.param == "default":
        yield tmp_path, None
        return
    access, fd = _rooted(tmp_path)
    try:
        yield tmp_path, access
    finally:
        os.close(fd)


def _lazy(
    directory: Path, access: FileAccess | None, name: str, dialect: CsvDialect | None = None
) -> CsvLazySource:
    """A source declared by a descriptor, as the builder gets it. Under the rooted policy the
    declared path is relative to the root, so the reader hands pandas a suffix-less descriptor."""
    declared = name if access is not None else str(directory / name)
    descriptor: dict[str, Any] = {
        "type": "file",
        "format": "csv",
        "path": declared,
        "has_header": True,
    }
    if dialect is not None and not dialect.has_header:
        descriptor.update(has_header=False, column_names=list(dialect.column_names or ()))
    built = build_lazy_source("t", descriptor, file_access=access)
    assert isinstance(built, CsvLazySource)
    return built


def _rows(batches: Any) -> list[list[Any]]:
    out: list[list[Any]] = []
    for batch in batches:
        cols = [batch.column(i).to_pylist() for i in range(batch.num_columns)]
        out.extend([list(r) for r in zip(*cols, strict=True)])
    return out


def _resident(path: Path) -> list[list[Any]]:
    frame = read_csv_source(path, CsvDialect(), table="t", dtype=str, file_access=LocalFileAccess())
    return [[None if pd.isna(v) else v for v in row] for row in frame.to_numpy().tolist()]


@pytest.mark.parametrize("suffix", sorted(CODECS))
@pytest.mark.parametrize("case", sorted(CORPUS))
def test_a_compressed_csv_reads_lazily_and_equals_the_resident_read(
    policy: tuple[Path, FileAccess | None], suffix: str, case: str
) -> None:
    directory, access = policy
    path = directory / f"f{suffix}"
    path.write_bytes(CODECS[suffix](CORPUS[case]))
    lazy = _lazy(directory, access, path.name)
    expected = _resident(path)
    for batch_rows in (1, 2, 1000):
        opened = lazy.open_batches(batch_rows)
        got = _rows(opened.batches)
        assert got == expected
        assert opened.num_rows == len(expected)
    assert lazy.num_rows == len(expected)
    assert _rows(lazy.iter_batches(2)) == expected


@pytest.mark.parametrize("suffix", sorted(CODECS))
def test_a_compressed_file_with_no_content_fails_as_the_resident_read_does(
    policy: tuple[Path, FileAccess | None], suffix: str
) -> None:
    directory, access = policy
    path = directory / f"f{suffix}"
    path.write_bytes(CODECS[suffix](b""))
    with pytest.raises(pd.errors.EmptyDataError):
        _resident(path)
    lazy = _lazy(directory, access, path.name)
    with pytest.raises(Exception) as err:
        lazy.footer_facts()
    assert type(err.value).__name__ in {"EmptyDataError", "FileAccessReadError"}


def test_a_headerless_compressed_csv_reads_lazily(policy: tuple[Path, FileAccess | None]) -> None:
    directory, access = policy
    path = directory / "f.csv.gz"
    path.write_bytes(gzip.compress(b"1,x\n2,y\n"))
    lazy = _lazy(directory, access, path.name, CsvDialect(False, ("a", "b"), ","))
    assert _rows(lazy.iter_batches(1)) == [["1", "x"], ["2", "y"]]


def test_the_resident_reader_decompresses_a_headerless_file_and_a_direct_source_infers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "f.csv.gz"
    path.write_bytes(gzip.compress(b"1,x\n2,y\n"))
    dialect = CsvDialect(False, ("a", "b"), ",")
    frame = read_csv_source(path, dialect, table="t", dtype=str, file_access=LocalFileAccess())
    assert frame.values.tolist() == [["1", "x"], ["2", "y"]]
    direct = CsvLazySource(path, dialect=dialect, table="t")
    assert _rows(direct.iter_batches(1)) == [["1", "x"], ["2", "y"]]


def test_a_file_replaced_between_facts_and_read_is_refused(
    policy: tuple[Path, FileAccess | None],
) -> None:
    directory, access = policy
    path = directory / "f.csv.gz"
    path.write_bytes(gzip.compress(b"a,b\n1,x\n2,y\n"))
    lazy = _lazy(directory, access, path.name)
    expected = ci.source_facts(lazy)
    path.write_bytes(gzip.compress(b"a,b\n1,x\n2,y\n3,z\n"))
    with pytest.raises(ExecutionError) as exc:
        ci.open_input(lazy, table="t", chunk_size_rows=2, expected=expected, native_threads=1)
    assert exc.value.code == reasons.runtime.LAZY_SOURCE_CHANGED


def test_the_compression_is_inferred_once_from_the_declared_name(tmp_path: Path) -> None:
    gz = build_lazy_source(
        "t",
        {"type": "file", "format": "csv", "path": str(tmp_path / "a.csv.gz"), "has_header": True},
    )
    plain = build_lazy_source(
        "t", {"type": "file", "format": "csv", "path": str(tmp_path / "a.csv"), "has_header": True}
    )
    assert isinstance(gz, CsvLazySource) and gz.compression == "gzip"
    assert isinstance(plain, CsvLazySource) and plain.compression is None


# AT-E6b: a decoder failure mid-stream is the coded refusal, never the decoder's own text.
GOOD = b"a,b\n" + b"".join(f"{i},x{i}\n".encode() for i in range(50))


def _damaged() -> dict[str, tuple[str, bytes]]:
    packed_xz = bytearray(lzma.compress(GOOD))
    packed_xz[-30:-12] = b"\xff" * 18
    # bzip2 ignores bytes after a complete stream, so its damage goes inside the stream.
    packed_bz2 = bytearray(bz2.compress(GOOD))
    packed_bz2[30:45] = b"\xff" * 15
    return {
        "gzip_plaintext_tail": (
            ".csv.gz",
            gzip.compress(GOOD) + f"{CANARY},secret@x.com\n".encode(),
        ),
        "bz2_damaged": (".csv.bz2", bytes(packed_bz2)),
        "xz_damaged": (".csv.xz", bytes(packed_xz)),
    }


@pytest.mark.parametrize("case", sorted(_damaged()))
@pytest.mark.parametrize("op", ["batches", "facts", "to_table"])
def test_a_decoder_failure_is_the_coded_value_free_refusal(
    tmp_path: Path, case: str, op: str
) -> None:
    suffix, raw = _damaged()[case]
    path = tmp_path / f"f{suffix}"
    path.write_bytes(raw)
    lazy = _lazy(tmp_path, None, path.name)
    with pytest.raises(ExecutionError) as err:
        if op == "batches":
            _rows(lazy.iter_batches(7))
        elif op == "facts":
            lazy.footer_facts()
        else:
            lazy.to_table()
    exc = err.value
    assert exc.code == reasons.runtime.CHUNKED_PASSTHROUGH_VALUE_UNREPRESENTABLE
    text = f"{exc!s} {exc!r} {exc.message}"
    for marker in (CANARY, "secret@x.com", "gzipped", "Invalid data", "b'", str(tmp_path)):
        assert marker not in text, marker
    assert exc.__cause__ is None and exc.__context__ is None


def test_a_decoder_failure_in_the_rooted_policy_carries_no_cell_text(tmp_path: Path) -> None:
    access, fd = _rooted(tmp_path)
    try:
        suffix, raw = _damaged()["gzip_plaintext_tail"]
        (tmp_path / f"f{suffix}").write_bytes(raw)
        lazy = _lazy(tmp_path, access, f"f{suffix}")
        with pytest.raises(Exception) as err:
            _rows(lazy.iter_batches(7))
        assert CANARY not in f"{err.value!s} {err.value!r}"
    finally:
        os.close(fd)


# V1 (codex r1): the shared reader, not only the lazy wrapper, owns decoder-error translation.
def _assert_refusal(exc: ExecutionError) -> None:
    assert exc.code == reasons.runtime.CHUNKED_PASSTHROUGH_VALUE_UNREPRESENTABLE
    text = f"{exc!s} {exc!r} {exc.message}"
    for marker in (CANARY, "secret@x.com", "gzipped", "Invalid data", "b'"):
        assert marker not in text, marker
    assert exc.__cause__ is None and exc.__context__ is None


@pytest.mark.parametrize("chunksize", [None, 7])
def test_a_direct_headerless_read_of_a_damaged_gzip_is_the_coded_refusal(
    tmp_path: Path, chunksize: int | None
) -> None:
    suffix, raw = _damaged()["gzip_plaintext_tail"]
    path = tmp_path / f"f{suffix}"
    path.write_bytes(raw)
    dialect = CsvDialect(has_header=False, column_names=("a", "b"))
    with pytest.raises(ExecutionError) as err:
        result = read_csv_source(path, dialect, table="t", dtype=str, chunksize=chunksize)
        if chunksize is not None:
            _rows(result)
    _assert_refusal(err.value)
    assert str(tmp_path) not in f"{err.value!s} {err.value.message}"


def test_a_corrupt_zstd_file_is_the_coded_refusal(tmp_path: Path) -> None:
    pytest.importorskip("zstandard")
    path = tmp_path / "f.csv.zst"
    # A valid zstd frame magic followed by bytes that are not a frame.
    path.write_bytes(b"\x28\xb5\x2f\xfd" + b"\xff" * 64)
    lazy = _lazy(tmp_path, None, path.name)
    for op in (lambda: _rows(lazy.iter_batches(7)), lazy.footer_facts, lazy.to_table):
        with pytest.raises(ExecutionError) as err:
            op()
        _assert_refusal(err.value)


def test_a_zstd_backend_error_is_the_coded_refusal_without_the_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The backend is optional; a stand-in module proves the mapping where it is not installed."""
    stand_in = types.ModuleType("zstandard")

    class ZstdError(Exception):
        pass

    stand_in.ZstdError = ZstdError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "zstandard", stand_in)

    def _raise(*_a: Any, **_k: Any) -> Any:
        raise ZstdError("frame header b'LEAKCELL,secret@x.com'")

    monkeypatch.setattr(csv_reader.pandas_adapter, "read_csv_chunks", _raise)
    (tmp_path / "f.csv.zst").write_bytes(b"x")
    dialect = CsvDialect()
    with pytest.raises(ExecutionError) as err:
        _rows(read_csv_source(tmp_path / "f.csv.zst", dialect, table="t", dtype=str, chunksize=7))
    _assert_refusal(err.value)
