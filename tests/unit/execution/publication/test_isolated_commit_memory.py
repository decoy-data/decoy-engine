"""A memory failure around the isolated route's publication call is a coded result.

The contract has two halves. Before the flag (setup through result preparation) a memory failure
is `process_out_of_memory` with NOT_PUBLISHED and the stage aborted. From just before
`publish_unit` through final cleanup it is the same reason with UNKNOWN: the target may or may not
exist, and the fixed text tells the caller to rerun with the same operation id. It is never a raw
exception and never a false NOT_PUBLISHED once publishing may have started.

One fault per run, injected into the real call, with the fake child and real staging.
"""

from __future__ import annotations

import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest

from decoy_engine import reasons
from decoy_engine.execution import _isolated_commit, _isolated_run
from decoy_engine.reasons import PublicationState
from decoy_engine.reasons import decoy as _decoy
from tests.unit.execution.publication._isolated_support import ENGINE_VERSION
from tests.unit.execution.publication.test_isolated_readback_cap import (
    FIGURES,
    HUGE,
    Run,
    ints,
    scratch,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX isolated route")

COMMIT = "decoy_engine.execution._isolated_commit"
RUN = "decoy_engine.execution._isolated_run"
CODE = "process_out_of_memory"
_SUMMARY = reasons.get(_decoy.PROCESS_OUT_OF_MEMORY.namespace, _decoy.PROCESS_OUT_OF_MEMORY).summary
BEFORE_TEXT = (
    f"{_SUMMARY} Run on a machine with more memory, or write fewer or smaller output tables."
)
UNKNOWN_TEXT = f"{_SUMMARY} Rerun with the same operation id to confirm."
CANARY = "CANARY-MEMORY"


def once(monkeypatch: pytest.MonkeyPatch, target: str, fired: list[str]) -> None:
    """Make the first call of `target` raise MemoryError, then behave as before."""
    module, _, name = target.rpartition(".")
    owner = sys.modules[module]
    real = getattr(owner, name)

    def fault(*args: Any, **kwargs: Any) -> Any:
        if not fired:
            fired.append(name)
            raise MemoryError(CANARY)
        return real(*args, **kwargs)

    monkeypatch.setattr(target, fault)


def memory(result: Any, state: PublicationState, text: str) -> None:
    assert result.outcome == "crashed"
    assert result.outputs is None
    assert result.reason is not None and result.reason.code == CODE
    assert result.reason.context.publication_state == state
    assert result.error == text
    assert CANARY not in repr(result)
    # Before the first figures exist the entry is absent; once there it is complete.
    assert set(result.extra.get("readback", FIGURES)) == FIGURES


def a_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Run:
    return Run(tmp_path, monkeypatch, [ints("t1", 10)], ceiling=HUGE)


BEFORE_THE_FLAG = [
    f"{COMMIT}.row_errors_of",
    f"{COMMIT}.asdict",
    f"{COMMIT}._admit",
    f"{COMMIT}._names_ok",
    f"{COMMIT}._priced",
    f"{COMMIT}.check_readback",
    f"{COMMIT}.lower_bound_bytes",
    f"{COMMIT}._read_staged",
]


@pytest.mark.parametrize("output", [True, False], ids=["output_dir", "no_output_dir"])
@pytest.mark.parametrize("target", BEFORE_THE_FLAG)
def test_a14_a_fault_before_the_flag_is_not_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
    target: str,
    output: bool,
) -> None:
    run = a_run(tmp_path, monkeypatch)
    fired: list[str] = []
    once(monkeypatch, target, fired)
    result = run.go(output=output)
    assert fired, f"{target} was never reached"
    memory(result, PublicationState.NOT_PUBLISHED, BEFORE_TEXT)
    assert list(scratch.iterdir()) == []
    run.nothing_left(output)


