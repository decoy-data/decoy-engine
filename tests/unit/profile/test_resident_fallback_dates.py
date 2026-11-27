"""The resident profiling fallback keeps an admitted date dictionary a categorical
(DATE-RANGE-SENTINEL S5 remediation round 2, V1-6).

An unrelated column pandas cannot hold (a `time64[ns]` with a sub-microsecond value) sends the
whole table to the per-column fallback. Only that column becomes text."""

from __future__ import annotations

import datetime as dt

import pyarrow as pa

from decoy_engine.profile._readers_resident import ResidentTableSource


def _table() -> pa.Table:
    entries = pa.array([dt.date(1970, 1, 1), None, dt.date(2020, 1, 2)], pa.date32())
    dates = pa.DictionaryArray.from_arrays(pa.array([0, 2, None, 0], pa.int8()), entries)
    times = pa.array([1, 2, 3, 4], pa.time64("ns"))  # 1 ns: not representable in pandas
    return pa.table({"d": dates, "t": times})


def test_only_the_unrepresentable_column_becomes_text() -> None:
    frame = ResidentTableSource(_table(), "t").to_frame()
    assert str(frame["d"].dtype) == "category"
    assert frame["d"].tolist()[:2] == [dt.date(1970, 1, 1), dt.date(2020, 1, 2)]
    assert frame["d"].isna().tolist() == [False, False, True, False]
    assert frame["t"].map(type).eq(str).all()


def test_the_sample_route_keeps_the_categorical_too() -> None:
    frame = ResidentTableSource(_table(), "t").sample_frame(3)
    assert str(frame["d"].dtype) == "category" and len(frame) == 3
