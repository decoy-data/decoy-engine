"""Shared setup for the delivery stage tests: a project folder, its pointer, and member helpers.

The stage writes local paths, so these cases run under the ambient policy. A run folder is the
empty folder P4 makes; `LATEST` is the managed pointer beside it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from decoy_engine import reasons
from decoy_engine.fileaccess import FileRequest, FileRole
from decoy_engine.fileaccess._local import LocalFileAccess
from decoy_engine.publication import (
    CurrentPointer,
    DeliveryStage,
    LocalPointerStore,
    StageDecision,
)

MOVED = reasons.decoy.DELIVERY_POINTER_MOVED
FAILED = reasons.decoy.PUBLICATION_FAILED
UNCERTAIN = reasons.decoy.PUBLICATION_COMMIT_UNCERTAIN
CONFLICT = reasons.decoy.PUBLICATION_OPERATION_CONFLICT
EVERYTHING = StageDecision(True, frozenset({"a", "b"}))


def dir_at(base: Path, rel: str) -> Any:
    req = FileRequest(FileRole.TARGET_OUTPUT, "write", str(base / rel), "targets.t.path")
    return LocalFileAccess().output_dir(req)


class Run:
    """One project folder `out/n` with its pointer, and a way to open runs against it."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.folder = base / "out" / "n"
        self.folder.mkdir(parents=True)
        leaf = dir_at(base, "out/n/LATEST")
        self.pointer = CurrentPointer(LocalPointerStore(leaf), leaf)
        self.latest = self.folder / "LATEST"

    def open(self, run_id: str = "r1", **kw: Any) -> DeliveryStage:
        (self.folder / run_id).mkdir(exist_ok=True)
        return DeliveryStage.open(
            dir_at(self.base, f"out/n/{run_id}"), self.pointer, run_id, f"op-{run_id}", **kw
        )

    def stage_files(self, stage: DeliveryStage) -> None:
        put(stage, "a", "a.csv", b"a1\n")
        put(stage, "b", "masked/b.csv", b"b1\n")

    def litter(self) -> list[str]:
        return sorted(p.name for p in self.folder.iterdir() if p.name.startswith("._decoy"))


def put(stage: DeliveryStage, table: str | None, rel: str, data: bytes, role: Any = "table") -> Any:
    """Reserve one member, write it where the stage says, and complete it."""
    member = stage.reserve(table, rel, role)
    member.path.write_bytes(data)
    member.complete()
    return member


def deliver(stage: DeliveryStage, decision: StageDecision = EVERYTHING, **kw: Any) -> Any:
    return stage.deliver(decision, kw.pop("before", lambda: None), **kw)


def volume_is_case_sensitive(folder: Path) -> bool:
    """Measure the target volume with two exclusive creates of one name in two cases."""
    import os

    probe = folder / "CaseProbe"
    probe.write_bytes(b"")
    try:
        try:
            os.close(os.open(folder / "caseprobe", os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            return False
        (folder / "caseprobe").unlink()
        return True
    finally:
        probe.unlink()


def unit_dir(stage: DeliveryStage) -> Path:
    """The disk path of the unit stage (ambient policy only)."""
    return Path(stage._txn.local_stage_path())
