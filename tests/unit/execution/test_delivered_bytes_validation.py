"""EXPECT-OFF-ROUTE S2 round 1: every route validates the bytes it delivers.

Each case compares a route to full-frame on the same input and config, or checks the
guarantee directly. Full-frame is the reference: validators run after declared casting renders
the outputs, against the same typed, row-aligned source masking read.

Mutations these tests kill: the mixed route pairs raw sources with typed outputs; the
out-of-core drivers collect before declared formatting; the whole-table fallback fold drops the
paired source; validator construction echoes a supplied value.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.errors import ValidatorFailedError
from decoy_engine.execution import run_pipeline
from decoy_engine.execution.out_of_core import _validate_batch
from decoy_engine.validators import ValidationSession
from decoy_engine.validators._registry import _REGISTRY
from tests._declared_schema import declare_rest
from tests.acceptance._f06_support import column, config, text_table, write_csv
from tests.parity import _f2_mixed_support as mixed
from tests.parity import test_phase_d_d3a_validators_ooc as ooc

_SECRET_URL = "https://svc-user:hunter2-token@db.internal.example/prod"
_SENTINEL = {"id": "sentinel/exact/v1", "values": ["TBD"]}


# --- 1. mixed route: leak_check reads the parsed, row-aligned source ------------------------------


def _mixed_declared_job(tmp_path: Path) -> tuple[dict[str, Any], pa.Table]:
    """40 rows; 20 are the sentinel, which declared casting turns into nulls. `truncate` leaves
    the other 20 values unchanged, so a leak check over the typed rows sees 20 of 20 identical."""
    keys = pa.array([str(i) for i in range(5)] * 8, pa.string())
    codes = [f"keep{i:02d}" if i % 2 else "TBD" for i in range(40)]
    child = pa.table({mixed.FK: keys, "code": pa.array(codes, pa.string())})
    declared = {
        "name": "code",
        "strategy": "truncate",
        "provider_config": {"length": 20},
        "logical_type": "string",
        "parse_format": {"id": "string/exact/v1"},
        "sentinel_to_null": _SENTINEL,
        "error_policy": "null",
    }
    cfg = mixed.mixed_config(tmp_path, child, child_columns=[declared])
    cfg["validators"] = [
        {
            "name": "leak_check",
            "columns": {mixed.CHILD: ["code"]},
            "params": {"max_identical_ratio": 0.75},
        }
    ]
    return cfg, child


def _raises_validation(call: Any) -> bool:
    try:
        call()
    except ValidatorFailedError:
        return True
    return False


@mixed.NEEDS_COMPANION
def test_mixed_leak_check_judges_the_typed_aligned_source_as_full_frame(tmp_path: Path) -> None:
    cfg, child = _mixed_declared_job(tmp_path)
    routes: list[str] = []

    class _Progress:
        def on_event(self, event: Any) -> None:
            if event.kind == "route":
                routes.append(event.route)

    assert _raises_validation(lambda: mixed.run(cfg, {mixed.CHILD: child}, mode="full_frame")), (
        "the reference run must reject the identical rows"
    )
    raised = _raises_validation(lambda: mixed.run(cfg, {mixed.CHILD: child}, progress=_Progress()))
    assert "mixed" in routes, "the job must take the mixed route"
    assert raised, "the mixed route paired raw source rows with typed output rows"


# --- 2. out-of-core: validators judge the declared-format output --------------------------------

_PADDED = {"id": "string/exact/v1", "width": 6, "width_unit": "code_points"}


def _declared_text(col: dict[str, Any]) -> dict[str, Any]:
    return {
        **col,
        "logical_type": "string",
        "parse_format": {"id": "string/exact/v1"},
        "error_policy": "null",
        "output_format": _PADDED,
    }


@pytest.mark.parametrize(
    ("table", "col", "pattern"),
    [("child", "memo", "^m[0-9]$"), ("parent", "code", "^[A-Za-z0-9]{3}$")],
    ids=["child-memo", "parent-code"],
)
def test_out_of_core_validates_the_rendered_bytes_as_full_frame(
    tmp_path: Path, table: str, col: str, pattern: str
) -> None:
    columns = ooc._columns()
    columns[table] = [_declared_text(c) if c["name"] == col else c for c in columns[table]]
    validators = [ooc._v("regex_match", {table: [col]}, pattern=pattern)]
    tables = ooc._tables()
    cfg = ooc.job(tmp_path, tables, columns, validators)
    full = ooc.outcome(cfg, tables, full=True)
    assert full[0] == "failed", "the reference run must reject the padded output"
    via_ooc = ooc.outcome(cfg, tables)
    assert via_ooc == full, "the out-of-core verdict covered bytes it did not deliver"


def test_out_of_core_collects_each_batch_as_it_is_delivered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    real = _validate_batch.collect_batch_validation

    def spy(collector: Any, table: str, batch: Any) -> None:
        if table == "child" and "memo" in batch.schema.names:
            seen.extend(v for v in batch.column("memo").to_pylist() if v is not None)
        real(collector, table, batch)

    monkeypatch.setattr(_validate_batch, "collect_batch_validation", spy)
    columns = ooc._columns()
    columns["child"] = [_declared_text(c) if c["name"] == "memo" else c for c in columns["child"]]
    tables = ooc._tables()
    cfg = ooc.job(
        tmp_path, tables, columns, [ooc._v("regex_match", {"child": ["memo"]}, pattern=".*")]
    )
    ooc.outcome(cfg, tables)
    assert seen
    assert all(len(v) == 6 for v in seen), "a cell was checked before it was rendered"


# --- 3. whole-table registry callables keep their source through run_pipeline --------------------


def test_a_whole_table_callable_receives_the_source_through_run_pipeline(tmp_path: Path) -> None:
    received: list[dict[str, Any] | None] = []

    def probe(
        outputs: dict[str, pa.Table],
        entry: dict[str, Any],
        cfg: dict[str, Any],
        *,
        sources: dict[str, pa.Table] | None = None,
    ) -> tuple[Any, ...]:
        received.append(None if sources is None else dict(sources))
        return ()

    src = write_csv(tmp_path / "g.csv", ["id", "v"], [["1", "a"]])
    raw = config(
        [column("id"), column("v")], source_path=src, top={"validators": [{"name": "probe"}]}
    )
    table = text_table(id=["1", "2"], v=["a", "b"])
    _REGISTRY["probe"] = probe
    try:
        run_pipeline(declare_rest(raw), {"people": table}, engine_version="probe")
    finally:
        del _REGISTRY["probe"]
    assert len(received) == 1
    held = received[0]
    assert held is not None and set(held) == {"people"}
    assert held["people"].num_rows == 2


# --- 5. validator construction never echoes a supplied value --------------------------------------


@pytest.mark.parametrize(
    "validators",
    [
        [_SECRET_URL],
        [{"name": "leak_check", "params": {"max_identical_ratio": _SECRET_URL}}],
        [{"name": "leak_check", "params": {"min_rows": _SECRET_URL}}],
        [
            {
                "name": "reconciliation_holds",
                "params": {
                    "parent_table": "a",
                    "parent_column": "x",
                    "child_table": "b",
                    "child_column": "y",
                    "tolerance": _SECRET_URL,
                },
            }
        ],
        [{"name": _SECRET_URL}],
    ],
    ids=["entry", "ratio", "min-rows", "tolerance", "name"],
)
def test_validator_construction_errors_do_not_echo_values(validators: list[Any]) -> None:
    with pytest.raises(ValueError) as caught:
        ValidationSession({"validators": validators})
    text = str(caught.value)
    assert "hunter2" not in text and "svc-user" not in text
    assert "validators entry 0" in text


def test_a_credential_in_a_validator_param_is_not_echoed_by_run_pipeline(tmp_path: Path) -> None:
    src = write_csv(tmp_path / "g.csv", ["id"], [["1"]])
    bad = {"name": "leak_check", "params": {"max_identical_ratio": _SECRET_URL}}
    raw = config([column("id")], source_path=src, top={"validators": [bad]})
    with pytest.raises(Exception) as caught:
        run_pipeline(declare_rest(raw), {"people": text_table(id=["1"])}, engine_version="probe")
    assert "hunter2" not in str(caught.value)
