"""`DeliveryStage`: stage a run's outputs, then make them visible together (DELIV kind R).

Pattern: Git commit then ref update (the object is written before the ref moves). The unit is bound first (`publish_unit`: vault, then the
run folder), then the pointer moves with a compare-and-swap on the state read at `open`, all under
the pointer lock. A run is visible only when `LATEST` names it, so a lost swap leaves a bound but
unreferenced run folder, as an unreferenced Git commit is. The stage takes the decision as plain
data: `publication` (tier 2) cannot import `delivery` (tier 1). Contract: `docs/publication.md`.

Every refusal is a `DeliveryReceipt` or a fixed-text error: a reason code, never an exception's
text, a path or a table value.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Literal

from decoy_engine import reasons
from decoy_engine.fileaccess import (
    FileAccessDenied,
    FileAccessUnavailable,
    FileSeal,
    OutputDir,
    OutputTxn,
    StageDir,
    probe_claim,
)
from decoy_engine.publication._current import (
    CurrentPointer,
    HeldPointer,
    PointerResult,
    PointerState,
    PointerUnreadable,
    is_pointer_value,
    pointer_bytes,
)
from decoy_engine.publication._members import Member, check_member_paths, stage_file_path
from decoy_engine.publication._publish import failed_receipt, publish_unit
from decoy_engine.publication._types import (
    DEFAULT_LOCK_TIMEOUT_S,
    LOCK_ERRORS,
    CommitReceipt,
    Outcome,
    PublicationFailed,
    PublicationRequest,
    Role,
    VaultBinding,
    lock_reason,
)
from decoy_engine.reasons import ReasonCode

__all__ = [
    "BIND_VERDICTS",
    "SWAP_VERDICTS",
    "DeliveryReceipt",
    "DeliveryStage",
    "StageDecision",
    "StagedMember",
]

DeliveryState = Literal["delivered", "uncertain", "nothing"]
StageState = Literal["open", "delivering", "delivered", "aborted"]

_FAILED = reasons.decoy.PUBLICATION_FAILED
_UNCERTAIN = reasons.decoy.PUBLICATION_COMMIT_UNCERTAIN
_MOVED = reasons.decoy.DELIVERY_POINTER_MOVED

if TYPE_CHECKING:
    from pathlib import Path

_FS_ERRORS = (OSError, FileAccessDenied, FileAccessUnavailable)
MemberState = Literal["reserved", "completed", "failed", "omitted"]


@dataclass(frozen=True)
class DeliveryReceipt:
    """What `deliver` did. `uncertain` counts as delivered: the pointer moved, durability is
    unknown. `cause` is the reason code behind `uncertain` and `nothing`."""

    state: DeliveryState
    cause: ReasonCode | None = None


@dataclass(frozen=True)
class StageDecision:
    """The delivery decision as plain data: whether to deliver, and which tables go out."""

    deliver: bool
    delivered: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if type(self.deliver) is not bool:
            raise ValueError("invalid deliver")
        if type(self.delivered) is not frozenset or not all(type(t) is str for t in self.delivered):
            raise ValueError("invalid delivered")


@dataclass(frozen=True)
class _Verdict:
    state: DeliveryState
    cause: ReasonCode | None  # None on a refused bind: F22's own code, from the receipt


# The outcome tables (plan 4.4): one row per `Outcome` and per `PointerResult`. A value with no
# row is a KeyError at the lookup, never a silent state; the unit tests walk `get_args` of both.
BIND_VERDICTS: Final[Mapping[Outcome, _Verdict]] = {
    "published": _Verdict("delivered", None),
    "already_committed": _Verdict("delivered", None),
    "commit_uncertain": _Verdict("uncertain", _UNCERTAIN),
    "refused": _Verdict("nothing", None),
    "operation_conflict": _Verdict("nothing", reasons.decoy.PUBLICATION_OPERATION_CONFLICT),
    "failed": _Verdict("nothing", _FAILED),
}
SWAP_VERDICTS: Final[Mapping[PointerResult, _Verdict]] = {
    "replaced": _Verdict("delivered", None),
    "stale": _Verdict("nothing", _MOVED),
    "uncertain": _Verdict("uncertain", _UNCERTAIN),
    "unknown": _Verdict("uncertain", _UNCERTAIN),  # a lost answer: visible or not, unknown
    "failed": _Verdict("nothing", _FAILED),
    "conflict": _Verdict("nothing", _FAILED),
}


def _acquire(
    stack: ExitStack, pointer: CurrentPointer, timeout_s: float
) -> tuple[HeldPointer | None, ReasonCode | None]:
    """Take the pointer lock into `stack`. The handlers only pick a code, so no context survives."""
    held: HeldPointer | None = None
    code: ReasonCode | None = None
    try:
        held = stack.enter_context(pointer.locked(timeout_s))
    except LOCK_ERRORS as exc:
        code = lock_reason(exc)
    return held, code


def _combine(bind: _Verdict, swap: _Verdict) -> DeliveryReceipt:
    if swap.state == "nothing":
        return DeliveryReceipt("nothing", swap.cause)
    if "uncertain" in (bind.state, swap.state):
        return DeliveryReceipt("uncertain", _UNCERTAIN)
    return DeliveryReceipt("delivered")


def _refusal_code(commit: CommitReceipt) -> ReasonCode:
    return _FAILED if commit.reason_code is None else ReasonCode(commit.reason_code, "decoy")


def _errno_of(exc: BaseException) -> int | None:
    return exc.errno if isinstance(exc, OSError) else None


def _stage_failure(request: PublicationRequest, os_errno: int | None) -> PublicationFailed:
    """The value-free refusal for a file-system failure. Build it outside the `except` that saw
    the error, so no context rides along."""
    return PublicationFailed(str(_FAILED), failed_receipt(request, os_errno=os_errno))


class StagedMember:
    """One reserved file. The writer writes to `path` (a slot in the slots stage, so the file
    keeps its real name and extension), then calls `complete()` once the writer has returned and
    closed it; `fail()` marks it unusable and `omit()` drops an optional one that was never
    written. Completion is only ever this explicit call: nothing reads size or mtime."""

    def __init__(
        self,
        stage: DeliveryStage,
        table: str | None,
        member: Member,
        slot: StageDir,
        path: Path,
    ) -> None:
        self._stage = stage
        self.table, self.member, self.slot, self.path = table, member, slot, path
        self.name = member.path.rpartition("/")[2]
        self.state: MemberState = "reserved"
        self.seal: FileSeal | None = None  # set when the claim succeeded: the file is in the unit

    def complete(self) -> None:
        """Claim the written file into the unit stage. Raises `ValueError` (value-free) when no
        file is at the slot, and `PublicationFailed` when the target refuses the name (for
        example a case-insensitive volume that already holds it)."""
        self._stage._complete(self)

    def fail(self) -> None:
        """The writer failed: remove the slot file if it is there and never bind the member."""
        self._stage._fail(self)

    def omit(self) -> None:
        """Drop an optional member whose writer produced nothing (a quarantine run with no
        rows). Only a reserved, unclaimed member can be omitted."""
        self._stage._omit(self)


class DeliveryStage:
    """One run folder's stage and its pointer. States `open -> delivering -> delivered |
    aborted`; `deliver` after `abort` is refused and `abort` after `delivered` is a no-op."""

    def __init__(
        self,
        out: OutputDir,
        txn: OutputTxn,
        slots: OutputTxn,
        pointer: CurrentPointer,
        expected: PointerState,
        run_id: str,
        request: PublicationRequest,
    ) -> None:
        self._out, self._txn, self._slots, self._pointer = out, txn, slots, pointer
        self._expected, self._run_id, self._request = expected, run_id, request
        self._members: list[StagedMember] = []
        self._dirs: dict[str, StageDir] = {}  # "a/b/" -> the unit folder, made by `reserve`
        self._next_slot = 1
        self._state: StageState = "open"
        self._crossed = False  # set once `publish_unit` may have bound the unit
        self._receipt: DeliveryReceipt | None = None
        self._reconciled = False
        self._delivered: frozenset[str] = frozenset()

    @classmethod
    def open(
        cls,
        out: OutputDir,
        pointer: CurrentPointer,
        run_id: str,
        operation_id: str,
        *,
        lock_timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
    ) -> DeliveryStage:
        """Check the destination, read the pointer (the state `deliver` compares against), open
        the unit stage and the slots stage beside the run folder, and probe that the target can
        claim files. A destination that is not the run's folder is a `ValueError` before any
        read, lock or stage. An unreadable pointer, a stage that cannot open or a target that
        cannot hard-link (named limit `delivery_links_unsupported`) raises `PublicationFailed`
        before a writer runs."""
        request = PublicationRequest(operation_id, lock_timeout_s=lock_timeout_s)
        if not is_pointer_value(run_id):
            raise ValueError("invalid run_id")
        if not _names_run_folder(out, pointer, run_id):
            raise ValueError("run_id does not name the output folder")  # the pointer must bind it
        expected: PointerState | None = None
        txn: OutputTxn | None = None
        slots: OutputTxn | None = None
        failed, os_errno = False, None
        try:
            expected = pointer.read()
            txn = out.begin("dir", "exclusive", label="publication")
            slots = out.begin("dir", "exclusive", label="delivery_slots")
            probe_claim(slots, txn)
        except PointerUnreadable:
            failed = True
        except _FS_ERRORS as exc:  # LinkUnsupported is an OSError: its errno names the limit
            failed, os_errno = True, _errno_of(exc)
        except BaseException:
            _abort_all(txn, slots)
            raise
        if failed or expected is None or txn is None or slots is None:
            _abort_all(txn, slots)
            raise _stage_failure(request, os_errno)
        return cls(out, txn, slots, pointer, expected, run_id, request)

    @property
    def state(self) -> StageState:
        return self._state

    def _require_open(self) -> None:
        if self._state != "open":
            raise RuntimeError("the delivery stage is not open")

    def set_vault(self, binding: VaultBinding) -> None:
        """Bind the run's vault; `publish_unit` publishes it create-only before the bind (Q6)."""
        self._require_open()
        self._request = replace(self._request, vault=binding)

    def reserve(self, table: str | None, relpath: str, role: Role = "table") -> StagedMember:
        """Reserve one member and return its handle. `table` is the table the file belongs to;
        `None` marks a file that is always delivered, like the report. Nothing exists at
        `.path`: the unit's folders are made (an exact-name folder is reused), and the writer's
        slot is a numbered folder in the slots stage. A duplicate, prefix clash or bad path is a
        value-free `ValueError`; a name the target treats as taken, or a strict policy (no local
        path), is `PublicationFailed`. A failed call removes only the folders it made."""
        self._require_open()
        member = Member(relpath, role)  # the one path rule, value-free
        if table is not None and not table:
            raise ValueError("invalid table")
        check_member_paths(
            [m.member.path for m in self._members] + [member.path],
            "path conflicts with a reserved path",
        )
        made: list[str] = []
        failed, os_errno = False, None
        try:
            slot_root = self._slots.local_stage_path()
            self._folders(member.path.split("/")[:-1], made)
            slot_name = f"s{self._next_slot}"
            slot = self._slots.create_dir(slot_name)
            path = stage_file_path(slot_root, f"{slot_name}/{member.path.rpartition('/')[2]}")
        except _FS_ERRORS as exc:
            failed, os_errno = True, _errno_of(exc)
        except BaseException:
            self._unmake(made)
            raise
        if failed:
            self._unmake(made)
            raise _stage_failure(self._request, os_errno)
        self._next_slot += 1
        staged = StagedMember(self, table, member, slot, path)
        self._members.append(staged)
        return staged

    def _folders(self, parts: list[str], made: list[str]) -> StageDir:
        """The unit folder for `parts`, made folder by folder and recorded at the moment each
        exists (in `made` too, so a later failure in the call can remove it)."""
        holder: StageDir = self._txn
        prefix = ""
        for part in parts:
            prefix = f"{prefix}{part}/"
            if prefix not in self._dirs:
                self._dirs[prefix] = holder.create_dir(part)
                made.append(prefix)
            holder = self._dirs[prefix]
        return holder

    def _unmake(self, made: list[str]) -> None:
        """Remove the folders one `reserve` call made, deepest first. A failing removal is
        dropped: the original refusal is what the caller sees and the stage abort cleans up."""
        for prefix in reversed(made):
            self._dirs.pop(prefix, None)
            try:
                self._holder(prefix).remove(prefix.rstrip("/").rpartition("/")[2])
            except _FS_ERRORS:
                pass

    def _holder(self, path: str) -> StageDir:
        """The unit folder that holds `path` (a file, or a folder written with a trailing `/`)."""
        parent = path.rstrip("/").rpartition("/")[0]
        return self._dirs[f"{parent}/"] if parent else self._txn

    def _complete(self, m: StagedMember) -> None:
        self._require_open()
        if m.state != "reserved":
            raise RuntimeError("the member is not reserved")
        missing, failed, os_errno = False, False, None
        try:
            if m.slot.seal_of(m.name) is None:
                missing = True
            else:
                m.seal = self._holder(m.member.path).claim_from(m.slot, m.name, m.name)
        except _FS_ERRORS as exc:  # a taken name is FileExistsError, an OSError with EEXIST
            failed, os_errno = True, _errno_of(exc)
        if missing:
            raise ValueError("the member was not written")
        if failed:
            m.state = "failed"
            raise _stage_failure(self._request, os_errno)
        m.state = "completed"

    def _fail(self, m: StagedMember) -> None:
        m.state = "failed"
        try:
            m.slot.remove(m.name)
        except _FS_ERRORS:
            pass  # never written, or already gone; the slots stage is discarded anyway

    def _omit(self, m: StagedMember) -> None:
        self._require_open()
        if m.state != "reserved" or m.seal is not None:
            raise RuntimeError("only a reserved member can be omitted")
        m.state = "omitted"

    def staged_path(self, table: str) -> Path:
        """The reserved destination of `table` in the unit stage (its first reservation),
        whatever the completion state. A stable path for the quarantine alias guard; it is not
        where the writer writes and never says whether a file exists."""
        for m in self._members:
            if m.table == table:
                return stage_file_path(self._txn.local_stage_path(), m.member.path)
        raise ValueError("no such table")

    def stage_dir(self) -> Path:
        """The slots stage root, for spill and temporary files: it is always discarded, never
        the unit stage the closed-stage walk checks."""
        return stage_file_path(self._slots.local_stage_path(), ".")

    def abort(self) -> None:
        """Remove both stages. The pointer is never touched; a no-op once delivered."""
        if self._state in ("delivered", "aborted"):
            return
        _abort_all(self._txn, self._slots)
        self._state = "aborted"

    def deliver(
        self,
        decision: StageDecision,
        before_visible: Callable[[], None],
        reconcile: Callable[[DeliveryReceipt], None] | None = None,
    ) -> DeliveryReceipt:
        """Prune the tables `decision` does not deliver, then under the pointer lock: compare the
        pointer, check every claimed member, call `before_visible`, bind the unit, swap the
        pointer. `reconcile` gets the final receipt while the lock is still held and must not
        raise. A `BaseException` after the lock is held is judged and reconciled inside the lock,
        then re-raised."""
        self._require_open()
        if not decision.deliver:
            self.abort()
            return DeliveryReceipt("nothing")
        self._state = "delivering"
        try:
            if not self._prune(decision.delivered):
                return self._settle(DeliveryReceipt("nothing", _FAILED), reconcile)
            with ExitStack() as stack:
                held, refusal = _acquire(stack, self._pointer, self._request.lock_timeout_s)
                if held is None:
                    return self._settle(DeliveryReceipt("nothing", refusal), reconcile)
                try:
                    return self._settle(self._visible(held, before_visible), reconcile)
                except BaseException:
                    if self._receipt is None:  # an interrupt or a bug: judge it under the lock
                        self._settle(self._after_interrupt(locked=True), reconcile)
                    raise
        except BaseException:
            if self._receipt is None:  # before the lock, or a second interrupt while settling
                self._settle(self._after_interrupt(locked=False), reconcile)
            raise

    def _visible(self, held: HeldPointer, before_visible: Callable[[], None]) -> DeliveryReceipt:
        now = self._read()
        if now is None:
            return DeliveryReceipt("nothing", _FAILED)
        if now.raw != self._expected.raw:
            return DeliveryReceipt("nothing", _MOVED)
        if not self._sealed():
            return DeliveryReceipt("nothing", _FAILED)
        before_visible()
        self._crossed = True
        commit = publish_unit(self._out, self._txn, self._request, members=self._kept())
        bind = BIND_VERDICTS[commit.outcome]
        if bind.state == "nothing":
            return DeliveryReceipt("nothing", bind.cause or _refusal_code(commit))
        swap = SWAP_VERDICTS[held.swap(self._expected, self._run_id)]
        if swap.state == "nothing" and self._names_run(self._expected.raw):
            # A replay (F23): the pointer already named this run, so a failed rewrite changes
            # nothing while it still does. The row assumes the folder is not current.
            now = self._read()
            if now is None:  # an unreadable pointer cannot say the run is not visible
                swap = _Verdict("uncertain", _UNCERTAIN)
            elif self._names_run(now.raw):
                swap = _Verdict("delivered", None)
        return _combine(bind, swap)

    def _names_run(self, raw: bytes | None) -> bool:
        return raw is not None and raw == pointer_bytes(self._run_id)

    def _read(self) -> PointerState | None:
        state: PointerState | None = None
        try:
            state = self._pointer.read()
        except PointerUnreadable:
            pass
        return state

    def _after_interrupt(self, *, locked: bool) -> DeliveryReceipt:
        """4.7 rule 2: under the held lock, `LATEST` naming this run means it is visible, with
        durability unknown. An unreadable pointer cannot prove it is not. Before the bind point
        the pointer is re-read only when it already named this run (a resume, plan 7.1). With no
        lock held nothing is read: the run counts as visible only for a resume."""
        named = pointer_bytes(self._run_id)
        if not self._crossed and self._expected.raw != named:
            return DeliveryReceipt("nothing")
        if not locked:
            return DeliveryReceipt("uncertain", _UNCERTAIN)
        now = self._read()
        if now is None or now.raw == named:
            return DeliveryReceipt("uncertain", _UNCERTAIN)
        return DeliveryReceipt("nothing")

    def _settle(
        self, receipt: DeliveryReceipt, reconcile: Callable[[DeliveryReceipt], None] | None
    ) -> DeliveryReceipt:
        self._receipt = receipt
        if receipt.state == "nothing" or not self._crossed:
            # Never bound: a fresh stage must not outlive a receipt that says the run is visible
            # (a resume interrupted before the bind). A no-op once the unit is bound.
            self._txn.abort()
        self._slots.abort()  # writer litter and unclaimed slots never outlive the call
        self._state = "aborted" if receipt.state == "nothing" else "delivered"
        if reconcile is not None and not self._reconciled:
            self._reconciled = True
            reconcile(receipt)
        return receipt

    def _kept(self) -> list[Member]:
        return sorted((m.member for m in self._members if self._is_kept(m)), key=lambda x: x.path)

    def _is_kept(self, m: StagedMember) -> bool:
        return m.state == "completed" and (m.table is None or m.table in self._delivered)

    def _prune(self, delivered: frozenset[str]) -> bool:
        """Remove from the unit only the files this stage claimed for tables not delivered, then
        the folders left with no kept member. `False` when a removal failed or a member of a
        delivered table was never completed. A failed, omitted or pending reservation never
        authorizes a removal: its name may resolve to another member's file."""
        self._delivered = delivered
        wanted = [m for m in self._members if m.table is None or m.table in delivered]
        if any(m.state in ("reserved", "failed") for m in wanted):
            return False
        failed = False
        try:
            for m in self._members:
                if m.seal is not None and m not in wanted:
                    self._holder(m.member.path).remove(m.name)
            kept = [m.member.path for m in wanted if m.state == "completed"]
            for folder in sorted(self._dirs, key=len, reverse=True):
                if not any(p.startswith(folder) for p in kept):
                    self._holder(folder).remove(folder.rstrip("/").rpartition("/")[2])
        except _FS_ERRORS:
            failed = True
        return not failed

    def _sealed(self) -> bool:
        """Under the lock, before the bind: every kept member is still the inode that was
        claimed, with one link and mode 0600, and no two members are one inode."""
        seen: set[tuple[int, int]] = set()
        ok = True
        try:
            for m in self._members:
                if not self._is_kept(m):
                    continue
                now = self._holder(m.member.path).seal_of(m.name)
                ok = ok and now is not None and now == m.seal
                if now is not None:
                    seen.add((now.dev, now.ino))
        except _FS_ERRORS:
            ok = False
        return ok and len(seen) == sum(1 for m in self._members if self._is_kept(m))


def _abort_all(*stages: OutputTxn | None) -> None:
    for stage in stages:
        if stage is not None:
            stage.abort()


def _names_run_folder(out: OutputDir, pointer: CurrentPointer, run_id: str) -> bool:
    """Whether `out` is exactly the run's folder in the pointer's own parent: the leaf equals the
    run id, and both parents are one folder (a symlinked spelling of it counts under the ambient
    policy; a strict root refuses a link beneath it, which reads as a mismatch)."""
    if out.leaf != run_id:
        return False
    same = False
    try:
        same = out.parent_identity() == pointer.leaf_dir.parent_identity()
    except _FS_ERRORS:
        pass
    return same
