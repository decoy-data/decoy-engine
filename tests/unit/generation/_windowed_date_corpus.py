"""Parity corpus and reference oracle for `apply_windowed_date` (GEN-WINDOWED-BATCH).

`reference_apply_windowed_date` is the per-row loop of origin/main 75fba3d855d71e3980a62afc3ce7f1187b72073d,
copied here with its helpers so a change to the module cannot move the oracle. The corpus is
data only; the tests live in `test_windowed_date_batch_parity.py`.
"""

from __future__ import annotations

import datetime as dt
import decimal
import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any

import numpy as np
import pandas as pd

from decoy_engine.determinism._derive import derive
from decoy_engine.transforms.windowed_date import WindowedDateConfig, WindowedDateError

_UTC = dt.timezone.utc
_DATE_FMT = "%Y-%m-%d"
_MIN = pd.Timestamp("1700-01-01")
_MAX = pd.Timestamp("2200-12-31 23:59:59.999999999")
_ISO = re.compile(
    r"\A\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?)?\Z",
    re.ASCII,
)


def _sample_offset(rng: np.random.Generator, lo: int, hi: int, distribution: str) -> int:
    span = hi - lo
    if span == 0:
        return lo
    a = int(rng.integers(lo, hi + 1))
    if distribution == "uniform":
        return a
    b = int(rng.integers(lo, hi + 1))
    if distribution == "early":
        return min(a, b)
    return max(a, b)


def _is_null(raw: Any) -> bool:
    if raw is None or raw is pd.NaT or raw is pd.NA:
        return True
    return isinstance(raw, float) and raw != raw


def _parse(raw: Any, position: int) -> pd.Timestamp:
    ts: pd.Timestamp
    failed = False
    if isinstance(raw, str):
        if _ISO.match(raw) is None:
            raise WindowedDateError(
                f"windowed_date anchor at row {position} is not an ISO date or datetime "
                "without a timezone"
            )
        try:
            ts = pd.Timestamp(raw)
        except (ValueError, OverflowError):
            failed = True
        if failed:
            raise WindowedDateError(
                f"windowed_date anchor at row {position} is not a valid calendar date"
            ) from None
    elif isinstance(raw, (pd.Timestamp, dt.datetime, dt.date)):
        if getattr(raw, "tzinfo", None) is not None:
            raise WindowedDateError(f"windowed_date anchor at row {position} carries a timezone")
        try:
            ts = pd.Timestamp(raw)
        except (ValueError, OverflowError):
            failed = True
        if failed:
            raise WindowedDateError(
                f"windowed_date anchor at row {position} is outside the supported range"
            ) from None
    else:
        raise WindowedDateError(
            f"windowed_date anchor at row {position} has unsupported type {type(raw).__name__}"
        )
    if ts is pd.NaT or pd.isna(ts):
        raise WindowedDateError(f"windowed_date anchor at row {position} parses to NaT")
    if not (_MIN <= ts <= _MAX):
        raise WindowedDateError(
            f"windowed_date anchor at row {position} is outside the supported range"
        )
    return ts


def _shift(anchor: pd.Timestamp, offset: int, position: int) -> str:
    try:
        out = anchor + pd.Timedelta(offset, unit="D")
        if _MIN <= out <= _MAX:
            return str(out.strftime(_DATE_FMT))
    except (OverflowError, ValueError):
        pass
    raise WindowedDateError(
        f"windowed_date result at row {position} is outside the supported range"
    ) from None


def reference_apply_windowed_date(
    config: WindowedDateConfig,
    df: pd.DataFrame,
    seed: bytes,
    namespace: str,
    row_offset: int = 0,
    positions: Sequence[int] | None = None,
) -> list[str | None]:
    anchor_series = df[config.anchor]
    result: list[str | None] = []
    row_numbers: Sequence[int] = (
        positions if positions is not None else range(row_offset, row_offset + len(anchor_series))
    )
    for i, raw_anchor in zip(row_numbers, anchor_series, strict=True):
        if _is_null(raw_anchor):
            result.append(None)
            continue
        anchor_ts = _parse(raw_anchor, int(i))
        row_seed_int = int.from_bytes(derive(seed, namespace, int(i).to_bytes(8, "big"))[:8], "big")
        row_rng = np.random.default_rng(row_seed_int)
        offset = _sample_offset(row_rng, config.min_days, config.max_days, config.distribution)
        result.append(_shift(anchor_ts, offset, int(i)))
    return result


