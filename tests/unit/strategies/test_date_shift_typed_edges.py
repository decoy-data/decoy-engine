"""COLUMN-SHAPE E1b edges: DST, date range, output types, the handler guards and a bad format.

These sit beside `test_date_shift_typed.py` and reuse its fixtures. Each test names the mutation
it kills in its docstring.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine import run_mask_chunked, run_mask_pipeline_chunked
from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.errors import RowErrorsFailedError
from decoy_engine.plan import PlanCompileError, run_config_only_checks
from decoy_engine.transforms.date_preserve import preserve_config_problem
from tests.native._chunked_entry_support import key_provider
from tests.unit.strategies.test_date_shift_typed import (
    DATES,
    NEEDS_FORMAT,
    ROUTES,
    _cfg,
    _compile,
    _ctx,
    _run,
    _seed,
    _table,
    run_sequential_typed,
)

NY = "America/New_York"


def _local(year: int, month: int, day: int, hour: int, minute: int, *, dst: bool) -> dt.datetime:
    """A New York wall time written with an explicit DST flag (it may be ambiguous)."""
    naive = dt.datetime(year, month, day, hour, minute)
    return naive.replace(tzinfo=ZoneInfo(NY), fold=0 if dst else 1)


@pytest.mark.parametrize("route", ["full_frame", "chunked"])
@pytest.mark.parametrize(
    ("source", "days", "wall", "offset_hours"),
    [
        (_local(2024, 3, 5, 10, 0, dst=False), 10, dt.datetime(2024, 3, 15, 10, 0), -4),
        (_local(2024, 10, 30, 10, 0, dst=True), 10, dt.datetime(2024, 11, 9, 10, 0), -5),
        # the shifted local time happens twice: the source row's DST flag picks the first or second
        (_local(2024, 10, 30, 1, 30, dst=True), 4, dt.datetime(2024, 11, 3, 1, 30), -4),
        (_local(2025, 1, 1, 1, 30, dst=False), 305, dt.datetime(2025, 11, 2, 1, 30), -5),
        # the shifted local time does not exist: it moves forward past the gap
        (_local(2024, 3, 7, 2, 30, dst=False), 3, dt.datetime(2024, 3, 10, 3, 0), -4),
    ],
)
def test_timestamp_tz_keeps_wall_clock_across_dst(
    tmp_path: Path, route: str, source: dt.datetime, days: int, wall: dt.datetime, offset_hours: int
) -> None:
    """Kills: shifting by `pd.to_timedelta(shifts, unit="D")` on the zoned value (24 hour steps)."""
    typ = pa.timestamp("us", tz=NY)
    table = _table([source], typ)
    cfg = _cfg(tmp_path, table, provider_config={"min_days": days, "max_days": days})
    got = _run(cfg, table, route).column("d").to_pylist()[0]
    local = got.astimezone(ZoneInfo(NY))
    assert local.replace(tzinfo=None) == wall
    assert local.utcoffset() == dt.timedelta(hours=offset_hours)


@pytest.mark.parametrize("route", ROUTES)
def test_far_dates_shift_without_pandas_bounds(tmp_path: Path, route: str) -> None:
    """Kills: running a typed date through `pd.to_datetime`, where 9999-12-31 becomes NaT."""
    values = [dt.date(9999, 12, 31), dt.date(9999, 6, 1), None, dt.date(2024, 1, 15)]
    table = _table(values, pa.date32())
    cfg = _cfg(tmp_path, table, provider_config={"min_days": -30, "max_days": -1})
    got = _run(cfg, table, route).column("d").to_pylist()
    assert got[2] is None
    for before, after in zip(values, got, strict=True):
        if before is not None:
            assert 1 <= (before - after).days <= 30


def test_shift_past_the_last_year_is_a_row_error(tmp_path: Path) -> None:
    """A date that cannot move inside years 1 to 9999 fails the run, it never keeps its value."""
    table = _table([dt.date(9999, 12, 31)], pa.date32())
    cfg = _cfg(tmp_path, table, provider_config={"min_days": 5, "max_days": 30})
    with pytest.raises(RowErrorsFailedError):
        _run(cfg, table, "full_frame")


@pytest.mark.parametrize("route", ROUTES)
def test_date64_source_keeps_date64(tmp_path: Path, route: str) -> None:
    """Kills: dropping the restore of the source type where the frame becomes a table."""
    table = _table(DATES, pa.date64())
    out = _run(_cfg(tmp_path, table), table, route)
    assert out.schema.field("d").type == pa.date64()


def test_sequential_route_keeps_date64(tmp_path: Path) -> None:
    out = run_sequential_typed(tmp_path, pa.date64())
    assert out.schema.field("d").type == pa.date64()


@pytest.mark.parametrize("entry", ["pipeline", "native"])
def test_all_null_chunk_keeps_the_source_type(tmp_path: Path, entry: str) -> None:
    """Kills: leaving a null-typed column in a chunk whose cells are all null."""
    typ = pa.date32()
    blank = _table([None, None], typ)
    full = _table([dt.date(2024, 1, 15), dt.date(2019, 9, 1)], typ)
    cfg = _cfg(tmp_path, full)
    chunks = [blank, full]
    if entry == "pipeline":
        out = run_mask_pipeline_chunked(
            cfg,
            chunks,
            table="t",
            engine_version="e1b",
            source_schema=full.schema,
            key_provider=key_provider(),
        )
    else:
        out = run_mask_chunked(
            cfg, chunks, table="t", engine_version="e1b", key_provider=key_provider()
        )
    written = list(out)
    assert len(written) == 2
    assert [t.schema.field("d").type for t in written] == [typ, typ]
    pa.concat_tables(written)  # one schema across chunks


def _frame(values: list[Any]) -> pd.DataFrame:
    return pd.DataFrame({"d": values})


def test_naive_datetime_digests_as_its_calendar_date() -> None:
    """Kills: dropping the datetime-to-date step, so a timestamp digests as its full text."""
    from decoy_engine.execution._strategies._date_shift import DateShiftStrategyHandler

    days = [dt.date(2024, 1, 15), dt.date(2019, 9, 1), dt.date(2031, 7, 19), dt.date(1987, 3, 11)]
    seed = _seed()
    wide = (("min_days", -400), ("max_days", 400))
    typed = dataclasses.replace(seed, provider_config=wide)
    text = dataclasses.replace(seed, provider_config=(*wide, ("date_format", "%Y-%m-%d")))
    handler = DateShiftStrategyHandler()
    stamped = _frame(pd.to_datetime([f"{d.isoformat()} 13:45:30" for d in days]).to_numpy())
    got, _ = handler.run(stamped, "d", typed, _ctx({("t", "d"): ColumnShape.DATE}))
    iso = _frame([d.isoformat() for d in days])
    ref, _ = handler.run(iso, "d", text, _ctx({}))
    shifted = [dt.date.fromisoformat(s) for s in ref["d"]]
    assert list(got["d"]) == shifted
    assert shifted != days


class _Seam:
    """A sequential-native seam that counts the columns it is asked about."""

    def __init__(self) -> None:
        self.asked = 0

    def date_shift_column(self, *args: Any, **kwargs: Any) -> None:
        self.asked += 1


def test_a_typed_column_never_reaches_the_sequential_native_seam() -> None:
    """Kills: dropping the shape guard before `seq.date_shift_column`."""
    from decoy_engine.execution._strategies._date_shift import DateShiftStrategyHandler

    seed = _seed()
    with_format = dataclasses.replace(
        seed, provider_config=(*seed.provider_config, ("date_format", "%Y-%m-%d"))
    )
    typed_seam, text_seam = _Seam(), _Seam()
    typed_ctx = _ctx({("t", "d"): ColumnShape.DATE})
    object.__setattr__(typed_ctx, "seq_native", typed_seam)
    DateShiftStrategyHandler().run(_frame([dt.date(2024, 1, 15)]), "d", seed, typed_ctx)
    assert typed_seam.asked == 0
    text_ctx = _ctx({})
    object.__setattr__(text_ctx, "seq_native", text_seam)
    DateShiftStrategyHandler().run(_frame(["2024-01-15"]), "d", with_format, text_ctx)
    assert text_seam.asked == 1  # the seam is still asked about a text column


@pytest.mark.parametrize("shape", list(ColumnShape))
def test_non_string_date_format_refused_whatever_the_shape(shape: ColumnShape) -> None:
    """A date_format that is not text is refused at compile on every shape, never ignored."""
    cfg = {"preserve_values": ["2024-02-03"], "date_format": 5}
    problem = preserve_config_problem(cfg, shape)
    assert problem is not None and "date_format" in problem


def test_non_string_date_format_refused_on_a_typed_column(tmp_path: Path) -> None:
    table = _table(DATES, pa.date32())
    cfg = _cfg(tmp_path, table, provider_config={"date_format": 5})
    with pytest.raises(PlanCompileError) as exc:
        run_config_only_checks(cfg)  # the shape is not known yet, the value is not text
    assert exc.value.code == NEEDS_FORMAT
    with pytest.raises(PlanCompileError) as exc2:
        _compile(cfg, table)  # a date32 column, which needs no format, still refuses a bad one
    assert exc2.value.code == NEEDS_FORMAT


@pytest.mark.parametrize("route", ["full_frame", "chunked", "sequential"])
def test_declared_date_column_keeps_its_text_output(route: str) -> None:
    """Kills: listing an F06-declared date column as native, which writes a date, not text."""
    from tests.acceptance._f06_support import (
        ISO_DATE,
        column,
        config,
        run,
        text_table,
        write_csv,
    )

    rows = ["2026-01-01", "2026-03-04", "1999-12-31"]
    window = {"min_days": -400, "max_days": 400}
    declared = column(
        "d",
        "date_shift",
        namespace="d",
        logical_type="date",
        parse_format=ISO_DATE,
        error_policy="fail",
        provider_config=window,
    )
    plain = column(
        "d", "date_shift", namespace="d", provider_config={**window, "date_format": "%Y-%m-%d"}
    )

    def go(col: dict[str, Any], tmp: str) -> pa.Table:
        src = write_csv(Path(tmp) / "p.csv", ["d"], [[r] for r in rows])
        raw = config([col], source_path=src)
        tables = {"people": text_table(d=rows)}
        if route == "sequential":  # this route needs a parent/child edge
            ids = [f"r{i}" for i in range(len(rows))]
            psrc = write_csv(Path(tmp) / "parent.csv", ["id"], [[i] for i in ids])
            table = raw["tables"][0]
            table["columns"].insert(0, column("ref", "hash", namespace="fk"))
            raw["tables"].append(
                {"name": "parent", "columns": [column("id", "hash", namespace="fk")]}
            )
            raw["sources"]["parent"] = {**raw["sources"]["people"], "path": psrc}
            raw["targets"]["parent"] = {**raw["targets"]["people"], "path": "/dev/null.parent"}
            raw["relationships"] = [
                {
                    "parent": {"table": "parent", "columns": ["id"]},
                    "children": [{"table": "people", "columns": ["ref"]}],
                    "orphan_policy": "preserve",
                    "namespace": "fk",
                }
            ]
            tables = {"people": text_table(ref=ids, d=rows), "parent": text_table(id=ids)}
            src = write_csv(
                Path(tmp) / "p.csv", ["ref", "d"], [[i, r] for i, r in zip(ids, rows, strict=True)]
            )
            raw["sources"]["people"]["path"] = src
        return run(raw, tables, execution_mode=route, key_provider=key_provider()).outputs["people"]

    import tempfile

    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        got, legacy = go(declared, a), go(plain, b)
    assert pa.types.is_string(got.schema.field("d").type)
    assert got.column("d").to_pylist() == legacy.column("d").to_pylist() != rows


def test_mixed_batch_dst_and_fixed_offset(tmp_path: Path) -> None:
    """One column with both ambiguous choices, a gap, an ordinary time, a null and a fixed zone."""
    from decoy_engine.execution._strategies._date_shift import _shift_zoned

    ny = ZoneInfo(NY)
    cells = [
        _local(2024, 10, 30, 1, 30, dst=True),  # +4 d: 2024-11-03 01:30 twice, DST copy
        _local(2025, 1, 1, 1, 30, dst=False),  # +305 d: 2025-11-02 01:30 twice, standard copy
        _local(2024, 3, 7, 2, 30, dst=False),  # +3 d: 2024-03-10 02:30 does not exist
        _local(2024, 6, 1, 9, 15, dst=True),  # +20 d: ordinary
        None,
    ]
    days = [4, 305, 3, 20, 0]
    parsed = pd.Series(pd.to_datetime(cells, utc=True).tz_convert(NY)).astype(
        "datetime64[us, America/New_York]"
    )
    out = _shift_zoned(parsed, days)
    walls = [None if pd.isna(v) else v.tz_localize(None).to_pydatetime() for v in out]
    assert walls == [
        dt.datetime(2024, 11, 3, 1, 30),
        dt.datetime(2025, 11, 2, 1, 30),
        dt.datetime(2024, 3, 10, 3, 0),
        dt.datetime(2024, 6, 21, 9, 15),
        None,
    ]
    offsets = [None if pd.isna(v) else v.utcoffset() for v in out]
    assert offsets[:2] == [dt.timedelta(hours=-4), dt.timedelta(hours=-5)]
    assert ny.key == NY
    fixed = pd.Series(pd.to_datetime(["2024-03-05 10:00", None], utc=True)).dt.tz_convert(
        dt.timezone(dt.timedelta(hours=5, minutes=30))
    )
    moved = _shift_zoned(fixed, [10, 0])
    assert moved.iloc[0].tz_localize(None) == pd.Timestamp("2024-03-15 15:30")
    assert str(moved.dt.tz) == str(fixed.dt.tz) and pd.isna(moved.iloc[1])
