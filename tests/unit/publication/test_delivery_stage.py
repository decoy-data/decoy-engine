"""`DeliveryStage` (DELIV E2b: AT-27, AT-28 engine part, and the stage's own behavior).

The stage writes local paths, so every case runs under the ambient policy. A run folder is the
empty folder P4 makes; `LATEST` is the managed pointer beside it.
"""

from __future__ import annotations

import errno
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args

import pytest

from decoy_engine import reasons
from decoy_engine.fileaccess import (
    FileAccessDenied,
    FileAccessUnavailable,
    FileRequest,
    FileRole,
)
from decoy_engine.fileaccess._local import LocalFileAccess
from decoy_engine.publication import (
    CurrentPointer,
    DeliveryReceipt,
    DeliveryStage,
    LocalPointerStore,
    Outcome,
    PointerResult,
    PublicationFailed,
    StageDecision,
)
from decoy_engine.publication import _stage as stage_module
from decoy_engine.publication._current import HeldPointer
from tests.fileaccess.publication._chain_support import anchor_at
from tests.unit.publication._publish_support import DESCRIPTOR, descriptor
from tests.unit.publication._vault_publish_support import binding

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX durable pointer")

MOVED = reasons.decoy.DELIVERY_POINTER_MOVED
FAILED = reasons.decoy.PUBLICATION_FAILED
UNCERTAIN = reasons.decoy.PUBLICATION_COMMIT_UNCERTAIN
CONFLICT = reasons.decoy.PUBLICATION_OPERATION_CONFLICT
EVERYTHING = StageDecision(True, frozenset({"a", "b"}))


def _dir(base: Path, rel: str) -> Any:
    req = FileRequest(FileRole.TARGET_OUTPUT, "write", str(base / rel), "targets.t.path")
    return LocalFileAccess().output_dir(req)