class MyDate(dt.date):
    """A `date` subclass: exact-type admission must send it to the reference path."""


@dataclass
class Case:
    name: str
    anchors: Callable[[], pd.Series]
    min_days: int = -30
    max_days: int = 90
    distribution: str = "uniform"
    seed: bytes = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    namespace: str = "windowed_date/ev"
    row_offset: int = 0
    positions: Callable[[int], list[int]] | None = None
    admitted: bool = False  # True when the fast path must run (no reference call)
    expect_error: bool | None = False  # None: parity only (the draws decide)
    tags: set[str] = field(default_factory=set)

    def config(self) -> WindowedDateConfig:
        return WindowedDateConfig(
            anchor="a",
            min_days=self.min_days,
            max_days=self.max_days,
            distribution=self.distribution,
        )

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame({"a": self.anchors()})

    def pos(self, n: int) -> list[int] | None:
        return None if self.positions is None else self.positions(n)


SEED8 = b"\x01\x02\x03\x04\x05\x06\x07\x08"
SEED32 = bytes(range(32))
DISTS = ("uniform", "early", "late")
NULLS: tuple[Any, ...] = (None, float("nan"), pd.NA, pd.NaT)


def _obj(values: list[Any]) -> pd.Series:
    return pd.Series(values, dtype=object)


def _iso_main() -> pd.Series:
    rng = np.random.default_rng(0)
    days = rng.integers(0, 14_600, size=2000)  # 1990-01-01 .. ~2030
    base = np.datetime64("1990-01-01")
    values: list[Any] = [str(base + int(d)) for d in days]
    for k, idx in enumerate(range(0, 2000, 20)):
        values[idx] = NULLS[k % 4]
    return _obj(values)


EDGE_STRINGS = [
    "2000-01-01",
    "2000-01-01T12:30",
    "2000-01-01 12:30",
    "2000-01-01T12:30:45",
    "2000-01-01 12:30:45",
    "2000-01-01T12:30:45.5",
    "2000-01-01T12:30:45.12",
    "2000-01-01T12:30:45.123",
    "2000-01-01T12:30:45.1234",
    "2000-01-01T12:30:45.12345",
    "2000-01-01T12:30:45.123456",
    "2000-01-01T12:30:45.1234567",
    "2000-01-01T12:30:45.12345678",
    "2000-01-01T12:30:45.123456789",
    "1960-05-05T23:59:59",
    "1969-12-31T23:59:59.999999999",
    "1969-12-31",
    "1970-01-01",
    "2000-02-29",
    "1900-02-28",
    "2024-02-29",
    "2024-02-29T23:59:59.999999999",
]


def _err_series(bad: Any, *, good_before: int = 6) -> pd.Series:
    good = ["2001-03-04", "2010-11-12", "1999-12-31", "2020-02-29", "1985-07-01", "2005-05-05"]
    return _obj([*good[:good_before], bad, "2002-02-02", "2003-03-03"])


def _anchor_pair(anchor: str) -> pd.Series:
    return _obj(["2000-01-01", anchor])


