"""PREFLIGHT-ARROW-PROFILE S1b, Codex round 1: the declared pyarrow floor, the memory text
markers at the pandas conversion sites, and what the bounded boundary forwards.

Each test names the review finding it pins. The reference profile comes from `support`.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import fileaccess, reasons
from decoy_engine._execution_error import ExecutionError
from decoy_engine.errors import ConfigError
from decoy_engine.profile import _readers
from decoy_engine.profile._readers_resident import _frame_of
from tests.unit.profile.arrow_profile.support import (
    SAFE_FAILURE,
    bounded_profile,
    make_reader,
    parquet_bytes,
)

MARKER = "123456789"
ENVELOPE = "digital envelope routines"
T_NS_BAD = 3_600_000_000_000 + 987_654_321


def _formatted(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc)) + repr(exc) + str(exc)


def _column(profile: Any, name: str) -> Any:
    return next(c for c in profile.columns if c.name == name)


# ---------------------------------------------- V1: PyArrow 14 and 15 have no view predicates


@pytest.mark.parametrize("kind", ["local", "s3", "gcs"])
def test_recovery_runs_where_pyarrow_has_no_view_types(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`pa.types.is_string_view` and `is_binary_view` arrive in PyArrow 16; the declared floor
    is 14. A bad date/time file must still profile there."""
    table = pa.table(
        {
            "t": pa.array([0, 1000, 2000, T_NS_BAD], pa.time64("ns")),
            "email": ["a@x.test", "b@x.test", "c@x.test", "d@x.test"],
        }
    )
    reader = make_reader(kind, table, parquet_bytes(table), tmp_path, monkeypatch)
    monkeypatch.delattr(pa.types, "is_string_view", raising=False)
    monkeypatch.delattr(pa.types, "is_binary_view", raising=False)
    profile = bounded_profile(reader, kind)
    t = _column(profile, "t")
    assert (t.dtype, t.distinct_count) == ("object", 4)
    assert _column(profile, "email").distinct_count == 4


# ---------------------------------------------- V1: a pandas error that quotes the OpenSSL text


def _quoted_period(freq: str = ENVELOPE) -> pa.Table:
    from pandas.core.arrays.arrow.extension_types import ArrowPeriodType

    storage = pa.array([1, 2], pa.int64())
    return pa.table({"p": pa.ExtensionArray.from_storage(ArrowPeriodType(freq), storage)})


def test_a_resident_period_frequency_quoting_the_openssl_text_is_not_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = _quoted_period()
    # The resident fallback profiles the column as text, as the base does (AT-12 pins the same
    # profile for another frequency text against the recorded base).
    resident = bounded_profile(
        make_reader("resident", table, b"", tmp_path, monkeypatch), "resident"
    )
    p = _column(resident, "p")
    assert (p.dtype, p.distinct_count, p.avg_length, p.max_length) == ("object", 2, 1.0, 1)


def test_a_resident_period_frequency_quoting_the_arrow_text_is_not_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = _quoted_period("Unknown error: Wrapping x failed")
    resident = bounded_profile(
        make_reader("resident", table, b"", tmp_path, monkeypatch), "resident"
    )
    p = _column(resident, "p")
    assert (p.dtype, p.distinct_count, p.avg_length, p.max_length) == ("object", 2, 1.0, 1)


def test_a_parquet_period_frequency_quoting_the_openssl_text_is_a_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = _quoted_period()
    try:
        data = parquet_bytes(table)
    except (pa.ArrowNotImplementedError, pa.ArrowInvalid, pa.ArrowTypeError):
        pytest.skip("this stack cannot write the extension type to Parquet")
    reader = make_reader("local", table, data, tmp_path, monkeypatch)
    with pytest.raises(ValueError, match=SAFE_FAILURE) as caught:
        bounded_profile(reader, "local")
    assert not fileaccess.is_memory_failure(caught.value)
    assert ENVELOPE not in _formatted(caught.value)


class _Failing:
    """A table whose whole conversion, and each column's, raises `exc`."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.columns = [self]
        self.column_names = ["a"]

    def to_pandas(self) -> Any:
        raise self._exc


@pytest.mark.parametrize(
    "exc",
    [
        pa.ArrowInvalid(f"Unknown error: Wrapping {MARKER} failed"),
        ValueError(f"Unknown error: Wrapping {MARKER} failed"),
    ],
)
def test_a_genuine_arrow_memory_failure_still_stops_the_resident_fallback(
    exc: BaseException,
) -> None:
    with pytest.raises(type(exc)) as caught:
        _frame_of(_Failing(exc))  # type: ignore[arg-type]
    assert caught.value is exc


def test_a_genuine_arrow_memory_failure_stops_the_column_fallback() -> None:
    whole = ValueError("not memory")
    leaky = pa.ArrowInvalid(f"Unknown error: Wrapping {MARKER} failed")

    class _Table(_Failing):
        def __init__(self) -> None:
            super().__init__(whole)
            self.columns = [_Failing(leaky)]

    with pytest.raises(pa.ArrowInvalid) as caught:
        _frame_of(_Table())  # type: ignore[arg-type]
    assert caught.value is leaky


# ---------------------------------------------- DESIGN: only trusted failures are forwarded


def _raising_reader(exc: BaseException, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    table = pa.table({"a": [1, 2]})
    reader = make_reader("local", table, parquet_bytes(table), tmp_path, monkeypatch)

    def boom(self: Any, sample_rows: int) -> Any:
        raise exc

    monkeypatch.setattr(_readers.ParquetFileSource, "sample_table", boom)
    return reader


def test_an_uncoded_config_error_is_a_closed_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _raising_reader(ConfigError(f"bad cell {MARKER}"), tmp_path, monkeypatch)
    with pytest.raises(ValueError, match=SAFE_FAILURE) as caught:
        bounded_profile(reader, "local")
    assert MARKER not in _formatted(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_an_uncoded_connector_error_is_a_closed_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decoy_engine.sdk import PermanentError

    reader = _raising_reader(PermanentError(f"bad cell {MARKER}"), tmp_path, monkeypatch)
    with pytest.raises(ValueError, match=SAFE_FAILURE) as caught:
        bounded_profile(reader, "local")
    assert MARKER not in _formatted(caught.value)


def test_a_coded_engine_error_keeps_its_own_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ExecutionError(
        code=reasons.runtime.FULL_FRAME_VALUE_UNREPRESENTABLE, message="fixed text"
    )
    reader = _raising_reader(original, tmp_path, monkeypatch)
    with pytest.raises(ExecutionError) as caught:
        bounded_profile(reader, "local")
    assert caught.value is original


def test_the_duplicate_name_refusal_keeps_its_own_type() -> None:
    from decoy_engine._field_names import DuplicateFieldNamesError
    from decoy_engine.profile._source import _passes_through

    assert _passes_through(DuplicateFieldNamesError("m"))
    assert not _passes_through(ConfigError("m"))
