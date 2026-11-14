"""AT-18 to AT-18e (SAMPLE SE3b): `FixedWidthLazySource` is a `LazySource` over the one parser.

Written before the implementation. Do not delete one, add a skip or xfail, or weaken a
comparison to make a case pass.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import read_fixed_width, reasons
from decoy_engine.errors import FixedWidthParseError
from decoy_engine.execution import ExecutionError
from decoy_engine.profile import _lazy_fixed_width
from decoy_engine.profile._lazy_fixed_width import FixedWidthLazySource
from decoy_engine.profile._readers import LazySource
from tests.unit.test_v2_fixed_width_source import _SENTINEL, _assert_sentinel_unreachable

LAYOUT: dict[str, Any] = {
    "columns": [
        {"name": "s", "start": 0, "width": 9},
        {"name": "n", "start": 9, "width": 4, "type": "int", "align": "right"},
        {"name": "f", "start": 13, "width": 6, "type": "float", "align": "right"},
    ]
}


def line(i: int) -> bytes:
    return f"{f'row{i}':<9}{i:>4}{i + 0.5:>6}".encode()


def write(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    return path


def records(count: int, sep: bytes = b"\n") -> bytes:
    return sep.join(line(i) for i in range(count)) + sep


def lazy(path: Path, table: str = "t") -> FixedWidthLazySource:
    descriptor = {"type": "file", "format": "fixed_width", "path": str(path), "layout": LAYOUT}
    return FixedWidthLazySource.from_descriptor(descriptor, table=table)


class Spy:
    """Counts the items `iter_fixed_width_records` hands out, and how often it is opened."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.yielded = 0
        self.opened = 0
        real = _lazy_fixed_width.iter_fixed_width_records

        def spy(*args: Any, **kwargs: Any) -> Iterator[Any]:
            self.opened += 1
            for item in real(*args, **kwargs):
                self.yielded += 1
                yield item

        monkeypatch.setattr(_lazy_fixed_width, "iter_fixed_width_records", spy)


def test_is_a_lazy_source_built_from_a_descriptor(tmp_path: Path) -> None:
    src = lazy(write(tmp_path / "f.dat", records(3)), table="orders")
    assert isinstance(src, LazySource)
    assert src.table == "orders"
    assert src.layout.columns[1].type == "int"


def test_at18_a_stopped_iteration_reads_one_batch_of_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = lazy(write(tmp_path / "f.dat", records(10)))
    spy = Spy(monkeypatch)
    it = src.iter_batches(3)
    first = next(it)
    it.close()
    assert first.num_rows == 3
    assert spy.yielded == 3


def test_at18_batches_are_capped_and_cover_every_row(tmp_path: Path) -> None:
    src = lazy(write(tmp_path / "f.dat", records(7)))
    sizes = [b.num_rows for b in src.iter_batches(3)]
    assert sizes == [3, 3, 1]


def test_at18_columns_select_a_projection(tmp_path: Path) -> None:
    src = lazy(write(tmp_path / "f.dat", records(4)))
    batch = next(src.iter_batches(10, columns=["n", "s"]))
    assert batch.schema.names == ["n", "s"]
    assert batch.column(0).to_pylist() == [0, 1, 2, 3]
    assert src.to_table(["f"]).column("f").to_pylist() == [0.5, 1.5, 2.5, 3.5]


@pytest.mark.parametrize(
    "payload",
    [
        records(40) + b"\n\n",
        b"\n" + records(40, sep=b"\n\n"),
        records(40, sep=b"\r\n"),
        records(40).rstrip(b"\n"),
    ],
    ids=["trailing-blanks", "interleaved-blanks", "crlf", "no-final-newline"],
)
def test_at18a_num_rows_is_exact(tmp_path: Path, payload: bytes) -> None:
    assert lazy(write(tmp_path / "f.dat", payload)).num_rows == 40


def test_at18a_the_count_is_cached_while_the_identity_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path / "f.dat", records(5))
    src = lazy(path)
    spy = Spy(monkeypatch)
    assert src.num_rows == 5
    assert spy.opened == 1
    assert src.num_rows == 5
    assert src.column_null_counts() == {"s": 0, "n": 0, "f": 0}
    assert spy.opened == 1
    write(path, records(8))
    assert src.num_rows == 8
    assert spy.opened == 2


def test_at18a_facts_carry_no_row_groups(tmp_path: Path) -> None:
    facts = lazy(write(tmp_path / "f.dat", records(5))).footer_facts()
    assert (facts.num_rows, facts.row_groups, facts.max_row_group_rows) == (5, 0, 0)


def test_at18b_schema_and_batches_equal_the_resident_read(tmp_path: Path) -> None:
    path = write(tmp_path / "f.dat", records(6))
    src = lazy(path)
    frame = read_fixed_width(path, LAYOUT)
    resident = pa.Table.from_pandas(frame, preserve_index=False)
    assert src.schema == resident.schema
    assert src.footer_facts().schema == resident.schema
    got = pa.Table.from_batches(list(src.iter_batches(4)))
    assert got.schema == resident.schema
    assert got.to_pylist() == resident.to_pylist()
    assert src.to_table().to_pylist() == resident.to_pylist()


