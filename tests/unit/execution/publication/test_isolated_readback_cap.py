"""The driver's readback of a child's staged output is capped by the kill ceiling.

After a child exits, the driver reads every staged table back into its own memory before it
publishes, with no memory limit of its own. Before each decode it now checks a strict lower
bound on what it would then hold (the caller's resident sources, the tables already read at
their measured bytes, this table and the rest at their Parquet footer floor) against the host
or cgroup kill ceiling. Only a bound above the ceiling refuses; a run at or under it returns
what it always did. A memory failure while reading is a coded memory result, not a
publication failure.

Most cases use the fake child (`install_fake_worker`) that stages an ordered list of tables
and a patched ceiling, with a spy on the driver's decode. The real-child cases are the streamed
out-of-core run and the governor.
"""

from __future__ import annotations

import errno
import gc
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import reasons
from decoy_engine.execution import _governor, run_pipeline_isolated
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.execution.pipeline import lazy_spec, lower_bound_bytes, resident_spec
from decoy_engine.fileaccess.adapters import arrow as arrow_adapter
from decoy_engine.publication import PublicationRequest
from tests.unit.execution.publication._isolated_support import (
    ENGINE_VERSION,
    install_fake_worker,
    job,
    sources,
    spec_table,
)
from tests.unit.publication._publish_support import stages_left

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX isolated route")

COMMIT = "decoy_engine.execution._isolated_commit"
CAPACITY = "isolated_readback_capacity_exceeded"
SUMMARY = "The finished output tables would hold more memory than this machine can give the caller."
REMEDY = "Run on a machine with more memory, or write fewer or smaller output tables."
REFUSAL = re.compile(
    re.escape(SUMMARY)
    + r" The figure checked is [0-9]+ bytes and the memory ceiling is [0-9]+ bytes\. "
    + re.escape(REMEDY)
)
FIGURES = {
    "kill_ceiling_bytes",
    "sources_bytes",
    "floor_bytes",
    "held_bytes",
    "tables_read",
    "tables_staged",
}
HUGE = 1 << 60
SECRET_ENV = "DECOY_TEST_READBACK_SECRET"


def ints(name: str, rows: int) -> dict[str, Any]:
    return {"name": name, "rows": rows, "columns": {"a": ["int", ""]}}


def strings(name: str, rows: int, text: str) -> dict[str, Any]:
    return {"name": name, "rows": rows, "columns": {"s": ["str", text]}}


def floor_of(entries: list[dict[str, Any]]) -> int:
    return lower_bound_bytes(
        [lazy_spec(e["rows"], spec_table(e).schema, charge_pandas=False) for e in entries]
    )


def measured(tmp_path: Path, entry: dict[str, Any]) -> int:
    """The bytes the driver holds for this table once it is read back from Parquet."""
    path = tmp_path / f"measure-{entry['name']}.parquet"
    pq.write_table(spec_table(entry), path)
    size = resident_spec(pq.read_table(path), charge_pandas=False).resident_input_bytes
    assert size is not None
    return size


def bytes_of(tables: dict[str, pa.Table]) -> int:
    return lower_bound_bytes([resident_spec(t, charge_pandas=False) for t in tables.values()])


class Decodes:
    """A spy on the driver's decode of a staged table; can raise on the n-th one."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.names: list[str] = []
        self.fail_on: int | None = None
        self.error: BaseException | None = None
        real = arrow_adapter.read_table

        def spy(handle: Any, **kwargs: Any) -> pa.Table:
            self.names.append(Path(str(handle.display)).name)
            if self.fail_on == len(self.names) and self.error is not None:
                raise self.error
            return real(handle, **kwargs)

        monkeypatch.setattr(arrow_adapter, "read_table", spy)


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The engine's scratch root, empty, so a leftover work root shows."""
    root = tmp_path / "scratch"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("TMPDIR", str(root))
    return root