class Run:
    """One project folder `out/n` with its pointer, and a way to open runs against it."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.folder = base / "out" / "n"
        self.folder.mkdir(parents=True)
        leaf = _dir(base, "out/n/LATEST")
        self.pointer = CurrentPointer(LocalPointerStore(leaf), leaf)
        self.latest = self.folder / "LATEST"

    def open(self, run_id: str = "r1", **kw: Any) -> DeliveryStage:
        (self.folder / run_id).mkdir(exist_ok=True)
        return DeliveryStage.open(
            _dir(self.base, f"out/n/{run_id}"), self.pointer, run_id, f"op-{run_id}", **kw
        )

    def stage_files(self, stage: DeliveryStage) -> None:
        stage.stage_path("a", "a.csv").write_bytes(b"a1\n")
        stage.stage_path("b", "masked/b.csv").write_bytes(b"b1\n")

    def litter(self) -> list[str]:
        return sorted(p.name for p in self.folder.iterdir() if p.name.startswith("._decoy"))


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Run:
    anchor_at(monkeypatch, tmp_path)
    return Run(tmp_path)


def _deliver(stage: DeliveryStage, decision: StageDecision = EVERYTHING, **kw: Any) -> Any:
    return stage.deliver(decision, kw.pop("before", lambda: None), **kw)


def test_a_delivered_run_binds_its_members_and_moves_the_pointer(run: Run) -> None:
    stage = run.open()
    run.stage_files(stage)
    stage.stage_path(None, "report.json", "report").write_bytes(b"{}")
    assert _deliver(stage) == DeliveryReceipt("delivered")
    assert stage.state == "delivered"
    assert run.latest.read_bytes() == b"r1\n"
    members = descriptor(run.folder / "r1")["artifacts"]
    assert [(m["path"], m["role"]) for m in members] == [
        ("a.csv", "table"),
        ("masked/b.csv", "table"),
        ("report.json", "report"),
    ]
    assert run.litter() == []


def test_a_table_the_decision_drops_is_removed_with_its_empty_folder(run: Run) -> None:
    stage = run.open()
    run.stage_files(stage)
    assert _deliver(stage, StageDecision(True, frozenset({"a"}))) == DeliveryReceipt("delivered")
    left = sorted(p.name for p in (run.folder / "r1").iterdir())
    assert left == [".decoy-publication-stage", DESCRIPTOR, "a.csv"]


def test_a_decision_that_delivers_nothing_aborts_and_touches_no_pointer(run: Run) -> None:
    run.latest.write_bytes(b"r0\n")
    stage = run.open()
    run.stage_files(stage)
    assert _deliver(stage, StageDecision(False)) == DeliveryReceipt("nothing")
    assert stage.state == "aborted" and run.latest.read_bytes() == b"r0\n"
    assert list((run.folder / "r1").iterdir()) == [] and run.litter() == []


def test_a_moved_pointer_stops_before_the_vault_or_the_bind(run: Run) -> None:
    stage = run.open()
    run.stage_files(stage)
    run.latest.write_bytes(b"r9\n")  # another run delivered after this one opened
    called: list[str] = []
    receipt = _deliver(stage, before=lambda: called.append("before"))
    assert receipt == DeliveryReceipt("nothing", MOVED) and called == []
    assert list((run.folder / "r1").iterdir()) == [] and run.litter() == []
    assert run.latest.read_bytes() == b"r9\n"


def test_two_runs_one_pointer_the_second_to_deliver_loses(run: Run) -> None:
    first, second = run.open("r1"), run.open("r2")
    for stage in (first, second):
        run.stage_files(stage)
    assert _deliver(second) == DeliveryReceipt("delivered")
    assert _deliver(first) == DeliveryReceipt("nothing", MOVED)
    assert run.latest.read_bytes() == b"r2\n"


def test_a_pointer_that_moves_after_the_compare_leaves_a_bound_folder_not_current(
    run: Run,
) -> None:
    stage = run.open()
    run.stage_files(stage)
    # The lock does not stop a writer that ignores it: the swap's own compare is the guard.
    receipt = _deliver(stage, before=lambda: run.latest.write_bytes(b"r9\n"))
    assert receipt == DeliveryReceipt("nothing", MOVED) and stage.state == "aborted"
    assert (run.folder / "r1" / DESCRIPTOR).exists() and run.latest.read_bytes() == b"r9\n"


def test_a_folder_that_holds_something_else_is_refused_with_f22s_code(run: Run) -> None:
    stage = run.open()
    run.stage_files(stage)
    (run.folder / "r1" / "stray.txt").write_bytes(b"x")
    receipt = _deliver(stage)
    assert receipt == DeliveryReceipt("nothing", reasons.decoy.PUBLICATION_TARGET_OCCUPIED)
    assert not run.latest.exists() and run.litter() == []


def test_a_declared_file_that_was_never_written_fails_the_publish(run: Run) -> None:
    stage = run.open()
    stage.stage_path("a", "a.csv")  # the writer failed before creating it
    assert _deliver(stage) == DeliveryReceipt("nothing", FAILED)
    assert not run.latest.exists() and run.litter() == []


def test_a_held_pointer_lock_refuses_with_the_lock_code_and_stages_nothing(run: Run) -> None:
    stage = run.open(lock_timeout_s=0.2)
    run.stage_files(stage)
    with run.pointer.locked(1.0):
        receipt = _deliver(stage)
    assert receipt == DeliveryReceipt("nothing", reasons.decoy.PUBLICATION_LOCK_TIMEOUT)
    assert run.litter() == [] and not run.latest.exists()


def test_before_visible_raising_aborts_and_the_error_comes_back_unchanged(run: Run) -> None:
    stage = run.open()
    run.stage_files(stage)
    seen: list[DeliveryReceipt] = []

    def boom() -> None:
        raise RuntimeError("evidence write failed")

    with pytest.raises(RuntimeError, match="evidence write failed"):
        _deliver(stage, before=boom, reconcile=seen.append)
    assert seen == [DeliveryReceipt("nothing")] and stage.state == "aborted"
    assert list((run.folder / "r1").iterdir()) == [] and not run.latest.exists()


def test_reconcile_runs_under_the_pointer_lock_with_the_final_receipt(run: Run) -> None:
    stage = run.open()
    run.stage_files(stage)
    seen: list[tuple[DeliveryReceipt, str]] = []

    def reconcile(receipt: DeliveryReceipt) -> None:
        try:
            with run.pointer.locked(0.1):
                held = "not held"
        except Exception as exc:
            held = type(exc).__name__
        seen.append((receipt, held))

    _deliver(stage, reconcile=reconcile)
    assert seen == [(DeliveryReceipt("delivered"), "LockTimeout")]


@pytest.mark.parametrize("swapped", [True, False])
def test_an_interrupt_at_the_visibility_point_is_judged_by_a_pointer_reread(
    run: Run, monkeypatch: pytest.MonkeyPatch, swapped: bool
) -> None:
    stage = run.open()
    run.stage_files(stage)
    real = HeldPointer.swap

    def interrupted(self: HeldPointer, expected: Any, new: str) -> Any:
        if swapped:
            real(self, expected, new)
        raise KeyboardInterrupt

    monkeypatch.setattr(HeldPointer, "swap", interrupted)
    seen: list[DeliveryReceipt] = []
    with pytest.raises(KeyboardInterrupt):
        _deliver(stage, reconcile=seen.append)
    if swapped:
        assert seen == [DeliveryReceipt("uncertain", UNCERTAIN)] and stage.state == "delivered"
    else:
        assert seen == [DeliveryReceipt("nothing")] and stage.state == "aborted"


def test_the_vault_is_published_before_the_bind_and_kept_when_the_swap_loses(run: Run) -> None:
    (run.base / "vaults").mkdir()
    stage = run.open()
    run.stage_files(stage)
    vault, _ = binding("ambient", run.base)
    stage.set_vault(vault)
    receipt = _deliver(stage, before=lambda: run.latest.write_bytes(b"r9\n"))
    assert receipt == DeliveryReceipt("nothing", MOVED)
    assert (run.base / "vaults" / "v.dcyvault").exists()  # the orphan the next run refuses
    assert descriptor(run.folder / "r1")["vault"] is not None


def test_a_delivered_run_records_its_vault_in_the_descriptor(run: Run) -> None:
    (run.base / "vaults").mkdir()
    stage = run.open()
    run.stage_files(stage)
    stage.set_vault(binding("ambient", run.base)[0])
    assert _deliver(stage) == DeliveryReceipt("delivered")
    assert descriptor(run.folder / "r1")["vault"]["sha256"]


def test_deliver_after_abort_is_refused_and_abort_after_delivered_is_a_no_op(run: Run) -> None:
    gone = run.open("r1")
    gone.abort()
    gone.abort()
    with pytest.raises(RuntimeError):
        _deliver(gone)
    kept = run.open("r2")
    run.stage_files(kept)
    _deliver(kept)
    kept.abort()
    assert kept.state == "delivered" and run.latest.read_bytes() == b"r2\n"
    with pytest.raises(RuntimeError):
        _deliver(kept)


def test_an_unreadable_pointer_refuses_at_open_before_a_stage_exists(run: Run) -> None:
    run.latest.symlink_to("elsewhere")
    with pytest.raises(PublicationFailed) as caught:
        run.open()
    assert caught.value.code == "publication_failed" and run.litter() == []


def test_a_stage_that_cannot_open_is_a_value_free_failure_with_the_errno(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _dir(run.base, "out/n/r1")

    def begin(*args: Any, **kwargs: Any) -> Any:
        raise PermissionError(errno.EACCES, "/secret/path")

    monkeypatch.setattr(out, "begin", begin)
    (run.folder / "r1").mkdir()
    with pytest.raises(PublicationFailed) as caught:
        DeliveryStage.open(out, run.pointer, "r1", "op-1")
    assert caught.value.receipt.os_error == "EACCES"
    assert "secret" not in str(caught.value)


def test_staging_rules_refuse_a_bad_path_a_repeat_with_another_table_and_an_empty_table(
    run: Run,
) -> None:
    stage = run.open()
    first = stage.stage_path("a", "x/a.csv")
    assert stage.stage_path("a", "x/a.csv") == first
    for call in (
        lambda: stage.stage_path("a", "../a.csv"),
        lambda: stage.stage_path("a", "/abs.csv"),
        lambda: stage.stage_path("b", "x/a.csv"),
        lambda: stage.stage_path("", "y.csv"),
    ):
        with pytest.raises(ValueError):
            call()


def test_every_value_free_delivery_error_carries_no_cause_or_context(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AT-27. The errors the stage raises itself, each built outside a handler."""
    run.latest.symlink_to("elsewhere")
    cases: list[Any] = []
    make: Callable[[], object]
    for make in (
        lambda: run.open(),
        lambda: DeliveryStage.open(_dir(run.base, "out/n/r1"), run.pointer, "bad\nid", "op"),
        lambda: DeliveryStage.open(_dir(run.base, "out/n/r1"), run.pointer, "r1", "bad op id"),
    ):
        with pytest.raises((PublicationFailed, ValueError)) as caught:
            make()
        cases.append(caught.value)
    run.latest.unlink()
    out = _dir(run.base, "out/n/r1")
    (run.folder / "r1").mkdir(exist_ok=True)
    for failure in (
        PermissionError(errno.EACCES, "/secret/path"),
        FileAccessDenied("targets.t.path"),
        FileAccessUnavailable("secret"),
    ):

        def begin(*args: Any, _failure: Exception = failure, **kwargs: Any) -> Any:
            raise _failure

        monkeypatch.setattr(out, "begin", begin)
        with pytest.raises(PublicationFailed) as caught:
            DeliveryStage.open(out, run.pointer, "r1", "op-1")
        cases.append(caught.value)
    stage = run.open("r2")
    for make in (
        lambda: stage.stage_path("a", "../a.csv"),
        lambda: stage.stage_path("", "a.csv"),
        lambda: StageDecision("yes", frozenset()),  # type: ignore[arg-type]
        lambda: StageDecision(True, {"a"}),  # type: ignore[arg-type]
    ):
        with pytest.raises(ValueError) as caught:
            make()
        cases.append(caught.value)
    stage.abort()
    for make in (lambda: stage.stage_path("a", "a.csv"), lambda: _deliver(stage)):
        with pytest.raises(RuntimeError) as caught:
            make()
        cases.append(caught.value)
    assert len(cases) == 12
    assert all(e.__cause__ is None and e.__context__ is None for e in cases)
    assert all(not any(word in str(e) for word in ("bad", "elsewhere", "secret")) for e in cases)


