"""PM-1 routes: every post-scan path reaches one comparison authority, pinned per fixture.

Each fixture names its target column `v` (configured `hash`), the policy row the target must
get, and a healthy neighbor `n` that was masked and must keep its own row. The expectations are
written out here, never computed with the production scan. Synthetic values only; no assertion
message carries a cell value. Plan: docs/plans/2026-11-27-pm1-comparison-redesign.md.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.verification.postmask import run_post_mask, run_post_mask_tables
from decoy_engine.verification.postmask._stream_input import from_table
from decoy_engine.verification.postmask.policy_validation import check_policy_validation
from decoy_engine.verification.postmask.runner import MEMORY_LIMIT

ROWS = 64
CONFIG = {
    "version": 2,
    "tables": [
        {
            "name": "t",
            "columns": [{"name": "v", "strategy": "hash"}, {"name": "n", "strategy": "hash"}],
        }
    ],
}
NEIGHBOR = ("info", ROWS, ROWS, False, "output differs from source as expected.")
UNCHANGED = (
    "fail",
    ROWS,
    ROWS,
    True,
    "strategy 'hash' was configured but the output is byte-identical to the source. "
    "The mask may not have fired.",
)
REFUSED = (
    "error",
    0,
    0,
    False,
    "could not compare source vs output for column 'v': CellNotComparableError (see job log). "
    "Policy validation did not conclude for this column.",
)


def _col(cells: list[object]) -> pd.Series:
    arr = np.empty(len(cells), dtype=object)
    for i, cell in enumerate(cells):
        arr[i] = cell
    # dtype=object: pandas would otherwise infer a temporal dtype and convert the cells.
    return pd.Series(arr, dtype=object)


def _frames(src: list[object], out: list[object]) -> tuple[pd.DataFrame, pd.DataFrame]:
    source = pd.DataFrame({"v": _col(src), "n": [f"src{i}" for i in range(ROWS)]})
    output = pd.DataFrame({"v": _col(out), "n": [f"out{i}" for i in range(ROWS)]})
    return source, output


def _record() -> np.void:
    # A marker value, so a rendered record would show in the report text.
    arr = np.full(2, (9917, 9917.5), dtype=[("a", "i4"), ("b", "f8")])
    arr.flags.writeable = False
    return arr[0]


def _collided(i: int, reverse: bool) -> set[int]:
    # i and i + 8 share a slot of an 8-slot set table, so insertion order sets iteration order.
    box: set[int] = set()
    for member in (i + 8, i) if reverse else (i, i + 8):
        box.add(member)
    return box


# name: (source cells, output cells, the pinned policy row of the target)
FIXTURES: dict[str, tuple[list[object], list[object], tuple[Any, ...]]] = {
    "V1-1 dict null key vs empty dict": (
        [{"k": None} if i % 2 else {} for i in range(ROWS)],
        [{"k": None} if i % 2 else {} for i in range(ROWS)],
        ("fail", 2, 2, True, UNCHANGED[4]),
    ),
    "V1-2 decimal vs exact text": (
        [Decimal(f"{i}.25") for i in range(ROWS)],
        [f"{i}.25" for i in range(ROWS)],
        UNCHANGED,
    ),
    "V1-2 utf8 bytes vs decoded text": (
        [f"u{i}".encode() for i in range(ROWS)],
        [f"u{i}" for i in range(ROWS)],
        UNCHANGED,
    ),
    "V1-3 equal sets in another order": (
        [_collided(i, False) for i in range(ROWS)],
        [_collided(i, True) for i in range(ROWS)],
        UNCHANGED,
    ),
    "V1-3 read-only record": (
        [_record() if i == 3 else i for i in range(ROWS)],
        [_record() if i == 3 else i for i in range(ROWS)],
        REFUSED,
    ),
}


def _row(finding: dict[str, Any]) -> tuple[Any, ...]:
    return (
        finding["severity"],
        finding["source_distinct"],
        finding["output_distinct"],
        finding["bytes_identical"],
        finding["message"],
    )


def _policy(rows: list[dict[str, Any]]) -> dict[str, tuple[Any, ...]]:
    assert sorted(r["column"] for r in rows if r["table"] == "t") == ["n", "v"]
    return {r["column"]: _row(r) for r in rows if r["table"] == "t"}


def _no_marker(report: object) -> None:
    text = json.dumps(report, default=str)
    assert "9917" not in text
    assert "src1" not in text and "out1" not in text


@pytest.mark.parametrize("name", list(FIXTURES))
def test_frame_route(name: str) -> None:
    src, out, expected = FIXTURES[name]
    source, output = _frames(src, out)
    report = run_post_mask({"t": source}, {"t": output}, config=CONFIG)
    assert _policy(report["policy_validation"]) == {"v": expected, "n": NEIGHBOR}
    _no_marker(report)


@pytest.mark.parametrize("name", list(FIXTURES))
def test_standalone_route(name: str) -> None:
    src, out, expected = FIXTURES[name]
    source, output = _frames(src, out)
    findings = check_policy_validation({"t": source}, {"t": output}, CONFIG)
    rows = [f.__dict__ for f in findings]
    assert _policy(rows) == {"v": expected, "n": NEIGHBOR}
    _no_marker(rows)


# The batch route receives Arrow tables, so only the Arrow-expressible fixtures apply.
BATCH = {
    "V1-2 decimal vs exact text": (
        pa.array([Decimal(f"{i}.25") for i in range(ROWS)], pa.decimal128(10, 2)),
        pa.array([f"{i}.25" for i in range(ROWS)], pa.string()),
    ),
    "V1-2 utf8 bytes vs decoded text": (
        pa.array([f"u{i}".encode() for i in range(ROWS)], pa.binary()),
        pa.array([f"u{i}" for i in range(ROWS)], pa.string()),
    ),
}


@pytest.mark.parametrize("name", list(BATCH))
def test_batch_route(name: str, tmp_path: Path) -> None:
    src_v, out_v = BATCH[name]
    source = pa.table({"v": src_v, "n": [f"src{i}" for i in range(ROWS)]})
    output = pa.table({"v": out_v, "n": [f"out{i}" for i in range(ROWS)]})
    report = run_post_mask_tables(
        {"t": from_table("t", source)},
        {"t": from_table("t", output)},
        config=CONFIG,
        keys=[],
        scratch=tmp_path,
        memory_limit=MEMORY_LIMIT,
    )
    assert _policy(report["policy_validation"]) == {"v": UNCHANGED, "n": NEIGHBOR}
    _no_marker(report)


def test_frame_route_refuses_a_cycle_before_any_conversion() -> None:
    """Run alone in the red check: Arrow crashes the interpreter on a cyclic list."""
    loop: list[object] = []
    loop.append(loop)
    source, output = _frames([loop if i == 3 else i for i in range(ROWS)], list(range(ROWS)))
    report = run_post_mask({"t": source}, {"t": output}, config=CONFIG)
    # Only the source is refused; the output's own distinct count stands.
    cycle = ("error", 0, ROWS, False, REFUSED[4])
    assert _policy(report["policy_validation"]) == {"v": cycle, "n": NEIGHBOR}
    _no_marker(report)
