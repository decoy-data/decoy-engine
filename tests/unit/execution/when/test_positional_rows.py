"""Rows travel by position from the gate to every consumer (plan revision 2.6, I2 and D1).

The masking frame has a fresh `RangeIndex` (`_fk_keys.masking_frame`); the stored index comes
back at output assembly through the one emission helper. These tests cross both routes with
sources whose stored index is a repeated label, a stepped range, non-monotonic or a string.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution._fk_keys import masking_frame
from decoy_engine.execution.pipeline._source_types import table_from_pandas_keeping_source_types
from tests.unit.execution.when import _write_support as ws

ROUTES: dict[str, Callable[..., pa.Table]] = {
    "single": ws.run,
    "sequential": ws.run_sequential,
}

BASE = pd.DataFrame(
    {
        "email": ["a@x", "b@x", "c@x", "d@x"],
        "note": ["n0", "n1", "n2", "n3"],
        "val": [10, 20, 30, 40],
    }
)


def _dup_source() -> pa.Table:
    frame = BASE.iloc[:2].copy()
    frame.index = [7, 7]
    return pa.Table.from_pandas(frame, preserve_index=True)


def _stepped_source() -> pa.Table:
    return pa.Table.from_pandas(BASE.iloc[::2])  # default pandas range metadata, step 2


SOURCES = {"stored_dup": _dup_source, "stepped": _stepped_source}

# Captured on main at 8ee461e0f with the same fixtures and a plain `redact` on `email`:
# (field names, field types, values by column). The sequential route carries a stored index field
# (V2-LOG `SEQ-INDEX-PASSTHROUGH`); the full-frame route drops it.
FROZEN: dict[tuple[str, str], tuple[list[str], list[str], dict[str, list[Any]]]] = {
    ("stored_dup", "single"): (
        ["email", "note", "val"],
        ["string", "string", "int64"],
        {"email": ["REDACTED"] * 2, "note": ["n0", "n1"], "val": [10, 20]},
    ),
    ("stored_dup", "sequential"): (
        ["email", "note", "val", "__index_level_0__"],
        ["string", "string", "int64", "int64"],
        {
            "email": ["REDACTED"] * 2,
            "note": ["n0", "n1"],
            "val": [10, 20],
            "__index_level_0__": [7, 7],
        },
    ),
    ("stepped", "single"): (
        ["email", "note", "val"],
        ["string", "string", "int64"],
        {"email": ["REDACTED"] * 2, "note": ["n0", "n2"], "val": [10, 30]},
    ),
    ("stepped", "sequential"): (
        ["email", "note", "val"],
        ["string", "string", "int64"],
        {"email": ["REDACTED"] * 2, "note": ["n0", "n2"], "val": [10, 30]},
    ),
}


@pytest.mark.parametrize("route", sorted(ROUTES))
@pytest.mark.parametrize("source", sorted(SOURCES))
def test_emission_matches_main_for_a_stored_or_stepped_index(source: str, route: str) -> None:
    """D1. Full Arrow schema (names, order, types), values in row order and any carried index
    field equal main's output, on both routes, for a repeated label and a stepped range."""
    names, types, values = FROZEN[(source, route)]
    out = ROUTES[route](ws.plan([("email", ws.seed("redact"))]), SOURCES[source]())
    assert out.schema.names == names
    assert [str(f.type) for f in out.schema] == types
    assert {c: out.column(c).to_pylist() for c in out.column_names} == values
    assert b"pandas" in (out.schema.metadata or {})


def test_a_dropped_row_still_takes_the_rows_changed_path() -> None:
    """The kept index is put back only for a frame that is still the source's rows in order."""
    source = _dup_source()
    frame, kept = masking_frame(source, ())
    assert frame.index.equals(pd.RangeIndex(2))
    for broken in (frame.iloc[:1], frame.iloc[::-1]):
        with pytest.raises(ExecutionError) as err:
            table_from_pandas_keeping_source_types(broken, source, (), kept_index=kept)
        assert err.value.code == "output_assembly_rows_changed"


def test_masking_frame_keeps_the_stored_index_for_assembly() -> None:
    frame, kept = masking_frame(_dup_source(), ())
    assert list(kept) == [7, 7]
    assert frame.index.equals(pd.RangeIndex(2))


# ---------------------------------------------------------------------------
# F1 and the R1 sweep: every snapshot reader gives the RangeIndex run's values.
# ---------------------------------------------------------------------------

INDEXES: dict[str, list[Any] | None] = {
    "range": None,
    "duplicate": [7, 7, 8, 8],
    "non_monotonic": [3, 1, 2, 0],
    "strings": ["w", "x", "y", "z"],
}


