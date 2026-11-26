"""Acceptance test 0 (plan 2026-10-01-dispatcher-auto-chunk, revision 5): the
output-delta record between today's chunked lane, the dispatcher lane and the
forced full frame, for every planner-admitted source shape.

The recorded fixture (`auto_chunk_fixtures/output_delta.json`) holds each cell's
output column set, per-column type, field nullability, field-metadata presence
and schema-metadata keys, or the exception type and code. The test does two
things against the live code:

1. The live record equals the fixture, so a pyarrow or pandas upgrade that
   changes today's lane, or a B1 change, surfaces as a fixture diff for review.
2. Every cell where the dispatcher lane differs from today's lane is one of
   guarantee 3's differences (b) to (e), and nothing else. The set of allowed
   differences is closed: do not add to it without a new plan gate.

   (e) is the one failure-to-success change (PREFLIGHT-ARROW-PROFILE S1b, plan
   AT-1/2, AT-7 and Amendment 1): a `time64[ns]` source with sub-microsecond
   values that the Parquet profile recovery accepts. Today's lane raises the coded
   `full_frame_value_unrepresentable`; the dispatcher lane profiles, routes and
   keeps `x` as the source column. It covers exactly the four cell ids in
   `RECOVERED_TIME64_CELLS`, with live checks of the values, the masked companions
   and today's exception.

The dispatcher lane here is B1's `run_mask_chunked` called as plan Design 4
calls it (`_auto_chunk_support.b1_as_the_lane`), so this module passes before
and after the B2 implementation. Cells run with `use_byte_estimate_routing=False`
because default byte-estimate routing crashes on date/time columns on main (plan
Known issues); re-record them by review when that defect is fixed.

Regenerate the fixture with `DECOY_RECORD_OUTPUT_DELTA=1` in the companion venv.
The recording runs inside the first test's setup, after the shared throwaway secret,
so keyed cells record the same way they run.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.execution._errors import ExecutionError
from tests.unit.execution import _auto_chunk_matrix as matrix
from tests.unit.execution import _auto_chunk_support as support

FIXTURE = Path(__file__).parent / "auto_chunk_fixtures" / "output_delta.json"
STRING_OUTPUT_COLUMNS = ("h", "r")
RECOVERED_CODE = "full_frame_value_unrepresentable"
# Guarantee 3 (e): named cell by cell, never matched by pattern. The `date32` cells hold
# representable dates and get no exception.
RECOVERED_TIME64_CELLS = frozenset(
    f"time64_ns_nonaligned|{role}|{nulls}"
    for role in ("pass", "uncfg")
    for nulls in ("none", "mixed")
)
CONTROL_TYPE = "time64_ns_aligned"


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


_recorded = False


@pytest.fixture(autouse=True)
def _maybe_record(
    _default_throwaway_secret: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Record once per process. It depends on the shared secret fixture so keyed
    cells see the same environment as the tests that read the record."""
    global _recorded
    if os.environ.get("DECOY_RECORD_OUTPUT_DELTA") != "1" or _recorded:
        return
    _recorded = True
    path = str(tmp_path_factory.mktemp("record") / "src.parquet")
    record = {cell: matrix.record_cell(cell, monkeypatch, path) for cell in matrix.cell_ids()}
    FIXTURE.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")


def test_fixture_covers_exactly_the_matrix() -> None:
    assert sorted(_fixture()) == sorted(matrix.cell_ids())


def _check_masked_column(
    name: str, d: pa.Table, l_: pa.Table, *, string_output: bool, faker_native_all_null: bool
) -> None:
    d_field, l_field = d.schema.field(name), l_.schema.field(name)
    assert d.column(name).to_pylist() == l_.column(name).to_pylist(), f"{name}: values differ"
    assert d_field.nullable, f"{name}: masked field must be nullable"
    assert d_field.metadata is None, f"{name}: masked field must carry no field metadata"
    if string_output:
        # hash, truncate, redact: always `string`; today's lane leaves `null` only when
        # every chunk is all-null.
        assert d_field.type == pa.string()
        assert l_field.type in (pa.string(), pa.null())
    elif faker_native_all_null:
        assert d_field.type == pa.string()
        assert l_field.type in (pa.string(), pa.null())
    else:
        assert d_field.type == l_field.type, f"{name}: masked type differs from today's lane"


