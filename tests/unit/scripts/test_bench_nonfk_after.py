"""The NONFK-OOM S5 bench helpers (`scripts/bench-auto-chunk/bench_nonfk_fallthrough.py`).

The after-case reads three facts off a refused run: the registered code, that the error is cleanly
chained, and that no staging entry was left. These helpers hold the verdict, so a wrong one cannot
turn an OOM kill or a leaked directory into a "pass" in the record."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
CODE = "nonfk_full_frame_capacity_exceeded"


@pytest.fixture(scope="module")
def bench() -> Any:
    path = REPO / "scripts" / "bench-auto-chunk" / "bench_nonfk_fallthrough.py"
    spec = importlib.util.spec_from_file_location("bench_nonfk_fallthrough", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _CodedError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__("text")
        self.code = code


def test_refusal_evidence_reports_code_and_clean_chaining(bench: Any) -> None:
    exc = _CodedError(CODE)
    assert bench.refusal_evidence(exc) == {"code": CODE, "clean_chaining": True}


def test_refusal_evidence_flags_a_chained_error(bench: Any) -> None:
    try:
        try:
            raise ValueError("inner")
        except ValueError:
            raise _CodedError(CODE) from None
    except _CodedError as exc:
        # `from None` hides the cause but the context is still set: not clean.
        assert bench.refusal_evidence(exc)["clean_chaining"] is False


def test_new_entries_lists_only_what_appeared(bench: Any, tmp_path: Path) -> None:
    (tmp_path / "old").mkdir()
    before = bench.snapshot_entries([tmp_path])
    (tmp_path / "staging-x").mkdir()
    assert bench.new_entries(before, bench.snapshot_entries([tmp_path])) == [
        str(tmp_path / "staging-x")
    ]


def test_new_entries_empty_when_nothing_appeared(bench: Any, tmp_path: Path) -> None:
    (tmp_path / "old").mkdir()
    before = bench.snapshot_entries([tmp_path])
    assert bench.new_entries(before, bench.snapshot_entries([tmp_path])) == []


@pytest.mark.parametrize(
    ("exit_code", "stderr", "target", "staging", "expected"),
    [
        (5, f"error: {CODE}", False, [], True),
        (-9, "", False, [], False),  # killed for memory: the before-case
        (1, f"error: {CODE}", False, [], False),  # wrong exit class
        (5, "error: something else", False, [], False),  # not the registered code
        (5, f"error: {CODE}", True, [], False),  # a target file appeared
        (5, f"error: {CODE}", False, ["/x/.staging"], False),  # staging left behind
    ],
)
def test_e2e_refused_cleanly(
    bench: Any, exit_code: int, stderr: str, target: bool, staging: list[str], expected: bool
) -> None:
    assert bench.e2e_refused_cleanly(exit_code, stderr, target, staging) is expected


def test_passthrough_only_keeps_every_column_and_drops_every_mask(bench: Any) -> None:
    config = bench.build_config("W-U", "/data/in.parquet")
    names = [c["name"] for c in config["tables"][0]["columns"]]
    plain = bench.passthrough_only(config)
    columns = plain["tables"][0]["columns"]
    assert [c["name"] for c in columns] == names
    assert {c["strategy"] for c in columns} == {"passthrough"}
    # The input config is not edited in place.
    assert {c["strategy"] for c in config["tables"][0]["columns"]} > {"passthrough"}
    assert len({c["strategy"] for c in config["tables"][0]["columns"]}) > 1


def test_expected_refusal_accepts_only_the_capacity_code(bench: Any) -> None:
    assert bench.is_expected_refusal(_CodedError(CODE)) is True
    assert bench.is_expected_refusal(_CodedError("some_other_code")) is False
    assert bench.is_expected_refusal(ValueError("no code")) is False


def test_run_dir_is_fresh_and_leaves_the_callers_files_alone(bench: Any, tmp_path: Path) -> None:
    (tmp_path / "out.parquet").write_text("keep")
    (tmp_path / "job.yaml").write_text("keep")
    first = bench.fresh_run_dir(tmp_path)
    second = bench.fresh_run_dir(tmp_path)
    assert first != second
    assert first.parent == tmp_path and second.parent == tmp_path
    assert (tmp_path / "out.parquet").read_text() == "keep"
    assert (tmp_path / "job.yaml").read_text() == "keep"
    assert list(first.iterdir()) == []


def test_cgroup_command_is_one_builder_with_memory_and_swap_limits(bench: Any) -> None:
    inner = ["decoy", "run", "job.yaml"]
    assert bench.cgroup_command(inner, None) == inner
    wrapped = bench.cgroup_command(inner, 123)
    assert wrapped[:4] == ["systemd-run", "--user", "--scope", "-q"]
    assert "MemoryMax=123" in wrapped and "MemorySwapMax=0" in wrapped
    assert wrapped[-3:] == inner


def test_trial_command_uses_the_shared_cgroup_builder(bench: Any, tmp_path: Path) -> None:
    cell = {"workload": "W-P", "rows": 10, "input": "lazy"}
    cmd = bench.trial_command(cell, tmp_path / "s.parquet", tmp_path, 777)
    assert "MemoryMax=777" in cmd and "MemorySwapMax=0" in cmd
    assert cmd == bench.cgroup_command(
        bench.trial_command(cell, tmp_path / "s.parquet", tmp_path, None), 777
    )


def _trial(route_mode: str, chunked: bool, peak: int, **extra: Any) -> dict[str, Any]:
    return {
        "exit_status": 0,
        "peak_bytes": peak,
        "increment_bytes": peak,
        "lower_bound_bytes": 100,
        "execution": {"execution_mode": route_mode},
        "chunked_route": chunked,
        **extra,
    }


def test_route_of_trial_reads_the_measured_route(bench: Any) -> None:
    assert bench.route_of_trial(_trial("full_frame", False, 1)) == "full_frame"
    assert bench.route_of_trial(_trial("full_frame", True, 1)) == "chunked"
    assert bench.route_of_trial(_trial("out_of_core", False, 1)) == "chunked"


def test_lower_bound_applies_only_to_full_frame_trials(bench: Any) -> None:
    trials = [_trial("full_frame", True, 50), _trial("full_frame", True, 60)]
    # A chunked run may sit below the full-frame bound; that is the point of the route.
    checks = bench.lower_bound_checks(trials, "W-P", "after")
    assert checks["peak_at_least_lb"] is None
    assert checks["route_mismatch"] is False


def test_lower_bound_still_checks_full_frame_trials(bench: Any) -> None:
    trials = [_trial("full_frame", False, 50)]
    checks = bench.lower_bound_checks(trials, "W-S", "after")
    assert checks["peak_at_least_lb"] is False
    assert checks["route_mismatch"] is False


def test_w_p_after_expects_the_chunked_route(bench: Any) -> None:
    still_full = [_trial("full_frame", False, 500)]
    assert bench.lower_bound_checks(still_full, "W-P", "after")["route_mismatch"] is True
    assert bench.lower_bound_checks(still_full, "W-P", "before")["route_mismatch"] is False
    chunked = [_trial("full_frame", True, 500)]
    assert bench.lower_bound_checks(chunked, "W-P", "before")["route_mismatch"] is True


def test_unexpected_exit_separates_a_kill_from_a_crash(bench: Any) -> None:
    assert bench.unexpected_exit(0, None) is False
    assert bench.unexpected_exit(1, None) is True
    assert bench.unexpected_exit(137, 1_000_000) is False  # killed for memory under the cap
    assert bench.unexpected_exit(1, 1_000_000) is True  # a traceback under the cap is a failure