def _readers(tmp_path: Path) -> dict[str, tuple[Any, tuple[tuple[str, ...], ...]]]:
    ref = ws.reference(tmp_path / "city.parquet", city=["C0", "C1", "C2"], state=["S0", "S1", "S2"])
    date_cfg = (
        ("max_shift_days", 30),
        ("group_by", "g"),
        ("date_format", "%Y-%m-%d"),
    )
    return {
        "when_reads_masked_column": (
            ws.plan(
                [
                    ("a_status", ws.seed("redact")),
                    ("z_target", ws.seed("redact", when="a_status == 'go'")),
                ]
            ),
            (("nm_unused",),),
        ),
        "gated_joint_mask": (
            ws.plan(
                [
                    ("a_status", ws.seed("redact")),
                    ("city", ws.joint(ref, ["city", "state"], when="a_status == 'go'")),
                ]
            ),
            (("nm_unused",),),
        ),
        "ungated_joint_mask": (
            ws.plan([("city", ws.joint(ref, ["city", "state"]))]),
            (("nm_unused",),),
        ),
        "ungated_date_shift_group_by": (
            ws.plan(
                [
                    (
                        "d",
                        ws.seed(
                            "date_shift",
                            provider_config=date_cfg,
                            namespace="nm",
                            deterministic=True,
                        ),
                    ),
                    ("g", ws.seed("redact")),
                ]
            ),
            (("d",),),
        ),
    }


def _table(index: list[Any] | None) -> pa.Table:
    frame = pd.DataFrame(
        {
            "k": ["k0", "k1", "k2", "k3"],
            "g": ["p", "q", "p", "q"],
            "d": ["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"],
            "a_status": ["go", "no", "go", "no"],
            "z_target": ["t0", "t1", "t2", "t3"],
            "city": ["c0", "c1", "c2", "c3"],
            "state": ["s0", "s1", "s2", "s3"],
        }
    )
    if index is None:
        return pa.Table.from_pandas(frame, preserve_index=False)
    frame.index = pd.Index(index)
    return pa.Table.from_pandas(frame, preserve_index=True)


@pytest.mark.parametrize("route", sorted(ROUTES))
@pytest.mark.parametrize("index", [n for n in INDEXES if n != "range"])
@pytest.mark.parametrize(
    "reader",
    [
        "when_reads_masked_column",
        "gated_joint_mask",
        "ungated_joint_mask",
        "ungated_date_shift_group_by",
    ],
)
def test_every_snapshot_reader_gives_the_range_index_values(
    reader: str, index: str, route: str, tmp_path: Path
) -> None:
    """R1 sweep. Output values equal the same rows under a `RangeIndex`, row by row, and a
    stored index field that the route carries equals the input index."""
    seed_plan, bound = _readers(tmp_path)[reader]
    bound = (("d",),) if reader.startswith("ungated_date") else (("k",),)
    run = ROUTES[route]
    want = run(seed_plan, _table(None), bound=bound)
    got = run(seed_plan, _table(INDEXES[index]), bound=bound)
    for column in want.column_names:
        assert got.column(column).to_pylist() == want.column(column).to_pylist(), column
    if "__index_level_0__" in got.column_names:
        assert got.column("__index_level_0__").to_pylist() == INDEXES[index]


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_gated_joint_mask_on_duplicate_index(route: str, tmp_path: Path) -> None:
    """F1. Two rows with stored index `[7, 7]`, `a_status` redacted first, a joint mask keyed on
    `k` and gated on `a_status == 'go'` where only the second row matches. Row 2 takes the tuple
    selected by its own source key, row 1 keeps its source values (the label lookup read both
    keys for the one gated row and raised on a length mismatch)."""
    ref = ws.reference(tmp_path / "r.parquet", city=["C0", "C1"], state=["S0", "S1"])
    seed_plan = ws.plan(
        [
            ("a_status", ws.seed("redact")),
            ("city", ws.joint(ref, ["city", "state"], when="a_status == 'go'")),
        ]
    )

    def table(index: list[int] | None) -> pa.Table:
        frame = pd.DataFrame(
            {
                "k": ["k0", "k1"],
                "a_status": ["no", "go"],
                "city": ["c0", "c1"],
                "state": ["s0", "s1"],
            }
        )
        if index is None:
            return pa.Table.from_pandas(frame, preserve_index=False)
        frame.index = pd.Index(index)
        return pa.Table.from_pandas(frame, preserve_index=True)

    run = ROUTES[route]
    want = run(seed_plan, table(None), bound=(("k",),))
    got = run(seed_plan, table([7, 7]), bound=(("k",),))
    assert got.column("city").to_pylist()[0] == "c0"
    assert got.column("city").to_pylist()[1] in {"C0", "C1"}
    for column in want.column_names:
        assert got.column(column).to_pylist() == want.column(column).to_pylist()
    if "__index_level_0__" in got.column_names:
        assert got.column("__index_level_0__").to_pylist() == [7, 7]