def test_a14_a_fault_in_the_reader_setup_is_not_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
) -> None:
    run = a_run(tmp_path, monkeypatch)
    fired: list[str] = []
    real = _isolated_commit._Readback

    def broken(*args: Any, **kwargs: Any) -> Any:
        fired.append("reader")
        raise MemoryError(CANARY)

    monkeypatch.setattr(f"{COMMIT}._Readback", broken)
    result = run.go()
    assert fired and real is not broken
    memory(result, PublicationState.NOT_PUBLISHED, BEFORE_TEXT)
    run.nothing_left(True)


def committed(run: Run) -> None:
    """The unit was published whatever the result says: the target is readable."""
    assert run.out.exists()
    assert (run.out / "t1.parquet").exists()


def unknown(result: Any) -> None:
    memory(result, PublicationState.UNKNOWN, UNKNOWN_TEXT)
    assert result.publication_receipt is None
    assert result.committed_output_dir is None
    # The reserve carries the last complete figures, not the zeros it was built with.
    assert result.extra["readback"]["tables_read"] == 1


def test_a14_a_fault_inside_publish_before_it_binds_is_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
) -> None:
    run = a_run(tmp_path, monkeypatch)
    fired: list[str] = []

    def failing(*args: Any, **kwargs: Any) -> Any:
        fired.append("publish")
        raise MemoryError(CANARY)

    monkeypatch.setattr(f"{COMMIT}.publish_unit", failing)
    result = run.go()
    assert fired
    unknown(result)
    assert not run.out.exists()


def test_a14_a_fault_after_the_real_publisher_returns_is_unknown_with_the_target_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
) -> None:
    run = a_run(tmp_path, monkeypatch)
    fired: list[str] = []
    real = _isolated_commit.publish_unit

    def published_then_fails(*args: Any, **kwargs: Any) -> Any:
        real(*args, **kwargs)
        fired.append("publish")
        raise MemoryError(CANARY)

    monkeypatch.setattr(f"{COMMIT}.publish_unit", published_then_fails)
    result = run.go()
    assert fired
    unknown(result)
    committed(run)
    # The advice works: the same request on the same destination confirms the commit.
    monkeypatch.setattr(f"{COMMIT}.publish_unit", real)
    again = run.go()
    assert again.outcome == "completed"
    assert again.publication_receipt is not None
    assert again.publication_receipt.outcome == "already_committed"


@pytest.mark.parametrize("target", [f"{COMMIT}.IsolatedRunResult", f"{RUN}.evidence_of"])
def test_a14_a_fault_building_the_completed_result_is_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
    target: str,
) -> None:
    run = a_run(tmp_path, monkeypatch)
    fired: list[str] = []
    once(monkeypatch, target, fired)
    result = run.go()
    assert fired
    unknown(result)
    committed(run)


def test_a14_cleanup_faults_are_unknown_and_scratch_close_still_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
) -> None:
    run = a_run(tmp_path, monkeypatch)
    order: list[str] = []
    real_begin = _isolated_run.begin_publication

    def begin(*args: Any, **kwargs: Any) -> Any:
        pub = real_begin(*args, **kwargs)
        if hasattr(pub, "txn"):
            real_abort = type(pub.txn).abort

            def abort(self: Any) -> None:
                real_abort(self)
                if sys._getframe(1).f_code.co_name == "_run_isolated":  # the finalizer's call
                    order.append("abort")
                    raise MemoryError(CANARY)

            monkeypatch.setattr(type(pub.txn), "abort", abort)
        return pub

    class Stack(ExitStack):
        def close(self) -> None:
            order.append("close")
            super().close()

    monkeypatch.setattr(f"{RUN}.begin_publication", begin)
    monkeypatch.setattr(f"{RUN}.ExitStack", Stack)
    result = run.go()
    assert order == ["abort", "close"]
    unknown(result)
    committed(run)
    assert list(scratch.iterdir()) == []


def test_a14_a_normal_run_keeps_its_outputs_and_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scratch: Path,  # noqa: F811
) -> None:
    run = a_run(tmp_path, monkeypatch)
    result = run.go()
    assert result.outcome == "completed"
    assert result.publication_receipt is not None
    assert result.outputs is not None and set(result.outputs) == {"t1"}
    assert ENGINE_VERSION
    committed(run)
