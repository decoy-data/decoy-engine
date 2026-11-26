"""R1 (SOURCE-READ-BOUNDARY S1b-1): the conversion choke point and its required callback."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.internal.pandas_compat import (
    arrow_to_frame,
    arrow_to_frame_pair,
    arrow_to_series,
)

# Day numbers and nanoseconds the failure text must never carry.
_LEAKS = ("10000", "2932897", "-768", "non-zero nanoseconds")


class _RefusedError(Exception):
    def __init__(self, column: str | None) -> None:
        super().__init__(f"column {column}")
        self.column = column


def _refuse(column: str | None) -> NoReturn:
    raise _RefusedError(column) from None


def _date32(days: int) -> pa.Array:
    return pa.array([days, 19000, None], pa.int32()).cast(pa.date32())


def _bad_table(kind: str) -> pa.Table:
    if kind == "date32":
        bad = _date32(2932897)
    elif kind == "date64":
        bad = pa.array([253402300800000, 0, None], pa.int64()).cast(pa.date64())
    else:
        bad = pa.array([1, 2, None], pa.time64("ns"))
    return pa.table({"ok": [1, 2, 3], "bad": bad})


@pytest.mark.parametrize("kind", ["date32", "date64", "time64"])
def test_unrepresentable_column_calls_the_callback_with_its_name(kind: str) -> None:
    with pytest.raises(_RefusedError) as caught:
        arrow_to_frame(_bad_table(kind), on_unrepresentable=_refuse)
    exc = caught.value
    assert exc.column == "bad"
    assert exc.__cause__ is None and exc.__context__ is None and exc.__suppress_context__
    text = "".join(traceback.format_exception(exc)) + repr(exc) + str(exc)
    assert not [leak for leak in _LEAKS if leak in text]


def test_in_range_table_equals_its_plain_conversion() -> None:
    table = pa.table({"i": [1, None, 3], "d": _date32(19000), "s": ["a", None, "c"]})
    pd.testing.assert_frame_equal(
        arrow_to_frame(table, on_unrepresentable=_refuse), table.to_pandas()
    )


def test_a_callback_that_returns_is_a_value_free_type_error() -> None:
    def returns(_column: str | None) -> NoReturn:
        return None  # type: ignore[misc]

    with pytest.raises(TypeError, match="on_unrepresentable must raise") as caught:
        arrow_to_frame(_bad_table("date32"), on_unrepresentable=returns)
    assert not [leak for leak in _LEAKS if leak in str(caught.value)]


def test_the_callback_is_required() -> None:
    with pytest.raises(TypeError):
        arrow_to_frame(_bad_table("date32"))  # type: ignore[call-arg]


@pytest.mark.parametrize("entry", [arrow_to_frame, arrow_to_series, arrow_to_frame_pair])
def test_widening_is_not_available_yet(entry: Callable[..., object]) -> None:
    table = pa.table({"a": [1]})
    args: tuple[object, ...] = (table, table) if entry is arrow_to_frame_pair else (table,)
    if entry is arrow_to_series:
        args = (table.column("a"),)
    with pytest.raises(NotImplementedError):
        entry(*args, on_unrepresentable=_refuse, widen=True)


def test_series_and_pair_use_the_same_callback() -> None:
    bad = _bad_table("date32")
    with pytest.raises(_RefusedError) as one:
        arrow_to_series(bad.column("bad"), on_unrepresentable=_refuse, name="bad")
    assert one.value.column == "bad"
    good = pa.table({"ok": [1, 2, 3]})
    with pytest.raises(_RefusedError):
        arrow_to_frame_pair(good, bad, on_unrepresentable=_refuse)
    left, right = arrow_to_frame_pair(good, good, on_unrepresentable=_refuse)
    assert left.equals(right)


class _FakeColumn:
    def __init__(self, error: Exception | None) -> None:
        self._error = error

    def to_pandas(self, **_kwargs: object) -> pd.Series:
        if self._error is not None:
            raise self._error
        return pd.Series([1])


class _FakeTable:
    """A table whose whole-table conversion raises a value-quoting ValueError."""

    column_names = ("ok",)

    def __init__(self, probe_error: Exception | None) -> None:
        self._probe_error = probe_error

    def to_pandas(self, **_kwargs: object) -> pd.DataFrame:
        raise ValueError("out of bounds 2932897")

    def column(self, _position: int) -> _FakeColumn:
        return _FakeColumn(self._probe_error)


def test_a_probe_that_raises_an_arrow_exception_still_reaches_the_callback_value_free() -> None:
    fake: Any = _FakeTable(pa.ArrowException("Wrapping cell 2932897 failed"))
    with pytest.raises(_RefusedError) as caught:
        arrow_to_frame(fake, on_unrepresentable=_refuse)
    exc = caught.value
    assert exc.column == "ok"
    assert exc.__cause__ is None and exc.__context__ is None
    assert "2932897" not in "".join(traceback.format_exception(exc))


def test_no_single_failing_column_calls_the_callback_with_none() -> None:
    fake: Any = _FakeTable(None)
    with pytest.raises(_RefusedError) as caught:
        arrow_to_frame(fake, on_unrepresentable=_refuse)
    exc = caught.value
    assert exc.column is None
    assert exc.__cause__ is None and exc.__context__ is None
    assert "2932897" not in "".join(traceback.format_exception(exc))


def test_a_bare_memory_error_in_a_probe_propagates_as_itself_without_context() -> None:
    # Not an unrepresentable-value type, so the probe's handler never sees it.
    probe_error = MemoryError("2932897")
    fake: Any = _FakeTable(probe_error)
    with pytest.raises(MemoryError) as caught:
        arrow_to_frame(fake, on_unrepresentable=_refuse)
    assert caught.value is probe_error
    assert caught.value.__context__ is None


def test_an_arrow_memory_error_in_a_probe_is_raised_value_free_without_context() -> None:
    # Recognised by the shared classifier: raised as its rebuilt twin, never the original.
    probe_error = pa.ArrowMemoryError("2932897")
    fake: Any = _FakeTable(probe_error)
    with pytest.raises(pa.ArrowMemoryError) as caught:
        arrow_to_frame(fake, on_unrepresentable=_refuse)
    assert caught.value is not probe_error
    assert "2932897" not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_a_resource_failure_in_the_conversion_propagates_as_itself() -> None:
    class _Oom:
        column_names = ("ok",)

        def to_pandas(self, **_kwargs: object) -> pd.DataFrame:
            raise pa.ArrowMemoryError("out of memory")

    fake: Any = _Oom()
    with pytest.raises(MemoryError):
        arrow_to_frame(fake, on_unrepresentable=_refuse)
    with pytest.raises(MemoryError):
        arrow_to_series(fake, on_unrepresentable=_refuse, name="ok")


class _CapTable:
    """Whole-table conversion hits the hard cap (Arrow's `Wrapping ... failed`); a column alone fits."""

    column_names = ("ok",)

    def to_pandas(self, **_kwargs: object) -> pd.DataFrame:
        raise pa.ArrowException("Unknown error: Wrapping 2932897 failed")

    def column(self, _position: int) -> _FakeColumn:
        return _FakeColumn(None)


def test_a_cap_failure_that_does_not_reproduce_stays_a_memory_failure_value_free() -> None:
    from decoy_engine.fileaccess import is_memory_failure

    fake: Any = _CapTable()
    with pytest.raises(pa.ArrowException) as caught:
        arrow_to_frame(fake, on_unrepresentable=_refuse)
    assert is_memory_failure(caught.value)
    assert "2932897" not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_a_series_cap_failure_that_does_not_reproduce_stays_a_memory_failure() -> None:
    from decoy_engine.fileaccess import is_memory_failure

    calls: list[int] = []

    class _Once:
        def to_pandas(self, **_kwargs: object) -> pd.Series:
            calls.append(1)
            if len(calls) == 1:
                raise pa.ArrowException("Unknown error: Wrapping 2932897 failed")
            return pd.Series([1])

    fake: Any = _Once()
    with pytest.raises(pa.ArrowException) as caught:
        arrow_to_series(fake, on_unrepresentable=_refuse, name="ok")
    assert is_memory_failure(caught.value)
    assert "2932897" not in str(caught.value)


def test_a_series_retry_that_hits_a_typed_allocation_failure_stays_a_memory_failure() -> None:
    # The first conversion reports Arrow's ambiguous "Wrapping ... failed"; the retry reports the
    # typed allocation failure. The caller must see memory, not a bad column, and no value text.
    from decoy_engine.fileaccess import is_memory_failure

    calls: list[int] = []

    class _Pressure:
        def to_pandas(self, **_kwargs: object) -> pd.Series:
            calls.append(1)
            if len(calls) == 1:
                raise pa.ArrowException("Unknown error: Wrapping 2932897 failed")
            raise pa.ArrowMemoryError("malloc of size 2932897 failed")

    fake: Any = _Pressure()
    with pytest.raises(pa.ArrowMemoryError) as caught:
        arrow_to_series(fake, on_unrepresentable=_refuse, name="ok")
    assert is_memory_failure(caught.value)
    assert "2932897" not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def _invalid_utf8_table() -> pa.Table:
    data = b"ok\xff\xfesecret"
    offsets = pa.array([0, 2, len(data)], pa.int32()).buffers()[1]
    column = pa.Array.from_buffers(pa.string(), 2, [None, offsets, pa.py_buffer(data)])
    return pa.table({"n": [1, 2], "s": column})


def _assert_value_free(exc: BaseException) -> None:
    text = "".join(traceback.format_exception(exc)) + repr(exc) + str(exc)
    assert "secret" not in text and "\ufffd" not in text and "Wrapping" not in text
    assert exc.__cause__ is None and exc.__context__ is None
    assert not getattr(exc, "__notes__", None)


@pytest.mark.parametrize("entry", ["frame", "series", "pair"])
def test_invalid_utf8_from_a_parquet_file_reaches_the_callback_value_free(
    entry: str, tmp_path: Path
) -> None:
    path = tmp_path / "t.parquet"
    pq.write_table(_invalid_utf8_table(), path)
    table = pq.read_table(path)
    with pytest.raises(_RefusedError) as caught:
        if entry == "frame":
            arrow_to_frame(table, on_unrepresentable=_refuse)
        elif entry == "series":
            arrow_to_series(table.column("s"), on_unrepresentable=_refuse, name="s")
        else:
            arrow_to_frame_pair(table, table, on_unrepresentable=_refuse)
    assert caught.value.column == "s"
    _assert_value_free(caught.value)


def _raised(call: Callable[[], object]) -> BaseException:
    try:
        call()
    except BaseException as exc:
        return exc
    raise AssertionError("the call returned")


class _Classified:
    """A stand-in for `fileaccess.classified_failure` that reads every failure as the given kind."""

    def __init__(self, kind: str, fresh: BaseException | None) -> None:
        self._kind = kind
        self._fresh = fresh
        self.seen: list[BaseException] = []

    def __call__(self, exc: BaseException) -> Any:
        from decoy_engine.fileaccess import ClassifiedFailure

        self.seen.append(exc)
        return ClassifiedFailure(self._kind, self._fresh)  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", ["typed_memory", "resource"])
def test_the_choke_point_follows_the_shared_classifier_for_resource_kinds(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One classification: a failure the shared classifier calls a resource failure is raised as
    its fresh twin from every entry, whatever the text says."""
    fresh = MemoryError("fixed")
    classifier = _Classified(kind, fresh)
    monkeypatch.setattr("decoy_engine.fileaccess.classified_failure", classifier)
    table: Any = _FakeTable(None)
    column: Any = _FakeColumn(ValueError("Wrapping 2932897 failed"))
    for call in (
        lambda: arrow_to_frame(table, on_unrepresentable=_refuse),
        lambda: arrow_to_series(column, on_unrepresentable=_refuse, name="ok"),
    ):
        raised = _raised(call)
        assert raised is fresh
        assert raised.__cause__ is None and raised.__context__ is None
    assert len(classifier.seen) == 2


def test_a_resource_kind_without_a_rebuild_raises_the_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("decoy_engine.fileaccess.classified_failure", _Classified("resource", None))
    table: Any = _FakeTable(None)
    raised = _raised(lambda: arrow_to_frame(table, on_unrepresentable=_refuse))
    assert isinstance(raised, ValueError) and "out of bounds" in str(raised)


class _CausedByMemory(_FakeTable):
    def to_pandas(self, **_kwargs: object) -> pd.DataFrame:
        try:
            raise MemoryError("2932897")
        except MemoryError as inner:
            raise ValueError("Wrapping 2932897 failed") from inner


def test_a_value_error_caused_by_memory_exhaustion_is_a_value_free_memory_error() -> None:
    fake: Any = _CausedByMemory(None)
    raised = _raised(lambda: arrow_to_frame(fake, on_unrepresentable=_refuse))
    assert isinstance(raised, MemoryError)
    assert "2932897" not in "".join(traceback.format_exception(raised))
    assert raised.__cause__ is None and raised.__context__ is None
