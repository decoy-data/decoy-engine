"""DATE-SHIFT-TYPED T9: the typed cases S1 keeps on the oracle, each with its coded reason.

`group_by`, `when:`, `preserve_values` and a `date64` resident under a `DATE` shape stay off the
native routes. The chunked route names the code in its reroute reason and its output equals the
forced-oracle run; the unified slice runs no native `date_shift` node and equals the full-frame
oracle. The admitted case is the control for the native half.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import run_pipeline
from decoy_engine.execution._sequential_native_ops import SEQ_DATE_SHIFT_DISPOSITION_KEY
from tests.native._b8_support import (
    FORCE,
    assert_same_as_oracle,
    identical,
    run_one,
    run_pair,
)
from tests.native._chunked_entry_support import (
    NEEDS_COMPANION,
    TABLE,
    key_provider,
    make_config,
    split,
)
from tests.native._date_shift_typed_support import with_parquet_sources

pytestmark = NEEDS_COMPANION

NS = "ns_t9"
DATES = [None if i % 7 == 3 else dt.date(2001, 1, 1) + dt.timedelta(days=53 * i) for i in range(40)]


def _ds(**cfg: Any) -> dict[str, Any]:
    config = {"min_days": -20, "max_days": 20, **cfg}
    return {"name": "d", "strategy": "date_shift", "namespace": NS, "provider_config": config}


DATE32 = pa.date32()


def _table(typ: pa.DataType = DATE32) -> pa.Table:
    return pa.table(
        {
            "d": pa.array(DATES, typ),
            "g": pa.array([f"g{i % 3}" for i in range(len(DATES))]),
            "p": pa.array(list(range(len(DATES))), pa.int64()),
        }
    )


_PASS = [{"name": "g", "strategy": "passthrough"}, {"name": "p", "strategy": "passthrough"}]

# case -> (date_shift column, source type, reason the chunked route names)
CASES: dict[str, tuple[dict[str, Any], pa.DataType, str]] = {
    # The chunked route reports a config-gate decline as its fallback policy, as for text.
    "group_by": (_ds(group_by="g"), pa.date32(), "fallback_policy_not_native:d:python_only"),
    "preserve_values": (
        _ds(preserve_values=["2001-02-23"]),
        pa.date32(),
        "date_shift_typed_preserve_not_native:d",
    ),
    "date64": (_ds(), pa.date64(), "date_shift_typed_type_not_native:d:date64[ms]"),
}


def _unified(columns: list[dict[str, Any]], table: pa.Table, unified: bool, tmp: Path) -> Any:
    return run_pipeline(
        with_parquet_sources(make_config(columns), {TABLE: table}, tmp),
        {TABLE: table},
        engine_version="t9",
        key_provider=key_provider(),
        execution_mode="full_frame",
        auto_chunk=False,
        unified_slice_enabled=unified,
    )


def _sequential(columns: list[dict[str, Any]], table: pa.Table, tmp: Path) -> Any:
    """`table` as the FK child of a one-key parent: the sequential route needs a relationship."""
    n = table.num_rows
    tables = {
        "parent": pa.table({"id": pa.array([f"k{i}" for i in range(n)])}),
        TABLE: table.append_column("pid", pa.array([f"k{i}" for i in range(n)])),
    }
    key = {"strategy": "hash", "namespace": "fk_t9"}
    config = make_config(
        [*columns, {"name": "pid", **key}],
        extra_tables=[{"name": "parent", "columns": [{"name": "id", **key}]}],
        relationships=[
            {
                "parent": {"table": "parent", "columns": ["id"]},
                "children": [{"table": TABLE, "columns": ["pid"]}],
                "orphan_policy": "preserve",
                "namespace": "fk_t9",
            }
        ],
    )
    return run_pipeline(
        with_parquet_sources(config, tables, tmp),
        tables,
        engine_version="t9",
        key_provider=key_provider(),
        execution_mode="sequential",
        auto_chunk=False,
    )


def _sequential_backends(result: Any) -> list[tuple[str, str | None]]:
    entries = result.quality_metrics.get(SEQ_DATE_SHIFT_DISPOSITION_KEY, [])
    return [(e["executed_backend"], e.get("reason")) for e in entries if e["column"] == "d"]


def _native_date_shift_nodes(result: Any) -> list[dict[str, Any]]:
    nodes = result.quality_metrics.get("unified_slice_activation", {}).get("nodes", {})
    return [
        n
        for n in nodes.values()
        if n["strategy"] == "date_shift" and n["executed_backend"] == "rust_companion"
    ]


@pytest.mark.parametrize("case", sorted(CASES))
def test_t9_chunked_declines_with_its_code_and_equals_the_oracle(case: str) -> None:
    column, typ, code = CASES[case]
    native, forced = run_pair([column, *_PASS], split(_table(typ), 15))
    assert code in (native.ev[0].reroute_reason or ""), native.ev[0].reroute_reason
    if case != "group_by":
        assert_same_as_oracle(native, forced, expect_native=False)
        return
    # A group_by reads its sibling through pandas on both legs, which the shared helper
    # forbids, so compare the bytes and the vault directly.
    assert native.ev[0].native_admitted is False
    for got, want in zip(native.out, forced.out, strict=True):
        assert identical(got, want.drop_columns([FORCE]))
    assert native.vault == forced.vault


@pytest.mark.parametrize("case", sorted(CASES))
def test_t9_unified_runs_no_native_date_shift_and_equals_the_oracle(
    case: str, tmp_path: Path
) -> None:
    column, typ, _ = CASES[case]
    table = _table(typ)
    on = _unified([column, *_PASS], table, True, tmp_path)
    off = _unified([column, *_PASS], table, False, tmp_path)
    assert _native_date_shift_nodes(on) == []
    assert on.outputs[TABLE].equals(off.outputs[TABLE])


def test_t9_a_when_predicate_keeps_the_typed_column_off_native(tmp_path: Path) -> None:
    column = {**_ds(), "when": "p > 5"}
    run = run_one(make_config([column, *_PASS]), split(_table(), 15))
    assert run.ev[0].native_admitted is False, run.ev[0]
    table = _table()
    on = _unified([column, *_PASS], table, True, tmp_path)
    off = _unified([column, *_PASS], table, False, tmp_path)
    assert _native_date_shift_nodes(on) == []
    assert on.outputs[TABLE].equals(off.outputs[TABLE])
    seq = _sequential([column, *_PASS], table, tmp_path)
    [(backend, reason)] = _sequential_backends(seq)
    assert (backend, reason) == ("python_scalar", "when_predicate_not_native:d")
    assert seq.outputs[TABLE].drop_columns(["pid"]).equals(off.outputs[TABLE])


def test_t9_control_the_admitted_typed_column_runs_native_on_both_routes(tmp_path: Path) -> None:
    native, forced = run_pair([_ds(), *_PASS], split(_table(), 15))
    assert_same_as_oracle(native, forced)
    table = _table()
    on = _unified([_ds(), *_PASS], table, True, tmp_path)
    off = _unified([_ds(), *_PASS], table, False, tmp_path)
    assert len(_native_date_shift_nodes(on)) == 1
    assert on.outputs[TABLE].equals(off.outputs[TABLE])
    seq = _sequential([_ds(), *_PASS], table, tmp_path)
    assert [b for b, _ in _sequential_backends(seq)] == ["rust_companion"]