class Run:
    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        entries: list[dict[str, Any]],
        *,
        ceiling: int | None,
        plant: str = "",
    ) -> None:
        self.tmp = tmp_path
        self.entries = entries
        self.out = tmp_path / "pub" / "out"
        install_fake_worker(tmp_path, monkeypatch, tables=entries, plant=plant)
        self.set_ceiling(monkeypatch, ceiling)
        self.decodes = Decodes(monkeypatch)
        self.cfg = job(tmp_path, 3)

    @staticmethod
    def set_ceiling(monkeypatch: pytest.MonkeyPatch, ceiling: int | None) -> None:
        monkeypatch.setattr(f"{COMMIT}.kill_ceiling", lambda: ceiling)

    def go(
        self,
        *,
        held: dict[str, pa.Table] | None = None,
        output: bool = True,
        staging: Path | None = None,
    ) -> Any:
        return run_pipeline_isolated(
            self.cfg,
            sources(self.cfg) if held is None else held,
            engine_version=ENGINE_VERSION,
            output_dir=self.out if output else None,
            staging_dir=staging,
            request=PublicationRequest("op-readback") if output else None,
        )

    def nothing_left(self, output: bool) -> None:
        if output:
            assert not self.out.exists()
            assert stages_left(self.out.parent) == []


def refused(result: Any) -> None:
    assert result.outcome == "crashed"
    assert result.outputs is None
    assert result.reason is not None and result.reason.code == CAPACITY
    assert REFUSAL.fullmatch(result.error)


@pytest.mark.parametrize("output", [True, False], ids=["output_dir", "no_output_dir"])
def test_a1_a_floor_over_the_ceiling_refuses_before_any_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch: Path, output: bool
) -> None:
    entries = [ints("t1", 1000), ints("t2", 500)]
    run = Run(tmp_path, monkeypatch, entries, ceiling=floor_of(entries) - 1)
    result = run.go(output=output)
    refused(result)
    assert run.decodes.names == []
    assert list(scratch.iterdir()) == []
    run.nothing_left(output)
    assert result.extra["readback"]["tables_read"] == 0
    assert result.extra["readback"]["tables_staged"] == 2


def test_a2_measured_bytes_tighten_the_bound_after_a_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch: Path
) -> None:
    t1, t2 = strings("t1", 1000, "x" * 100), ints("t2", 1000)
    f1, f2, m1 = floor_of([t1]), floor_of([t2]), measured(tmp_path, t1)
    ceiling = f1 + f2 + (m1 - f1) // 2
    assert f1 + f2 <= ceiling < m1 + f2  # the floor fits, the measured table does not
    run = Run(tmp_path, monkeypatch, [t1, t2], ceiling=ceiling)
    result = run.go(held={})
    refused(result)
    assert run.decodes.names == ["t1.parquet"]  # t2 is never decoded
    assert result.extra["readback"]["tables_read"] == 1
    assert result.extra["readback"]["held_bytes"] == m1


def test_a3_the_callers_resident_sources_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch: Path
) -> None:
    entries = [ints("t1", 100)]
    big = {"t": pa.table({"a": [f"{'y' * 100}{i}" for i in range(2000)]})}
    ceiling = floor_of(entries) + bytes_of(big) // 2
    run = Run(tmp_path, monkeypatch, entries, ceiling=ceiling)
    refused(run.go(held=big, output=False))
    assert run.decodes.names == []
    # The outputs alone fit, so it is the sources that tipped it.
    result = run.go(held={}, output=False)
    assert result.outcome == "completed" and run.decodes.names == ["t1.parquet"]


def _pub_equal(result: Any, out: Path) -> None:
    for name, table in result.outputs.items():
        published = pq.read_table(out / f"{name}.parquet")
        assert table.schema.equals(published.schema, check_metadata=True), name
        assert table.equals(published, check_metadata=True), name
        pd.testing.assert_frame_equal(table.to_pandas(), published.to_pandas())