# -- AT-28: the outcome tables ---------------------------------------------------------------

BIND_ROWS = {
    "published": ("delivered", None),
    "already_committed": ("delivered", None),
    "commit_uncertain": ("uncertain", UNCERTAIN),
    "refused": ("nothing", None),
    "operation_conflict": ("nothing", CONFLICT),
    "failed": ("nothing", FAILED),
}
SWAP_ROWS = {
    "replaced": ("delivered", None),
    "stale": ("nothing", MOVED),
    "uncertain": ("uncertain", UNCERTAIN),
    "unknown": ("uncertain", UNCERTAIN),
    "failed": ("nothing", FAILED),
    "conflict": ("nothing", FAILED),
}
BIND_STATE = {k: state for k, (state, _) in BIND_ROWS.items()}
SWAP_STATE = {k: state for k, (state, _) in SWAP_ROWS.items()}


def test_each_outcome_and_each_swap_result_maps_to_exactly_one_state() -> None:
    """Plan 4.4 row by row: the state and the cause, not the state alone."""
    assert set(stage_module.BIND_VERDICTS) == set(get_args(Outcome))
    assert set(stage_module.SWAP_VERDICTS) == set(get_args(PointerResult))
    assert {k: (v.state, v.cause) for k, v in stage_module.BIND_VERDICTS.items()} == BIND_ROWS
    assert {k: (v.state, v.cause) for k, v in stage_module.SWAP_VERDICTS.items()} == SWAP_ROWS