@pytest.mark.parametrize("route", ["native", "oracle"])
@pytest.mark.parametrize("cell", matrix.cell_ids())
def test_cell_matches_record_and_differences_are_guarantee_3(
    cell: str, route: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if route == "native" and not support.COMPANION_PRESENT:
        pytest.skip("compiled companion not installed; the companion-present job covers this")
    src, lanes = matrix.run_cell(cell, monkeypatch, str(tmp_path / "src.parquet"))
    recorded = _fixture()[cell]
    for lane, (rec, _table) in lanes.items():
        if lane.startswith(matrix.LIVE_PREFIX):
            continue
        assert rec == recorded[lane], f"{cell}: live {lane} record differs from the fixture"
    # The shipped lane (no patch) equals the fixture lane: record and table.
    if f"disp_{route}" in lanes:
        live_rec, live = lanes[f"{matrix.LIVE_PREFIX}{route}"]
        fix_rec, fix = lanes[f"disp_{route}"]
        assert live_rec == fix_rec, f"{cell}: shipped lane record differs from disp_{route}"
        assert (live is None) == (fix is None)
        if live is not None and fix is not None:
            assert live.equals(fix, check_metadata=True), f"{cell}: shipped table differs"

    typ, role, nulls = cell.split("|")
    (l_rec, legacy), (d_rec, disp) = lanes["legacy"], lanes[f"disp_{route}"]
    if cell in RECOVERED_TIME64_CELLS:
        _check_recovered_time64(cell, route, src, l_rec, legacy, d_rec, disp, tmp_path, monkeypatch)
        return
    if legacy is None or disp is None:
        # An exception on either lane must be the same exception on the other: a lane
        # change never turns a failure into a success or the reverse.
        assert legacy is None and disp is None
        assert l_rec == d_rec
        return
    assert l_rec["mode"] == "chunked", (
        f"{cell}: today's lane did not route; the cell proves nothing"
    )
    assert d_rec["mode"] == "chunked"

    # (a) same columns in the same order, same row count.
    assert disp.column_names == legacy.column_names
    assert disp.num_rows == legacy.num_rows == support.ROWS

    # (d) no schema metadata.
    assert disp.schema.metadata is None

    string_output_x = role in matrix.STRING_OUTPUT_ROLES
    faker_x = role == "faker"
    # Guarantee 3 (b)'s route-dependent cells: an all-null Faker source outputs `string` on the
    # dispatcher lane while today's lane leaves `null`. For a string source only the native leg
    # pins (C5b-i); C5c-ii pins a bool/int/uint source on BOTH dispatcher legs, so `bool` (the
    # only all-null numeric faker cell -- int/uint are non-nullable in this matrix) is pinned on
    # the oracle route too.
    faker_native_all_null = (
        faker_x
        and nulls == "all"
        and ((route == "native" and typ in ("string", "large_string")) or typ == "bool")
    )
    for name in disp.column_names:
        if name in STRING_OUTPUT_COLUMNS or (name == "x" and string_output_x):
            _check_masked_column(
                name, disp, legacy, string_output=True, faker_native_all_null=False
            )
        elif name == "x" and faker_x:
            _check_masked_column(
                name, disp, legacy, string_output=False, faker_native_all_null=faker_native_all_null
            )
        else:
            # (c) a passthrough column present in today's output equals the source exactly, except
            # that O3 narrows a `large_string` source column to `string`.
            want_field, want = src.schema.field(name), src.column(name)
            if pa.types.is_large_string(want_field.type):
                want_field, want = want_field.with_type(pa.string()), want.cast(pa.string())
            assert disp.column(name).equals(want), f"{name}: passthrough values/type"
            assert disp.schema.field(name).equals(want_field, check_metadata=True)


def _check_recovered_time64(
    cell: str,
    route: str,
    src: pa.Table,
    l_rec: dict[str, Any],
    legacy: pa.Table | None,
    d_rec: dict[str, Any],
    disp: pa.Table | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guarantee 3 (e), checked on the live run and not on the record alone."""
    assert legacy is None, f"{cell}: today's lane no longer raises; (e) does not apply"
    assert l_rec == {"exc": "ExecutionError", "code": RECOVERED_CODE}
    assert disp is not None, f"{cell}: dispatcher lane must succeed on {route}"
    assert d_rec["mode"] == "chunked"
    assert disp.column_names == src.column_names
    assert disp.num_rows == src.num_rows

    # `x` keeps the source's Arrow type and exact values. `equals` compares the int64
    # nanoseconds, where `to_pylist` would round them to microseconds.
    want = src.column("x")
    assert disp.schema.field("x").type == src.schema.field("x").type
    assert disp.column("x").equals(want), "x values differ from the source"

    # The masked companions equal a representable control's outputs, so a lane that
    # copies a raw source value into `h` or `r` fails.
    control = matrix.run_cell(
        cell.replace("time64_ns_nonaligned", CONTROL_TYPE),
        monkeypatch,
        str(tmp_path / "ctl.parquet"),
    )[1][f"disp_{route}"][1]
    assert control is not None, "the representable control must succeed"
    for name in STRING_OUTPUT_COLUMNS:
        assert disp.column(name).equals(control.column(name)), f"{name}: differs from control"
        assert disp.schema.field(name).equals(control.schema.field(name), check_metadata=True)

    # Today's lane, run live: coded, value-free, and no exception context.
    cfg, _ = matrix.build_source(cell, str(tmp_path / "legacy.parquet"))
    with pytest.raises(ExecutionError) as caught:
        support.run_legacy(cfg, src)
    exc = caught.value
    assert exc.code == RECOVERED_CODE
    assert exc.__cause__ is None
    assert exc.__context__ is None
    text = str(exc)
    for value in want.cast(pa.int64()).drop_null().to_pylist():
        assert str(value) not in text
    for value in src.column("h").to_pylist() + src.column("r").to_pylist():
        assert value not in text
