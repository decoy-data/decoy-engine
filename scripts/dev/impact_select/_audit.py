"""The one audit-hook installer for the impact-map build (PEP 578).

It records, for the measured test file, every tracked repo file that is opened and every repo
directory that is listed (Ekstazi-style file dependencies), plus a start marker per process and a
launch record per Python subprocess the process starts. The build reconciles the launches against
the markers and coverage shards, so a child that skipped the hook (`-S`, another interpreter)
fails the build instead of silently shrinking the map.

This file is copied into the build venv as `_decoy_impact_boot.py` and imported by a `.pth`, so it
runs at startup of every interpreter there: stdlib only, no relative imports, and nothing happens
unless `DECOY_IMPACT_SHARD_DIR` is set. Events whose issuing frame is the frozen import loader are
dropped: importing a module is not a dependency on its text, while `Path.read_text`, `rglob` and
`inspect.getsource` reads are.

Method: Ekstazi (Gligoric et al., ISSTA 2015) file dependencies recorded through audit events."""

from __future__ import annotations

import os
import sys

TYPE_CHECKING = False  # the `typing` import below is for annotations only; skip it at startup
if TYPE_CHECKING:
    from typing import Any

ENV_SHARD_DIR = "DECOY_IMPACT_SHARD_DIR"
ENV_ROOT = "DECOY_IMPACT_ROOT"

_LOADER_FRAMES = ("<frozen importlib._bootstrap", "<frozen zipimport")
_LAUNCH_EVENTS = frozenset({"subprocess.Popen", "os.exec", "os.posix_spawn", "os.spawn"})
_SKIP_PARTS = ("__pycache__",)
_FLAG = (
    "_decoy_impact_audit_installed"  # on `sys`: the .pth copy and the plugin are two module objects
)


def install_audit() -> bool:
    """Install the hook once per process. False when already installed or not measuring."""
    shard_dir = os.environ.get(ENV_SHARD_DIR)
    root = os.environ.get(ENV_ROOT)
    if getattr(sys, _FLAG, False) or not shard_dir or not root:
        return False
    setattr(sys, _FLAG, True)
    import json
    import re
    import shutil
    import threading
    import time

    roots = sorted({os.path.abspath(root), os.path.realpath(root)})
    fd = os.open(
        os.path.join(shard_dir, f"{os.getpid()}-{time.time_ns()}.jsonl"),
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o600,
    )
    seen: set[tuple[str, str]] = set()
    local = threading.local()
    py_name = re.compile(r"python[0-9.]*(\.exe)?", re.IGNORECASE)
    own = os.path.realpath(sys.executable) if sys.executable else ""

    def emit(rec: dict[str, object]) -> None:
        os.write(fd, (json.dumps(rec, separators=(",", ":")) + "\n").encode("utf-8"))

    def rel(p: object) -> str | None:
        try:
            s = os.fspath(p)  # type: ignore[call-overload]
        except TypeError:
            return None  # an fd, not a path
        if isinstance(s, bytes):
            s = os.fsdecode(s)
        a = os.path.abspath(s or ".")
        for r in roots:
            if a == r:
                return "."
            if a.startswith(r + os.sep):
                out = a[len(r) + 1 :].replace(os.sep, "/")
                if out.split("/", 1)[0] == ".git" or any(x in out for x in _SKIP_PARTS):
                    return None
                return out
        return None

    stdlib = os.path.dirname(os.__file__)
    tool_marker = os.sep + "coverage" + os.sep

    def from_coverage(frame: Any) -> bool:
        # coverage lists every `source` dir when it saves; that is the tool, not the test. Every
        # test frame has coverage's runner below it, so ask who the nearest non-stdlib caller is.
        while frame is not None:
            name = frame.f_code.co_filename
            if name.startswith("<frozen") or (
                name.startswith(stdlib) and "site-packages" not in name
            ):
                frame = frame.f_back
                continue
            return "site-packages" in name and tool_marker in name
        return False

    def note(kind: str, p: object, frame: Any) -> None:
        r = rel(p)
        if r is None or (kind, r) in seen:
            return
        # Importing is not a dependency on a file's text, so the frozen loader's own opens and
        # listings are dropped; a test that reads the same path itself is still recorded.
        if frame.f_code.co_filename.startswith(_LOADER_FRAMES) or from_coverage(frame):
            return
        seen.add((kind, r))
        emit({"k": kind, "p": r})

    def is_python(exe: object) -> bool:
        try:
            s = os.fsdecode(os.fspath(exe))  # type: ignore[call-overload]
        except TypeError:
            return False
        found = s if os.sep in s else shutil.which(s)
        if not found or not os.path.isfile(found):
            return False  # a launch that cannot happen is not a missing child
        return bool(py_name.fullmatch(os.path.basename(found))) or os.path.realpath(found) == own

    def glob_dir(args: tuple[object, ...]) -> object:
        pattern = os.fsdecode(os.fspath(args[0]))  # type: ignore[call-overload]
        base = args[2] if len(args) > 2 and args[2] else "."
        parts: list[str] = []
        for part in pattern.split("/")[:-1]:
            if any(c in part for c in "*?["):
                break
            parts.append(part)
        return os.path.join(os.fsdecode(os.fspath(base)), *parts) if parts else base  # type: ignore[call-overload]

    def hook(event: str, args: tuple[object, ...]) -> None:
        if getattr(local, "busy", False):
            return
        if event not in {"open", "os.listdir", "os.scandir", "glob.glob"} | _LAUNCH_EVENTS:
            return
        local.busy = True
        try:
            if event in _LAUNCH_EVENTS:
                exe = args[0] if event != "os.spawn" else args[1]
                if event == "subprocess.Popen" and exe is None and args[1]:
                    exe = args[1][0]  # type: ignore[index]
                if is_python(exe):
                    emit({"k": "launch"})
                return
            frame = sys._getframe(1)  # the Python frame that issued the event
            if event == "open":
                note("read", args[0], frame)
            elif event == "glob.glob":
                note("list", glob_dir(args), frame)
            else:
                note("list", args[0] if args and args[0] is not None else ".", frame)
        except Exception:
            return
        finally:
            local.busy = False

    emit({"k": "start", "pid": os.getpid(), "ppid": os.getppid()})
    sys.addaudithook(hook)
    return True


def read_shards(shard_dir: str) -> tuple[set[str], set[str], list[dict[str, int]], int]:
    """Merge one test file's shards: (reads, lists, start markers, Python launches)."""
    import json

    reads: set[str] = set()
    lists: set[str] = set()
    starts: list[dict[str, int]] = []
    launches = 0
    for name in sorted(os.listdir(shard_dir)):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(shard_dir, name), encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                k = rec["k"]
                if k == "read":
                    reads.add(rec["p"])
                elif k == "list":
                    lists.add(rec["p"])
                elif k == "start":
                    starts.append({"pid": rec["pid"], "ppid": rec["ppid"]})
                elif k == "launch":
                    launches += 1
    return reads, lists, starts, launches