@pytest.mark.parametrize("outcome", get_args(Outcome))
def test_deliver_maps_every_bind_outcome(
    run: Run, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    code = None if outcome in ("published", "already_committed") else "publication_failed"
    commit = SimpleNamespace(outcome=outcome, reason_code=code)
    monkeypatch.setattr(stage_module, "publish_unit", lambda *a, **k: commit)
    stage = run.open()
    receipt = _deliver(stage)
    assert receipt.state == BIND_STATE[outcome]
    assert (run.latest.exists()) == (BIND_STATE[outcome] != "nothing")
    if BIND_ROWS[outcome][1] is not None:
        assert receipt.cause == BIND_ROWS[outcome][1]
    if outcome == "commit_uncertain":
        assert stage.state == "delivered"


@pytest.mark.parametrize("result", get_args(PointerResult))
def test_deliver_maps_every_swap_result(
    run: Run, monkeypatch: pytest.MonkeyPatch, result: str
) -> None:
    monkeypatch.setattr(HeldPointer, "swap", lambda self, expected, new: result)
    stage = run.open()
    run.stage_files(stage)
    receipt = _deliver(stage)
    assert (receipt.state, receipt.cause) == SWAP_ROWS[result]
    assert stage.state == ("aborted" if receipt.state == "nothing" else "delivered")


def test_an_uncertain_bind_with_a_clean_swap_is_uncertain_not_delivered(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = SimpleNamespace(outcome="commit_uncertain", reason_code="publication_commit_uncertain")
    monkeypatch.setattr(stage_module, "publish_unit", lambda *a, **k: commit)
    assert _deliver(run.open()) == DeliveryReceipt("uncertain", UNCERTAIN)
    assert run.latest.read_bytes() == b"r1\n"


def test_an_outcome_with_no_row_fails_closed(run: Run, monkeypatch: pytest.MonkeyPatch) -> None:
    commit = SimpleNamespace(outcome="mystery", reason_code=None)
    monkeypatch.setattr(stage_module, "publish_unit", lambda *a, **k: commit)
    stage = run.open()
    with pytest.raises(KeyError):
        _deliver(stage)
    assert not run.latest.exists() and stage.state == "aborted"


# -- lock and prune failures, interrupts ------------------------------------------------------


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (FileAccessDenied("targets.t.path"), reasons.decoy.FILE_ACCESS_DENIED),
        (FileAccessUnavailable("secret"), reasons.decoy.PUBLICATION_LOCK_UNAVAILABLE),
    ],
)
def test_a_lock_the_policy_refuses_settles_nothing_with_a_code(
    run: Run, monkeypatch: pytest.MonkeyPatch, failure: Exception, code: Any
) -> None:
    stage = run.open()
    run.stage_files(stage)

    def refused(timeout_s: float) -> Any:
        raise failure

    monkeypatch.setattr(run.pointer, "locked", refused)
    seen: list[DeliveryReceipt] = []
    assert _deliver(stage, reconcile=seen.append) == DeliveryReceipt("nothing", code)
    assert seen == [DeliveryReceipt("nothing", code)] and stage.state == "aborted"
    assert run.litter() == [] and not run.latest.exists()