@pytest.mark.parametrize("variant", ["equal", "within_the_admission_band"])
def test_a4_a_bound_at_or_under_the_ceiling_runs_and_returns_what_main_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch: Path, variant: str
) -> None:
    t1, t2 = strings("t1", 500, "z" * 20), ints("t2", 700)
    held = sources(job(tmp_path, 3))
    # The largest bound any check sees: the sources, t1 as read, and t2 at its floor.
    needed = bytes_of(held) + measured(tmp_path, t1) + floor_of([t2])
    ceiling = needed if variant == "equal" else -(-needed * 10 // 9)
    assert variant == "equal" or 0.85 * ceiling < needed <= ceiling
    run = Run(tmp_path, monkeypatch, [t1, t2], ceiling=ceiling)
    result = run.go(held=held)
    assert result.outcome == "completed"
    assert run.decodes.names == ["t1.parquet", "t2.parquet"]  # one decode per staged table
    _pub_equal(result, run.out)
    figures = result.extra["readback"]
    assert set(figures) == FIGURES
    assert all(type(v) is int for v in figures.values())
    outputs_bytes = sum(
        resident_spec(t, charge_pandas=False).resident_input_bytes or 0
        for t in result.outputs.values()
    )
    assert figures["kill_ceiling_bytes"] == ceiling
    assert figures["sources_bytes"] == bytes_of(held) > 0
    assert figures["held_bytes"] == outputs_bytes  # outputs only, not the sources
    assert figures["floor_bytes"] == floor_of([t1, t2]) <= figures["held_bytes"]
    assert figures["tables_read"] == figures["tables_staged"] == 2


def test_a4_opaque_pandas_metadata_is_priced_without_a_pandas_conversion() -> None:
    from decoy_engine.execution._isolated_commit import _priced

    table = pa.table({"s": ["a", "b"]}).replace_schema_metadata({"pandas": "{not json"})
    with pytest.raises(ValueError):  # non-vacuity: the unstripped schema cannot be parsed
        resident_spec(table, charge_pandas=False)
    priced = _priced(table)
    plain = resident_spec(pa.table({"s": ["a", "b"]}), charge_pandas=False)
    assert priced.resident_input_bytes == plain.resident_input_bytes
    assert priced.resident_input_bytes and not priced.charge_pandas


def test_a5_an_undetectable_ceiling_checks_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch: Path
) -> None:
    run = Run(tmp_path, monkeypatch, [ints("t1", 5000)], ceiling=None)
    result = run.go()
    assert result.outcome == "completed"
    figures = result.extra["readback"]
    assert figures["kill_ceiling_bytes"] is None
    assert all(type(v) is int for k, v in figures.items() if k != "kill_ceiling_bytes")
    assert figures["tables_read"] == 1


def test_a6_a_refusal_names_no_table_column_or_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch: Path, caplog: pytest.LogCaptureFixture
) -> None:
    canary = "canary_9f3b"
    entry = {
        "name": f"{canary}_table",
        "rows": 50,
        "columns": {f"{canary}_column": ["str", f"{canary}_value_"]},
    }
    run = Run(tmp_path, monkeypatch, [entry], ceiling=floor_of([entry]) - 1)
    with caplog.at_level(logging.DEBUG):
        result = run.go()
    refused(result)
    assert REFUSAL.fullmatch(result.error)
    assert REFUSAL.fullmatch(result.error + "\n") is None  # anchored: no trailing newline
    surfaces = [
        result.error,
        repr(result),
        json.dumps(result.reason.to_payload()),
        repr(result.extra),
        repr(result.publication_receipt),
        caplog.text,
    ]
    assert not [s for s in surfaces if canary in s]