def _typed(kind: str, n: int = 300) -> pd.Series:
    rng = np.random.default_rng(1)
    days = rng.integers(0, 20_000, size=n)
    base = dt.date(1970, 1, 1)
    dates: list[Any] = [base + dt.timedelta(days=int(d)) for d in days]
    if kind == "date":
        values: list[Any] = dates
    elif kind == "datetime":
        values = [
            dt.datetime.combine(d, dt.time(int(h), int(m), int(s), int(us)))
            for d, h, m, s, us in zip(
                dates,
                rng.integers(0, 24, n),
                rng.integers(0, 60, n),
                rng.integers(0, 60, n),
                rng.integers(0, 1_000_000, n),
                strict=True,
            )
        ]
    elif kind == "timestamp":
        values = [
            pd.Timestamp(d) + pd.Timedelta(int(ns), unit="ns")
            for d, ns in zip(dates, rng.integers(0, 86_400 * 10**9, n), strict=True)
        ]
    else:
        raise AssertionError(kind)
    for k in range(0, n, 25):
        values[k] = NULLS[(k // 25) % 4]
    return _obj(values)


def _dt64() -> pd.Series:
    s = pd.Series(pd.to_datetime(_typed("timestamp", 300).where(lambda x: x.notna(), pd.NaT)))
    assert str(s.dtype) == "datetime64[ns]"
    return s


def build_cases() -> list[Case]:
    cases: list[Case] = []
    for dist in DISTS:
        cases.append(Case(f"main_{dist}", _iso_main, distribution=dist, admitted=True))
    cases.append(Case("main_seed32", _iso_main, seed=SEED32, admitted=True))
    cases.append(Case("main_min_eq_max", _iso_main, min_days=7, max_days=7, admitted=True))
    cases.append(Case("main_negative_window", _iso_main, min_days=-90, max_days=-1, admitted=True))
    cases.append(Case("main_wide_window", _iso_main, min_days=-3650, max_days=3650, admitted=True))

    for dist in DISTS:
        cases.append(
            Case(
                f"edge_strings_{dist}",
                lambda: _obj(EDGE_STRINGS),
                distribution=dist,
                min_days=-30,
                max_days=90,
                admitted=True,
            )
        )
    cases.append(
        Case(
            "range_low_edge",
            lambda: _obj(["1700-01-01", "1700-01-01T12:00"]),
            min_days=0,
            max_days=30,
            admitted=True,
        )
    )
    cases.append(
        Case(
            "range_high_edge",
            lambda: _obj(["2200-12-31", "2200-12-31T23:59:59.999999999"]),
            min_days=-30,
            max_days=0,
            admitted=True,
        )
    )
    cases.append(
        Case(
            "window_to_ns_limit",
            lambda: _obj(["1700-01-01"]),
            min_days=106_751,
            max_days=106_751,
            admitted=True,
        )
    )

    # Windows past the ns timedelta range (and past the supported date range).
    for name, lo, hi, anchor in (
        ("past_ns_pos_exact", 106_752, 106_752, "1700-01-01"),
        ("past_ns_pos_wide", 0, 200_000, "2000-01-01"),
        ("past_ns_pos_far", 150_000, 200_000, "1700-01-01"),
        ("past_ns_neg_exact", -106_752, -106_752, "2200-12-31"),
        ("past_ns_neg_wide", -200_000, 0, "2000-01-01"),
    ):
        for dist in DISTS:
            cases.append(
                Case(
                    f"{name}_{dist}",
                    partial(_anchor_pair, anchor),
                    min_days=lo,
                    max_days=hi,
                    distribution=dist,
                    expect_error=None if name.endswith("_wide") else True,
                )
            )

    # Row numbering.
    n_main = 2000
    for off in (65_536, 2**32, 2**63 - 1 - n_main):
        cases.append(Case(f"row_offset_{off}", _iso_main, row_offset=off, admitted=True))
    cases.append(Case("row_offset_past_u64", _iso_main, row_offset=2**64 - 10, expect_error=True))
    cases.append(
        Case(
            "positions_sparse",
            _iso_main,
            positions=lambda n: [3 * k + (k % 7) for k in range(n)],
            admitted=True,
        )
    )
    cases.append(
        Case(
            "positions_big",
            _iso_main,
            positions=lambda n: [2**40 + 7 + 5 * k for k in range(n)],
            admitted=True,
        )
    )
    cases.append(
        Case(
            "positions_negative",
            _iso_main,
            positions=lambda n: [k if k != 41 else -1 for k in range(n)],
            expect_error=True,
        )
    )
    cases.append(
        Case(
            "positions_shorter",
            _iso_main,
            positions=lambda n: list(range(n - 1)),
            expect_error=True,
        )
    )
    cases.append(
        Case(
            "positions_longer",
            _iso_main,
            positions=lambda n: list(range(n + 1)),
            expect_error=True,
        )
    )

    # Seeds and namespaces.
    cases.append(
        Case("namespace_empty_all_null", lambda: _obj([None, pd.NaT, pd.NA]), namespace="")
    )
    cases.append(
        Case(
            "namespace_empty_non_null",
            lambda: _obj([None, "2000-01-01"]),
            namespace="",
            expect_error=True,
        )
    )
    cases.append(Case("namespace_other", _iso_main, namespace="windowed_date/other", admitted=True))
    cases.append(
        Case("seed_wrong_length", lambda: _obj(["2000-01-01"]), seed=b"abc", expect_error=True)
    )
    cases.append(Case("empty_batch", lambda: _obj([])))
    cases.append(Case("all_null_batch", lambda: _obj([None, np.nan, pd.NA, pd.NaT])))

    # Anchor shapes.
    for kind in ("date", "datetime", "timestamp"):
        for dist in DISTS:
            cases.append(
                Case(
                    f"typed_{kind}_{dist}",
                    partial(_typed, kind),
                    distribution=dist,
                    admitted=True,
                )
            )
    for dist in DISTS:
        cases.append(Case(f"datetime64_{dist}", _dt64, distribution=dist, admitted=True))
    cases.append(
        Case(
            "datetime64_positions",
            _dt64,
            positions=lambda n: [2 * k + 1 for k in range(n)],
            admitted=True,
        )
    )
    cases.append(
        Case("date_subclass", lambda: _obj([MyDate(2000, 1, 1), MyDate(2001, 2, 3), None]))
    )
    cases.append(
        Case(
            "mixed_str_and_date",
            lambda: _obj(["2000-01-01", dt.date(2001, 2, 3), None, "1999-12-31"]),
        )
    )
    cases.append(
        Case(
            "mixed_date_and_datetime",
            lambda: _obj([dt.date(2000, 1, 1), dt.datetime(2001, 2, 3, 4, 5)]),
        )
    )
    cases.append(
        Case(
            "mixed_timestamp_and_datetime",
            lambda: _obj([pd.Timestamp("2000-01-01"), dt.datetime(2001, 2, 3, 4, 5)]),
        )
    )
    cases.append(
        Case(
            "tz_aware_timestamp",
            lambda: _obj(["2000-01-01"] * 4 + [pd.Timestamp("2000-01-01", tz="UTC")]),
            expect_error=True,
        )
    )
    cases.append(
        Case(
            "tz_aware_datetime",
            lambda: _obj([dt.datetime(2000, 1, 1)] * 4 + [dt.datetime(2000, 1, 1, tzinfo=_UTC)]),
            expect_error=True,
        )
    )
    cases.append(
        Case(
            "date_out_of_range",
            lambda: _obj([dt.date(2000, 1, 1)] * 4 + [dt.date(9999, 12, 31)]),
            expect_error=True,
        )
    )
    cases.append(
        Case(
            "date_below_range",
            lambda: _obj([dt.date(2000, 1, 1)] * 4 + [dt.date(1, 1, 1)]),
            expect_error=True,
        )
    )
    cases.append(
        Case(
            "date_below_supported_min",
            lambda: _obj([dt.date(2000, 1, 1)] * 4 + [dt.date(1650, 1, 1)]),
            expect_error=True,
        )
    )

    # Error cases: each at a non-first row after good rows.
    bad_cells: list[tuple[str, Any]] = [
        ("bad_grammar_slash", "2000/01/01"),
        ("bad_grammar_text", "yesterday"),
        ("empty_string", ""),
        ("nat_string", "NaT"),
        ("zone_z", "2000-01-01T00:00:00Z"),
        ("zone_offset", "2000-01-01T00:00:00+02:00"),
        ("int_cell", 5),
        ("float_cell", 1.5),
        ("bool_cell", True),
        ("bytes_cell", b"2000-01-01"),
        ("numpy_nat", np.datetime64("NaT")),
        ("decimal_nan", decimal.Decimal("NaN")),
        ("below_range", "1500-01-01"),
        ("above_range", "2300-01-01"),
        ("year_zero_one", "0001-01-01"),
        ("invalid_calendar", "2024-02-30"),
        ("invalid_month", "2024-13-01"),
        ("invalid_day", "2024-01-32"),
        ("hour_24", "2024-01-01T24:00"),
        ("hour_25", "2024-01-01T25:00"),
        ("minute_60", "2024-01-01T10:60"),
        ("second_60", "2024-01-01T23:59:60"),
        ("leading_space", " 2000-01-01"),
        ("trailing_newline", "2000-01-01\n"),
        ("non_ascii_digits", "\uff12\uff10\uff10\uff10-01-01"),
    ]
    for name, bad in bad_cells:
        cases.append(Case(f"err_{name}", partial(_err_series, bad), expect_error=True))
    cases.append(
        Case(
            "err_result_past_max",
            lambda: _obj(["2001-01-01", "2002-01-01", "2200-12-30", "2003-01-01"]),
            min_days=5,
            max_days=10,
            expect_error=True,
        )
    )
    cases.append(
        Case(
            "err_result_below_min",
            lambda: _obj(["2001-01-01", "1700-01-02", "2003-01-01"]),
            min_days=-10,
            max_days=-5,
            expect_error=True,
        )
    )
    cases.append(
        Case(
            "err_two_bad_rows",
            lambda: _obj(["2001-01-01", "2024-02-30", "yesterday"]),
            expect_error=True,
        )
    )
    return cases


def _dt64_series(*values: str, tz: str | None = None) -> pd.Series:
    return pd.Series(pd.to_datetime(list(values), utc=tz is not None))


def build_range_cases() -> list[Case]:
    """Anchors outside the supported range whose offset returns them into it, on both edges.

    Kept apart from `build_cases` so the pinned base digest does not move. Every shape of anchor
    is covered, because each input class has its own parse path.
    """
    low, high = "1699-12-31", "2201-01-01"
    shapes: dict[str, Callable[[str], pd.Series]] = {
        "str": lambda v: _obj([v]),
        "date": lambda v: _obj([dt.date.fromisoformat(v)]),
        "datetime": lambda v: _obj([dt.datetime.fromisoformat(v)]),
        "timestamp": lambda v: _obj([pd.Timestamp(v)]),
        "dt64": lambda v: _dt64_series(v),
    }
    cases: list[Case] = []
    for shape, make in shapes.items():
        for dist in DISTS:
            cases.append(
                Case(
                    f"range_{shape}_below_{dist}",
                    partial(make, low),
                    min_days=1,
                    max_days=1,
                    distribution=dist,
                    expect_error=True,
                )
            )
            cases.append(
                Case(
                    f"range_{shape}_above_{dist}",
                    partial(make, high),
                    min_days=-1,
                    max_days=-1,
                    distribution=dist,
                    expect_error=True,
                )
            )
        # The nearest anchors that are still inside the range keep working.
        cases.append(
            Case(f"range_{shape}_edge_in_low", partial(make, "1700-01-01"), min_days=0, max_days=0)
        )
        cases.append(
            Case(f"range_{shape}_edge_in_high", partial(make, "2200-12-31"), min_days=0, max_days=0)
        )
    cases.append(
        Case(
            "range_dt64_mixed_rows",
            lambda: _dt64_series("2000-01-01", "1699-12-31", "2001-01-01"),
            min_days=1,
            max_days=1,
            expect_error=True,
        )
    )
    cases.append(
        Case(
            "range_dt64_tz_aware",
            lambda: _dt64_series("2000-01-01", tz="UTC"),
            expect_error=True,
        )
    )
    return cases


Outcome = tuple[Any, ...]


def outcome(fn: Callable[..., list[str | None]], case: Case) -> Outcome:
    """('ok', list) or ('err', type name, message, no_cause_no_context)."""
    df = case.frame()
    try:
        out = fn(
            case.config(),
            df,
            case.seed,
            case.namespace,
            row_offset=case.row_offset,
            positions=case.pos(len(df)),
        )
    except Exception as exc:
        no_chain = exc.__cause__ is None and exc.__context__ is None
        return ("err", type(exc).__name__, str(exc), no_chain)
    return ("ok", out)


def corpus_digest(fn: Callable[..., list[str | None]]) -> str:
    h = hashlib.sha256()
    for case in build_cases():
        h.update(repr((case.name, outcome(fn, case))).encode())
    return h.hexdigest()
