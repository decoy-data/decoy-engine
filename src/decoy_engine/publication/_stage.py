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

import os
import unicodedata
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, Literal

from decoy_engine import reasons
from decoy_engine.fileaccess import (
    FileAccessDenied,
    FileAccessUnavailable,
    OutputDir,
    OutputTxn,
    StageDir,
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
from decoy_engine.publication._members import Member
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
]

DeliveryState = Literal["delivered", "uncertain", "nothing"]
StageState = Literal["open", "delivering", "delivered", "aborted"]

_FAILED = reasons.decoy.PUBLICATION_FAILED
_UNCERTAIN = reasons.decoy.PUBLICATION_COMMIT_UNCERTAIN
_MOVED = reasons.decoy.DELIVERY_POINTER_MOVED
_UNWRITTEN_MTIME_NS = 0  # a pre-created member keeps this stamp until a writer opens it


def _fold(path: str) -> str:
    """The key under which a case-insensitive or normalizing file system sees `path` as one name."""
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", path).casefold())


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


class DeliveryStage:
    """One run folder's stage and its pointer. States `open -> delivering -> delivered |
    aborted`; `deliver` after `abort` is refused and `abort` after `delivered` is a no-op."""

    def __init__(
        self,
        out: OutputDir,
        txn: OutputTxn,
        pointer: CurrentPointer,
        expected: PointerState,
        run_id: str,
        request: PublicationRequest,
    ) -> None:
        self._out, self._txn, self._pointer = out, txn, pointer
        self._expected, self._run_id, self._request = expected, run_id, request
        self._staged: dict[str, tuple[str | None, Role]] = {}
        self._dirs: dict[str, StageDir] = {}
        self._names: dict[str, tuple[str, bool]] = {}  # folded path -> (spelling, is_folder)
        self._members: list[Member] = []
        self._state: StageState = "open"
        self._crossed = False  # set once `publish_unit` may have bound the unit

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
        """Read the pointer (the state `deliver` compares against), then open the stage beside
        the run folder. An unreadable pointer, or a stage that cannot open, raises
        `PublicationFailed` before anything is staged."""
        request = PublicationRequest(operation_id, lock_timeout_s=lock_timeout_s)
        if not is_pointer_value(run_id):
            raise ValueError("invalid run_id")
        if out.locator.rstrip("/\\").replace("\\", "/").rpartition("/")[2] != run_id:
            raise ValueError("run_id does not name the output folder")  # the pointer must bind it
        expected: PointerState | None = None
        txn: OutputTxn | None = None
        os_errno: int | None = None
        try:
            expected = pointer.read()
            txn = out.begin("dir", "exclusive", label="publication")
        except PointerUnreadable:
            pass
        except (OSError, FileAccessDenied, FileAccessUnavailable) as exc:
            os_errno = exc.errno if isinstance(exc, OSError) else None
        if expected is None or txn is None:
            raise PublicationFailed(str(_FAILED), failed_receipt(request, os_errno=os_errno))
        return cls(out, txn, pointer, expected, run_id, request)

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

    def stage_path(self, table: str | None, relpath: str, role: Role = "table") -> Path:
        """The local path of one staged file, its folders made and the file created owner-only
        (`0600`, whatever the umask). `table` is the table the file belongs to; `None` marks a
        file that is always delivered, like the report. A path that is the same file as a staged
        one on a case-insensitive file system, or a file where a folder is staged (or the
        reverse), is refused before the stage records or creates anything."""
        self._require_open()
        member = Member(relpath, role)  # the one path rule, value-free
        if table is not None and not table:
            raise ValueError("invalid table")
        local = Path(self._txn.local_stage_path()) / member.path
        known = self._staged.get(member.path)
        if known is not None:
            if known != (table, role):
                raise ValueError("path already staged")
            return local
        parts = member.path.split("/")
        self._check_names(parts)
        holder: StageDir = self._txn
        prefix = ""
        for part in parts[:-1]:
            prefix = f"{prefix}{part}/"
            if prefix not in self._dirs:
                self._dirs[prefix] = holder.create_dir(part)  # recorded once it exists
                self._names[_fold(prefix.rstrip("/"))] = (prefix.rstrip("/"), True)
            holder = self._dirs[prefix]
        os.close(holder.create_file(parts[-1]))
        os.utime(local, ns=(0, _UNWRITTEN_MTIME_NS))  # `_unwritten` reads this back
        self._staged[member.path] = (table, role)
        self._names[_fold(member.path)] = (member.path, False)
        return local

    def _check_names(self, parts: list[str]) -> None:
        """Refuse a name that aliases a staged file or folder, or sits across the file and folder
        divide. Folders on the way are compared as folders, the last part as a file."""
        for depth in range(1, len(parts) + 1):
            spelling = "/".join(parts[:depth])
            held = self._names.get(_fold(spelling))
            if held is not None and held != (spelling, depth < len(parts)):
                raise ValueError("path conflicts with a staged path")

    def abort(self) -> None:
        """Remove the stage. The pointer is never touched; a no-op once delivered."""
        if self._state in ("delivered", "aborted"):
            return
        self._txn.abort()
        self._state = "aborted"

    def deliver(
        self,
        decision: StageDecision,
        before_visible: Callable[[], None],
        reconcile: Callable[[DeliveryReceipt], None] | None = None,
    ) -> DeliveryReceipt:
        """Prune the tables `decision` does not deliver, then under the pointer lock: compare the
        pointer, call `before_visible`, bind the unit, swap the pointer. `reconcile` gets the
        final receipt while the lock is still held and must not raise. A `BaseException` once the
        bind may have happened is judged by a pointer re-read, reconciled, and re-raised."""
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
                return self._settle(self._visible(held, before_visible), reconcile)
        except BaseException:
            if self._state == "delivering":  # not yet settled: an interrupt or a bug, never a row
                self._settle(self._after_interrupt(), reconcile)
            raise

    def _visible(self, held: HeldPointer, before_visible: Callable[[], None]) -> DeliveryReceipt:
        now = self._read()
        if now is None:
            return DeliveryReceipt("nothing", _FAILED)
        if now.raw != self._expected.raw:
            return DeliveryReceipt("nothing", _MOVED)
        before_visible()
        self._crossed = True
        commit = publish_unit(self._out, self._txn, self._request, members=self._members)
        bind = BIND_VERDICTS[commit.outcome]
        if bind.state == "nothing":
            return DeliveryReceipt("nothing", bind.cause or _refusal_code(commit))
        swap = SWAP_VERDICTS[held.swap(self._expected, self._run_id)]
        if swap.state == "nothing" and self._names_run(self._expected.raw):
            # A replay (F23): the pointer already named this run, so a failed rewrite changes
            # nothing while it still does. The row assumes the folder is not current.
            now = self._read()
            if now is not None and self._names_run(now.raw):
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

    def _after_interrupt(self) -> DeliveryReceipt:
        """4.7 rule 2: under the held lock, `LATEST` naming this run means it is visible, with
        durability unknown. An unreadable pointer cannot prove it is not. Before the bind point
        the pointer is re-read only when it already named this run (a resume, plan 7.1)."""
        named = pointer_bytes(self._run_id)
        if not self._crossed and self._expected.raw != named:
            return DeliveryReceipt("nothing")
        now = self._read()
        if now is None or now.raw == named:
            return DeliveryReceipt("uncertain", _UNCERTAIN)
        return DeliveryReceipt("nothing")

    def _settle(
        self, receipt: DeliveryReceipt, reconcile: Callable[[DeliveryReceipt], None] | None
    ) -> DeliveryReceipt:
        if receipt.state == "nothing" or not self._crossed:
            # Never bound: a fresh stage must not outlive a receipt that says the run is visible
            # (a resume interrupted before the bind). A no-op once the unit is bound.
            self._txn.abort()
        self._state = "aborted" if receipt.state == "nothing" else "delivered"
        if reconcile is not None:
            reconcile(receipt)
        return receipt

    def _holder(self, path: str) -> StageDir:
        """The stage folder that holds `path` (a file, or a folder written with a trailing `/`)."""
        parent = path.rstrip("/").rpartition("/")[0]
        return self._dirs[f"{parent}/"] if parent else self._txn

    def _prune(self, delivered: frozenset[str]) -> bool:
        """Remove the staged files of tables not delivered, then the folders left with no
        member; set the unit's members. `False` when a removal failed."""
        keep = sorted(
            p for p, (table, _) in self._staged.items() if table is None or table in delivered
        )
        failed = False
        try:
            for path in self._staged.keys() - set(keep):
                self._drop(path)
            for folder in sorted(self._dirs, key=len, reverse=True):
                if not any(p.startswith(folder) for p in keep):
                    self._drop(folder)
        except (OSError, FileAccessDenied, FileAccessUnavailable):
            failed = True
        self._members = [Member(p, self._staged[p][1]) for p in keep]
        return not failed and not any(self._unwritten(p) for p in keep)

    def _unwritten(self, path: str) -> bool:
        """Whether a declared file still has the empty, never-opened stamp `stage_path` gave it:
        its writer failed before writing. A written empty file has a fresh mtime."""
        try:
            seen = (Path(self._txn.local_stage_path()) / path).stat()
        except OSError:
            return True
        return seen.st_size == 0 and seen.st_mtime_ns == _UNWRITTEN_MTIME_NS

    def _drop(self, path: str) -> None:
        try:
            self._holder(path).remove(path.rstrip("/").rpartition("/")[2])
        except FileNotFoundError:
            pass  # a writer that failed before creating its file