def test_a7_the_governor_stops_on_a_refusal_instead_of_rerouting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch: Path
) -> None:
    cfg = job(tmp_path, 50)
    monkeypatch.setattr(f"{COMMIT}.kill_ceiling", lambda: 1)
    outcome = _governor.run_job_with_governor(
        cfg, sources(cfg), budget_bytes=1 << 30, engine_version=ENGINE_VERSION
    )
    assert outcome.outcome == "exhausted"
    assert len(outcome.trips) == 1  # the later rungs of the ladder are not tried
    trip = outcome.trips[0]
    assert (trip.route, trip.trip_kind, trip.reroute_to) == ("full_frame", "crashed", None)
    assert trip.error is not None and REFUSAL.fullmatch(trip.error)


def test_a8_a_mid_read_refusal_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch: Path
) -> None:
    t1, t2 = strings("t1", 1000, "x" * 100), ints("t2", 1000)
    ceiling = floor_of([t1, t2]) + (measured(tmp_path, t1) - floor_of([t1])) // 2
    run = Run(tmp_path, monkeypatch, [t1, t2], ceiling=ceiling)
    result = run.go(held={})
    refused(result)
    run.nothing_left(True)
    receipt = result.publication_receipt
    assert receipt is not None and receipt.outcome == "failed"
    assert result.committed_output_dir is None


def _interrupt_over_memory() -> KeyboardInterrupt:
    """Arrow reports exhaustion at a cap as a `KeyboardInterrupt` raised while handling a
    `MemoryError`; only the exception types are read."""
    try:
        try:
            raise MemoryError("CANARY")
        except MemoryError:
            raise KeyboardInterrupt from None
    except KeyboardInterrupt as exc:
        return exc
    raise AssertionError("unreachable")


MEMORY_FAILURES = {
    "interrupt_over_memory": _interrupt_over_memory,
    "arrow_memory_error": lambda: pa.ArrowMemoryError("CANARY"),
    "bare_memory_error": lambda: MemoryError("CANARY"),
    "enomem": lambda: OSError(errno.ENOMEM, "CANARY"),
    "arrow_marker": lambda: pa.ArrowInvalid("not able to copy ctx CANARY"),
}


@pytest.mark.parametrize("kind", sorted(MEMORY_FAILURES))
def test_a9_a_memory_failure_while_reading_is_a_coded_memory_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch: Path, kind: str
) -> None:
    run = Run(tmp_path, monkeypatch, [ints("t1", 10), ints("t2", 10)], ceiling=HUGE)
    run.decodes.fail_on, run.decodes.error = 2, MEMORY_FAILURES[kind]()
    result = run.go()
    assert result.outcome == "crashed" and result.outputs is None
    assert result.reason is not None and result.reason.code == "process_out_of_memory"
    assert "CANARY" not in result.error + repr(result)
    assert os.strerror(errno.ENOMEM) not in result.error
    run.nothing_left(True)
    assert list(scratch.iterdir()) == []


def _wholly_clean(run: Run, output: bool, staging: Path | None, scratch: Path) -> None:
    run.nothing_left(output)
    if staging is None:
        assert list(scratch.iterdir()) == []
    else:
        assert staging.is_dir() and not (staging / "staging_output").exists()


@pytest.mark.parametrize("fail_at", [1, 4], ids=["first_measure", "after_the_last_decode"])
def test_a9_a_failure_while_measuring_is_a_memory_result_and_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch: Path, fail_at: int
) -> None:
    """The figures are taken in the guarded read: the last measure runs after the final decode
    and before `publish_unit`, so an allocation failure there publishes nothing."""
    run = Run(tmp_path, monkeypatch, [ints("t1", 10)], ceiling=HUGE)
    real = lower_bound_bytes
    calls: list[int] = []

    def failing(specs: Any) -> int:
        calls.append(1)
        if len(calls) == fail_at:  # each measure makes three calls
            raise MemoryError("CANARY")
        return real(specs)

    monkeypatch.setattr(f"{COMMIT}.lower_bound_bytes", failing)
    result = run.go()
    assert result.reason is not None and result.reason.code == "process_out_of_memory"
    assert "CANARY" not in result.error + repr(result)
    assert run.decodes.names == ([] if fail_at == 1 else ["t1.parquet"])
    run.nothing_left(True)