@pytest.mark.parametrize(
    "failure",
    [
        PermissionError(errno.EACCES, "/secret/path"),
        FileAccessDenied("t.p"),
        FileAccessUnavailable(),
    ],
)
def test_a_prune_that_fails_aborts_reconciles_and_settles_nothing(
    run: Run, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    stage = run.open()
    run.stage_files(stage)

    def drop(self: DeliveryStage, path: str) -> None:
        raise failure

    monkeypatch.setattr(DeliveryStage, "_drop", drop)
    seen: list[DeliveryReceipt] = []
    receipt = _deliver(stage, StageDecision(True, frozenset({"a"})), reconcile=seen.append)
    assert receipt == DeliveryReceipt("nothing", FAILED) and seen == [receipt]
    assert stage.state == "aborted" and run.litter() == [] and not run.latest.exists()


def _make_pointer_unreadable(run: Run) -> None:
    run.latest.unlink(missing_ok=True)
    run.latest.symlink_to("elsewhere")


def test_an_interrupt_inside_publish_unit_is_judged_by_the_reread(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bind may have happened: an unreadable pointer is `uncertain`, a readable one that does
    not name this run is `nothing`."""
    for unreadable in (False, True):
        stage = run.open(f"r{int(unreadable) + 1}")
        run.stage_files(stage)

        def interrupted(*args: Any, _unreadable: bool = unreadable, **kwargs: Any) -> Any:
            if _unreadable:
                _make_pointer_unreadable(run)
            raise KeyboardInterrupt

        monkeypatch.setattr(stage_module, "publish_unit", interrupted)
        seen: list[DeliveryReceipt] = []
        with pytest.raises(KeyboardInterrupt):
            _deliver(stage, reconcile=seen.append)
        want = DeliveryReceipt("uncertain", UNCERTAIN) if unreadable else DeliveryReceipt("nothing")
        assert seen == [want]
        run.latest.unlink(missing_ok=True)


def test_an_unreadable_pointer_after_the_bind_is_uncertain(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = run.open()
    run.stage_files(stage)

    def interrupted(self: HeldPointer, expected: Any, new: str) -> Any:
        _make_pointer_unreadable(run)
        raise KeyboardInterrupt

    monkeypatch.setattr(HeldPointer, "swap", interrupted)
    seen: list[DeliveryReceipt] = []
    with pytest.raises(KeyboardInterrupt):
        _deliver(stage, reconcile=seen.append)
    assert seen == [DeliveryReceipt("uncertain", UNCERTAIN)] and stage.state == "delivered"


def test_an_interrupt_before_the_bind_leaves_nothing_even_when_the_pointer_is_unreadable(
    run: Run,
) -> None:
    stage = run.open()
    run.stage_files(stage)

    def interrupted() -> None:
        _make_pointer_unreadable(run)
        raise KeyboardInterrupt

    seen: list[DeliveryReceipt] = []
    with pytest.raises(KeyboardInterrupt):
        _deliver(stage, before=interrupted, reconcile=seen.append)
    assert seen == [DeliveryReceipt("nothing")] and stage.state == "aborted"


def test_a_resume_whose_pointer_already_names_the_run_is_visible_after_an_early_interrupt(
    run: Run,
) -> None:
    """F23 resume (plan 7.1): `LATEST` naming the run means delivered, even before the bind."""
    run.latest.write_bytes(b"r1\n")
    stage = run.open("r1")
    run.stage_files(stage)

    def interrupted() -> None:
        raise KeyboardInterrupt

    seen: list[DeliveryReceipt] = []
    with pytest.raises(KeyboardInterrupt):
        _deliver(stage, before=interrupted, reconcile=seen.append)
    assert seen == [DeliveryReceipt("uncertain", UNCERTAIN)] and stage.state == "delivered"
