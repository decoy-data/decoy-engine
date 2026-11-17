"""F26 stage reclaim: `fileaccess.reclaim_stages` judges dead `publication` stages (plan 6.1).

Plan `docs/plans/2026-11-16-f26-v1-rescope.md` (revision 6.1) G1, G3, G5, 3.1 and 4. E2a lands
the preview (`apply=False`) cells: AT-E5 non-removal, AT-E6, AT-E8, AT-E9 and AT-E10. Every tree
is the test's own `tmp_path`; the only process outside the test is a `LiveWriter` child.
"""

from __future__ import annotations

import errno
import fcntl
import os
import time
from pathlib import Path
from typing import Any

import pytest

from decoy_engine.fileaccess import ReclaimOutcome, ReclaimReport, reclaim_stages
from tests.fileaccess.publication._reclaim_support import (
    PENDING,
    RECLAIM,
    LiveWriter,
    make_stage,
    needs_root,
    snapshot,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX reclaim")

FOREIGN_UID = 4242


def _record_opens(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Names (last components) passed to `os.open` from here on."""
    seen: list[str] = []
    real = os.open

    def recording(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        seen.append(os.path.basename(os.fsdecode(path)))
        return real(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", recording)
    return seen


def _only(report: ReclaimReport, **expected: int) -> None:
    """Every count of `report` is zero except the ones named."""
    counts = {o.value: report.count(o) for o in ReclaimOutcome}
    counts["scope_unavailable"] = report.scope_unavailable
    assert counts == {name: expected.get(name, 0) for name in counts}


def test_scope_exact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AT-E5, preview cells: only exact 0700 owned stages with a valid marker are eligible;
    nothing else is opened where it must not be, and nothing changes."""
    scope = tmp_path / "out"
    scope.mkdir()
    unit = scope / "run-1"
    unit.mkdir()
    (unit / "_decoy_publication.json").write_text("{}")
    (unit / "t.parquet").write_bytes(b"PAR1")
    (scope / ".run-1.decoy-lock").write_bytes(b"")
    (scope / "_decoy_stage_0123456789ab").write_bytes(b"file stage")
    (scope / "notes.txt").write_text("user file")
    malformed = [
        f"{prefix}{token}"
        for prefix in (PENDING, RECLAIM)
        for token in ("0123456789a", "0123456789abc", "0123456789AB", "0123456789ab\n")
    ]
    for name in malformed:
        make_stage(scope, prefix="", token=name)
    data = tmp_path / "data"
    data.mkdir()
    (data / "rows.csv").write_text("a,b\n")
    os.symlink(data, scope / f"{PENDING}aaaaaaaaaaaa")
    (scope / f"{PENDING}bbbbbbbbbbbb").write_bytes(b"a regular file with a stage name")
    make_stage(scope, token="cccccccccccc", mode=0o755)
    make_stage(scope, token="dddddddddddd", files=("t.parquet", "_decoy_publication.json"))
    linked = make_stage(scope, token="eeeeeeeeeeee")
    os.symlink(data, linked / "link")
    os.link(data / "rows.csv", linked / "hard")
    foreign = None
    if needs_root() is None:
        foreign = make_stage(scope, token="ffffffffffff")
        os.chown(foreign, FOREIGN_UID, FOREIGN_UID)
    before = snapshot(tmp_path)

    opened = _record_opens(monkeypatch)
    report = reclaim_stages(scope, apply=False, min_age_s=0)

    _only(report, eligible=2, unproven=3, foreign=1 if foreign else 0)
    assert snapshot(tmp_path) == before
    assert f"{PENDING}dddddddddddd" in opened and f"{PENDING}eeeeeeeeeeee" in opened
    never = {*malformed, f"{PENDING}aaaaaaaaaaaa", f"{PENDING}bbbbbbbbbbbb", "link", "hard"}
    never |= {f"{PENDING}cccccccccccc", "run-1", "notes.txt", "rows.csv"}
    if foreign is not None:
        never.add(foreign.name)
    assert not never & set(opened)


def test_preview_changes_nothing(tmp_path: Path) -> None:
    """AT-E6: a preview finds the dead stage and leaves names, inodes, modes and times alone."""
    make_stage(tmp_path, files=("a.parquet", "b.parquet"))
    before = snapshot(tmp_path)
    _only(reclaim_stages(tmp_path, apply=False, min_age_s=0), eligible=1)
    assert snapshot(tmp_path) == before  # no lock file, no reclaim name, nothing touched


@pytest.mark.parametrize("cell", ["fresh", "future_mtime", "pre_lock_engine", "deep_write"])
def test_young_stage_kept(tmp_path: Path, cell: str) -> None:
    """AT-E8: a stage any entry of which changed inside the grace is `young`."""
    grace: float = 3600  # the default
    if cell == "fresh":
        make_stage(tmp_path)
    elif cell == "future_mtime":
        stage = make_stage(tmp_path)
        ahead = time.time() + 7200
        for path in (*stage.iterdir(), stage):
            os.utime(path, (ahead, ahead))
    elif cell == "pre_lock_engine":  # what engine 0.27.0 leaves: no lock and no marker
        make_stage(tmp_path, marker=False)
    else:
        # ctime cannot be set back, so the grace is scaled down instead: the top of the tree is
        # older than it, and one file two levels down changed just now.
        stage = make_stage(tmp_path, files=())
        (stage / "a" / "b").mkdir(parents=True)
        (stage / "a" / "b" / "t.parquet").write_bytes(b"PAR1")
        time.sleep(1.6)
        grace = 1.0
        _only(reclaim_stages(tmp_path, apply=False, min_age_s=5.0), young=1)  # sanity
        with open(stage / "a" / "b" / "t.parquet", "ab") as late:
            late.write(b"more")
    before = snapshot(tmp_path)
    _only(reclaim_stages(tmp_path, apply=False, min_age_s=grace), young=1)
    assert snapshot(tmp_path) == before


def _force_exclusive(monkeypatch: pytest.MonkeyPatch, error: OSError) -> list[int]:
    """The cleaner's `LOCK_EX|LOCK_NB` raises `error`; every other `flock` is the real call."""
    real = fcntl.flock
    calls: list[int] = []

    def flock(fd: int, operation: int) -> None:
        if operation & fcntl.LOCK_EX and operation & fcntl.LOCK_NB:
            calls.append(fd)
            raise error
        real(fd, operation)

    monkeypatch.setattr(fcntl, "flock", flock)
    return calls


@pytest.mark.parametrize("code", ["EBADF", "ENOLCK", "ENOTSUP", "EINVAL", "EIO"])
def test_lock_unavailable_retains(
    tmp_path: Path, code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AT-E10: any errno from the cleaner's lock is `lock_unavailable`, never removal or live."""
    make_stage(tmp_path)
    before = snapshot(tmp_path)
    num = getattr(errno, code)
    calls = _force_exclusive(monkeypatch, OSError(num, os.strerror(num)))
    _only(reclaim_stages(tmp_path, apply=False, min_age_s=0), lock_unavailable=1)
    assert calls  # non-vacuity: the lock was reached
    assert snapshot(tmp_path) == before


def test_blocking_lock_is_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_stage(tmp_path)
    _force_exclusive(monkeypatch, BlockingIOError(errno.EWOULDBLOCK, "held"))
    _only(reclaim_stages(tmp_path, apply=False, min_age_s=0), live=1)


def test_report_value_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AT-E9: one pass over every preview outcome, and a report that names nothing."""
    scope = tmp_path / "out"
    scope.mkdir()
    tokens = ["111111111111", "222222222222", "333333333333", "444444444444"]
    make_stage(scope, token=tokens[0])  # eligible
    young = make_stage(scope, token=tokens[1])
    ahead = time.time() + 7200
    os.utime(young, (ahead, ahead))
    make_stage(scope, token=tokens[2], mode=0o755)  # unproven
    make_stage(scope, prefix=RECLAIM, token=tokens[3], marker=False)  # kept: no proof, a file
    make_stage(scope, prefix=RECLAIM, marker=False, files=())  # eligible: empty, no proof
    make_stage(scope, token="555555555555", marker_token="666666666666")  # kept: wrong token
    expected = {"eligible": 2, "young": 1, "unproven": 1, "kept": 2, "live": 1}
    if needs_root() is None:
        os.chown(make_stage(scope, token="777777777777"), FOREIGN_UID, FOREIGN_UID)
        expected["foreign"] = 1
    with LiveWriter(scope / "run-2") as writer:
        report = reclaim_stages(scope, apply=False, min_age_s=0)
        assert writer.finish("publish") == 0  # the live run publishes as if nothing ran
    _only(report, **expected)
    assert (scope / "run-2" / "t.parquet").read_bytes() == b"PAR1-live"

    names = [p.name for p in scope.iterdir()] + [str(tmp_path), *tokens, writer.stage.name]
    for text in (str(report), repr(report)):
        assert not [n for n in names if n in text]
    assert all(type(getattr(report, f)) is int for f in report.__dataclass_fields__)

    linked = tmp_path / "linked"
    os.symlink(scope, linked)
    _only(reclaim_stages(linked, apply=False, min_age_s=0), scope_unavailable=1)  # ELOOP
    _only(reclaim_stages(tmp_path / "absent", apply=False), scope_unavailable=1)


def test_report_refuses_non_counts() -> None:
    for bad in (-1, True, 1.0, "1"):
        with pytest.raises(ValueError, match="non-negative int counts"):
            ReclaimReport(removed=bad)  # type: ignore[arg-type]