def test_a9_nothing_the_result_needs_is_allocated_after_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch: Path
) -> None:
    """No readback pricing runs after `publish_unit`, so a fault in it cannot change the result."""
    run = Run(tmp_path, monkeypatch, [ints("t1", 10)], ceiling=HUGE)
    published: list[bool] = []
    real_publish = sys.modules[COMMIT].publish_unit
    real_bytes = lower_bound_bytes

    def publish(*args: Any, **kwargs: Any) -> Any:
        receipt = real_publish(*args, **kwargs)
        published.append(True)
        return receipt

    def failing(specs: Any) -> int:
        if published:
            raise MemoryError("CANARY")
        return real_bytes(specs)

    monkeypatch.setattr(f"{COMMIT}.publish_unit", publish)
    monkeypatch.setattr(f"{COMMIT}.lower_bound_bytes", failing)
    result = run.go()
    assert published
    assert result.outcome == "completed"
    assert result.extra["readback"]["tables_read"] == 1
    assert run.out.exists()


def test_a9_a_plain_interrupt_is_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch: Path
) -> None:
    run = Run(tmp_path, monkeypatch, [ints("t1", 10), ints("t2", 10)], ceiling=HUGE)
    run.decodes.fail_on, run.decodes.error = 2, KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        run.go()
    run.nothing_left(True)
    assert list(scratch.iterdir()) == []


def _open_under(root: Path) -> list[str]:
    """The files this process holds open beneath `root`; empty where /proc is absent."""
    fd_dir = Path("/proc/self/fd")
    if not fd_dir.is_dir():
        return []
    held = []
    for entry in fd_dir.iterdir():
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith(str(root)):
            held.append(target)
    return sorted(held)


SCENARIOS = [
    "pre_read_refusal",
    "mid_read_refusal",
    "memory_failure",
    "corrupt_footer",
    "detection_error",
]


@pytest.mark.parametrize("caller_root", [False, True], ids=["engine_root", "caller_root"])
@pytest.mark.parametrize("output", [True, False], ids=["output_dir", "no_output_dir"])
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_a12_every_exit_path_leaves_no_stage_and_no_open_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,
    scenario: str,
    output: bool,
    caller_root: bool,
) -> None:
    t1, t2 = strings("t1", 1000, "x" * 100), ints("t2", 1000)
    mid = floor_of([t1, t2]) + (measured(tmp_path, t1) - floor_of([t1])) // 2
    ceiling = {"pre_read_refusal": floor_of([t1, t2]) - 1, "mid_read_refusal": mid}.get(
        scenario, HUGE
    )
    run = Run(
        tmp_path,
        monkeypatch,
        [t1, t2],
        ceiling=ceiling,
        plant="corrupt_first" if scenario == "corrupt_footer" else "",
    )
    staging = tmp_path / "work" if caller_root else None
    if scenario == "memory_failure":
        run.decodes.fail_on, run.decodes.error = 2, MemoryError("CANARY")
    if scenario == "detection_error":
        monkeypatch.setattr(
            f"{COMMIT}.kill_ceiling",
            lambda: (_ for _ in ()).throw(
                ExecutionError(
                    code=reasons.runtime.OUT_OF_CORE_INSUFFICIENT_MEMORY, message="detection"
                )
            ),
        )
    gc.collect()
    before = _open_under(tmp_path)
    if scenario == "detection_error":  # detection raises another coded error: it propagates
        with pytest.raises(ExecutionError) as raised:
            run.go(held={}, output=output, staging=staging)
        assert raised.value.code == reasons.runtime.OUT_OF_CORE_INSUFFICIENT_MEMORY
    else:
        result = run.go(held={}, output=output, staging=staging)
        expected = {
            "pre_read_refusal": CAPACITY,
            "mid_read_refusal": CAPACITY,
            "memory_failure": "process_out_of_memory",
            "corrupt_footer": "publication_failed",
        }[scenario]
        assert result.outcome == "crashed" and result.outputs is None
        assert result.reason is not None and result.reason.code == expected
    assert _open_under(tmp_path) == before
    _wholly_clean(run, output, staging, scratch)


