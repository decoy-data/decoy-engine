"""Shared harness for the F26 stage-reclaim tests (plan 6.1, E2a and E2b).

Every tree is built under the test's own `tmp_path`. A dead stage is built here exactly as the
engine's stage creator leaves one (an owner-only directory and its 0600 marker), so a cell can
vary one property at a time; the kill cells of E2b make theirs with a real engine child.
`LiveWriter` is a real child process holding an open `publication` transaction at a barrier.
"""

from __future__ import annotations

import os
import secrets
import stat
import subprocess
import sys
from pathlib import Path
from types import TracebackType

PENDING = "._decoy_publication_pending_"
RECLAIM = "._decoy_publication_reclaim_"
MARKER = ".decoy-publication-stage"
MAGIC = b"decoy-publication-stage-v1:"
REPO = Path(__file__).resolve().parents[3]

Snapshot = dict[str, tuple[int, int, int, int, int]]


def make_stage(
    parent: Path,
    *,
    prefix: str = PENDING,
    token: str | None = None,
    marker_token: str | None = None,
    marker: bool = True,
    files: tuple[str, ...] = ("t.parquet",),
    mode: int = 0o700,
) -> Path:
    """A stage as the writer leaves it. `marker_token` writes a marker for another token."""
    token = token or secrets.token_hex(6)
    stage = parent / f"{prefix}{token}"
    stage.mkdir()
    for name in files:
        (stage / name).write_bytes(b"PAR1-" + name.encode())
    if marker:
        proof = stage / MARKER
        proof.write_bytes(MAGIC + (marker_token or token).encode("ascii") + b"\n")
        os.chmod(proof, 0o600)
    os.chmod(stage, mode)
    return stage


def snapshot(root: Path) -> Snapshot:
    """Every entry below `root`, links not followed: inode, mode, mtime, ctime and size."""
    out: Snapshot = {}
    for path in sorted([root, *root.rglob("*")]):
        st = os.lstat(path)
        out[str(path.relative_to(root))] = (
            st.st_ino,
            st.st_mode,
            st.st_mtime_ns,
            st.st_ctime_ns,
            st.st_size if not stat.S_ISDIR(st.st_mode) else 0,
        )
    return out


_WRITER = """
import os, sys
from decoy_engine.fileaccess import FileRequest, FileRole
from decoy_engine.fileaccess._local import LocalFileAccess
req = FileRequest(FileRole.TARGET_OUTPUT, "write", sys.argv[1], "targets.t.path")
txn = LocalFileAccess().output_dir(req).begin("dir", "exclusive", label="publication")
fd = txn.create_file("t.parquet")
os.write(fd, b"PAR1-live")
os.close(fd)
print(os.path.basename(txn.local_stage_path()), flush=True)
end = sys.stdin.readline().strip()
txn.publish() if end == "publish" else txn.abort()
print("done", flush=True)
"""


class LiveWriter:
    """A child holding an open, locked `publication` stage beside `target` until `finish`."""

    def __init__(self, target: Path) -> None:
        self.proc = subprocess.Popen(  # noqa: S603 -- static argv: sys.executable and a literal script
            [sys.executable, "-c", _WRITER, str(target)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            cwd=REPO,
        )
        assert self.proc.stdout is not None
        self.stage = target.parent / self.proc.stdout.readline().strip()
        assert self.stage.name.startswith(PENDING), "the writer did not reach its barrier"

    def finish(self, end: str = "publish") -> int:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        if self.proc.poll() is None:
            self.proc.stdin.write(end + "\n")
            self.proc.stdin.flush()
            assert self.proc.stdout.readline().strip() == "done"
        return self.proc.wait(60)

    def __enter__(self) -> LiveWriter:
        return self

    def __exit__(
        self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(60)


def needs_root() -> str | None:
    """The reason a cell that chowns to another uid cannot run, or None."""
    return None if os.geteuid() == 0 else "chowning an entry to another uid needs root"