def test_at18b_an_empty_file_keeps_the_layout_schema(tmp_path: Path) -> None:
    src = lazy(write(tmp_path / "f.dat", b""))
    want = pa.schema([("s", pa.string()), ("n", pa.int64()), ("f", pa.float64())])
    assert src.schema == want
    assert src.num_rows == 0
    assert src.to_table().schema == want
    assert list(src.iter_batches(5)) == []


def test_at18c_a_rewrite_between_facts_and_open_is_refused(tmp_path: Path) -> None:
    path = write(tmp_path / "f.dat", records(4))
    src = lazy(path)
    src.footer_facts()
    write(path, records(6))
    with pytest.raises(ExecutionError) as exc:
        src.open_batches(2)
    assert exc.value.code == reasons.runtime.LAZY_SOURCE_CHANGED


def test_at18c_a_same_size_rewrite_is_refused_by_identity(tmp_path: Path) -> None:
    path = write(tmp_path / "f.dat", records(4))
    src = lazy(path)
    src.footer_facts()
    stat = path.stat()
    write(path, records(4).replace(b"row1", b"rowX"))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    with pytest.raises(ExecutionError) as exc:
        src.open_batches(2)
    assert exc.value.code == reasons.runtime.LAZY_SOURCE_CHANGED


def test_at18c_a_rewrite_while_batches_are_read_is_refused(tmp_path: Path) -> None:
    path = write(tmp_path / "f.dat", records(6))
    src = lazy(path)
    opened = src.open_batches(2)
    assert opened.facts.num_rows == 6
    it = iter(opened.batches)
    next(it)
    write(path, records(9))
    with pytest.raises(ExecutionError) as exc:
        list(it)
    assert exc.value.code == reasons.runtime.LAZY_SOURCE_CHANGED


def test_at18c_an_unchanged_file_reads_through_open_batches(tmp_path: Path) -> None:
    src = lazy(write(tmp_path / "f.dat", records(5)))
    opened = src.open_batches(2)
    assert opened.facts.num_rows == 5
    assert [b.num_rows for b in opened.batches] == [2, 2, 1]
    opened.close()
    projected = src.open_batches(10, columns=["n"])
    assert next(iter(projected.batches)).schema.names == ["n"]
    assert projected.facts.schema.names == ["s", "n", "f"]


def _count_changes_during_the_pass(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> FixedWidthLazySource:
    src = lazy(path)
    real = _lazy_fixed_width.iter_fixed_width_records

    def rewriting(*args: Any, **kwargs: Any) -> Iterator[Any]:
        yield from real(*args, **kwargs)
        write(path, records(9))

    monkeypatch.setattr(_lazy_fixed_width, "iter_fixed_width_records", rewriting)
    return src


def test_at18c_a_rewrite_during_the_count_pass_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _count_changes_during_the_pass(write(tmp_path / "f.dat", records(4)), monkeypatch)
    with pytest.raises(ExecutionError) as exc:
        src.footer_facts()
    assert exc.value.code == reasons.runtime.LAZY_SOURCE_CHANGED


_GOOD = _SENTINEL.encode() + b" 123  1.50\n"


@pytest.mark.parametrize(
    "tail",
    [
        _SENTINEL.encode() + b"abc  1.50\n",  # bad int cast
        _SENTINEL[:7].encode() + b"\n",  # short record
        b"\xff" + _SENTINEL.encode() + b"\n",  # not UTF-8
    ],
    ids=["cast", "short", "utf8"],
)
def test_at18d_a_bad_record_in_the_batches_is_value_free(tmp_path: Path, tail: bytes) -> None:
    src = lazy(write(tmp_path / "f.dat", _GOOD * 2 + tail))
    with pytest.raises(FixedWidthParseError) as info:
        list(src.iter_batches(100))
    _assert_sentinel_unreachable(info.value)
    assert "line 3" in str(info.value)


@pytest.mark.parametrize(
    "tail",
    [_SENTINEL[:7].encode() + b"\n", b"\xff" + _SENTINEL.encode() + b"\n"],
    ids=["short", "utf8"],
)
def test_at18d_a_bad_record_in_the_count_pass_is_value_free(tmp_path: Path, tail: bytes) -> None:
    src = lazy(write(tmp_path / "f.dat", _GOOD * 2 + tail))
    with pytest.raises(FixedWidthParseError) as info:
        src.footer_facts()
    _assert_sentinel_unreachable(info.value)
    with pytest.raises(FixedWidthParseError) as info2:
        _ = src.num_rows
    _assert_sentinel_unreachable(info2.value)


def test_at18d_a_bad_record_after_a_yielded_batch_is_value_free(tmp_path: Path) -> None:
    src = lazy(write(tmp_path / "f.dat", _GOOD * 2 + _SENTINEL.encode() + b"abc  1.50\n"))
    it = src.iter_batches(2)
    assert next(it).num_rows == 2
    with pytest.raises(FixedWidthParseError) as info:
        next(it)
    _assert_sentinel_unreachable(info.value)


def test_at18d_a_bad_record_through_open_batches_is_value_free(tmp_path: Path) -> None:
    src = lazy(write(tmp_path / "f.dat", _GOOD * 2 + _SENTINEL[:7].encode() + b"\n"))
    with pytest.raises(FixedWidthParseError) as info:
        src.open_batches(10)
    _assert_sentinel_unreachable(info.value)