def _fk_config(tmp_path: Path) -> dict[str, Any]:
    """A small pure-mask foreign-key job that both the full-frame and out-of-core routes admit."""
    count = 30
    parent = pa.table({"id": [f"p{i}" for i in range(count)]})
    child = pa.table(
        {"cid": [f"c{i}" for i in range(count)], "parent_id": [f"p{i}" for i in range(count)]}
    )
    paths = {"parent": tmp_path / "parent.parquet", "child": tmp_path / "child.parquet"}
    pq.write_table(parent, paths["parent"])
    pq.write_table(child, paths["child"])

    def hashed(name: str, namespace: str) -> dict[str, Any]:
        return {"name": name, "strategy": "hash", "namespace": namespace}

    return {
        "version": 2,
        "global_settings": {
            "job_name": "readback-cap",
            "seed": 7,
            "mask_secret_ref": f"env:{SECRET_ENV}",
        },
        "sources": {
            n: {"type": "file", "path": str(p), "format": "parquet"} for n, p in paths.items()
        },
        "targets": {
            n: {"type": "file", "path": str(tmp_path / f"{n}.out.parquet"), "format": "parquet"}
            for n in paths
        },
        "tables": [
            {"name": "parent", "columns": [hashed("id", "ns")]},
            {"name": "child", "columns": [hashed("cid", "cns"), hashed("parent_id", "ns")]},
        ],
        "relationships": [
            {
                "parent": {"table": "parent", "columns": ["id"]},
                "children": [{"table": "child", "columns": ["parent_id"]}],
                "orphan_policy": "preserve",
                "namespace": "ns",
            }
        ],
    }


@pytest.mark.parametrize("variant", ["equal", "within_the_admission_band"])
def test_a4_a_streamed_out_of_core_child_reads_back_once_per_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scratch: Path, variant: str
) -> None:
    config = _fk_config(tmp_path)
    held = sources(config)
    monkeypatch.setenv(SECRET_ENV, "a1" * 32)
    decodes = Decodes(monkeypatch)
    monkeypatch.setattr(f"{COMMIT}.kill_ceiling", lambda: HUGE)
    kwargs: dict[str, Any] = {"engine_version": ENGINE_VERSION, "execution_mode": "out_of_core"}
    probe = run_pipeline_isolated(config, held, **kwargs)
    assert probe.outcome == "completed", (probe.reason, probe.error)
    names = list(probe.outputs)
    read = [resident_spec(probe.outputs[n], charge_pandas=False) for n in names]
    last = probe.outputs[names[-1]]
    # The largest bound any check sees: the caller's sources, every table but the last as read,
    # and the last one at its footer floor.
    needed = (
        bytes_of(held)
        + lower_bound_bytes(read[:-1])
        + lower_bound_bytes([lazy_spec(last.num_rows, last.schema, charge_pandas=False)])
    )
    ceiling = needed if variant == "equal" else -(-needed * 10 // 9)
    monkeypatch.setattr(f"{COMMIT}.kill_ceiling", lambda: ceiling)
    decodes.names.clear()
    out = tmp_path / "pub" / "out"
    result = run_pipeline_isolated(
        config, held, output_dir=out, request=PublicationRequest("op-ooc"), **kwargs
    )
    assert result.outcome == "completed"
    assert result.quality_metrics["execution"]["execution_mode"] == "out_of_core"
    assert result.extra["readback"]["kill_ceiling_bytes"] == ceiling
    assert len(decodes.names) == len(names) == result.extra["readback"]["tables_read"]
    _pub_equal(result, out)
