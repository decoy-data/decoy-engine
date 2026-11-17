"""Helpers for the F22 b2 tests: `publish_unit` with a vault (plan 5.5, 7.1, 7.2).

A unit is published into `base/a/out` and its vault into `base/vaults/v.dcyvault`, both under
the same policy. The `spawn` children run one publish each: a winner parked in `_after_judge`
(two-writer tests, ordered by events, never by timing) or a writer that SIGKILLs itself before
its `nth` durability step (crash tests, with a marker file naming the step as the non-vacuity
line). Built on the a3 and b1 helpers, not a second harness.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import signal
from pathlib import Path
from typing import Any

from tests.fileaccess.publication._vault_support import LEAF, ROWS, vault_out, writer
from tests.unit.publication._publish_support import (
    DESCRIPTOR,
    _anchor_child,
    make_out,
    tables,
)

OUT_REL = "a/out"
VAULT_REL = f"vaults/{LEAF}"
ALICE = (("ns", "X", "Alice"),)
BOB = (("ns", "X", "Bob"),)
KILL_MARKER = "vault-order-killed"
STEPS = ("fsync", "link", "rename")


def prepare(base: Path) -> None:
    (base / "a").mkdir(parents=True, exist_ok=True)
    (base / "vaults").mkdir(parents=True, exist_ok=True)


def binding(policy: str, base: Path, rows: Any = ROWS, rel: str = VAULT_REL) -> tuple[Any, int]:
    """A `VaultBinding` for `rows` at `base/rel`; the second value is its root fd (or -1)."""
    from decoy_engine.publication import VaultBinding

    out, root_fd = vault_out(policy, base, rel)
    return VaultBinding(writer=writer(rows), out=out), root_fd


def publish(
    policy: str, base: Path, seed: str, op: str, rows: Any = ROWS, *, vault: bool = True
) -> tuple[Any, list[int]]:
    """`publish_tables` of `seed` with (or without) a vault of `rows`; returns the receipt and
    the root fds to close."""
    from decoy_engine.publication import PublicationRequest, publish_tables

    out, out_fd = make_out(policy, base, OUT_REL)
    bound, vault_fd = binding(policy, base, rows) if vault else (None, -1)
    request = PublicationRequest(op, vault=bound, lock_timeout_s=60)
    return publish_tables(out, tables(seed), request), [out_fd, vault_fd]


def close_all(fds: list[int]) -> None:
    for fd in fds:
        if fd >= 0:
            os.close(fd)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vault_fingerprint(path: Path) -> tuple[str, int] | None:
    """The vault leaf's bytes digest and inode, or None when it is absent."""
    if not path.exists():
        return None
    return sha(path), os.lstat(path).st_ino


def bound_descriptor(leaf: Path) -> dict[str, Any] | None:
    path = leaf / DESCRIPTOR
    if not path.is_file():
        return None
    loaded: dict[str, Any] = json.loads(path.read_bytes())
    return loaded


def _kill_before(nth: int, marker: Path) -> None:
    """SIGKILL just before the `nth` durability step (an fsync, the vault `link` or the stage
    rename) counted from the bind verdict; the marker names the step that was cut."""
    from decoy_engine.publication import _publish

    state = {"armed": False, "count": 0}

    def arm() -> None:
        state["armed"] = True

    def cutting(kind: str, real: Any) -> Any:
        def step(*args: Any, **kwargs: Any) -> Any:
            if state["armed"]:
                state["count"] += 1
                if state["count"] == nth:
                    marker.write_text(kind, encoding="utf-8")
                    os.kill(os.getpid(), signal.SIGKILL)
            return real(*args, **kwargs)

        return step

    _publish._after_judge = arm  # type: ignore[attr-defined]
    os.fsync = cutting("fsync", os.fsync)  # type: ignore[assignment]
    os.link = cutting("link", os.link)  # type: ignore[assignment]
    os.rename = cutting("rename", os.rename)  # type: ignore[assignment]
    os.replace = cutting("rename", os.replace)  # type: ignore[assignment]


def crash_child(spec_path: str) -> None:
    """Publish with a vault, SIGKILLed before durability step `spec["kill_at"]`; a run that
    finishes first writes its outcome (the step count was past the end)."""
    spec = json.loads(Path(spec_path).read_text("utf-8"))
    base = Path(spec["base"])
    if spec["policy"] == "ambient":
        _anchor_child(base)
    _kill_before(spec["kill_at"], base.parent / KILL_MARKER)
    receipt, _fds = publish(spec["policy"], base, "one", "op-1")
    Path(spec["result"]).write_text(json.dumps({"outcome": receipt.outcome}), encoding="utf-8")


def winner_child(spec_path: str, w_in_hook: Any, l_probed: Any, l_waiting: Any) -> None:
    """Writer W with Alice's vault: parks in `_after_judge` (lock held, bind verdict, no vault
    written yet) until L has probed the lock and is blocked on it, then commits and binds."""
    spec = json.loads(Path(spec_path).read_text("utf-8"))
    from decoy_engine.publication import _publish

    fired = []

    def hook() -> None:
        fired.append(True)
        w_in_hook.set()
        if not (l_probed.wait(60) and l_waiting.wait(60)):  # pragma: no cover - a hung loser
            raise AssertionError("loser never probed the lock")

    _publish._after_judge = hook  # type: ignore[attr-defined]
    receipt, _fds = publish(spec["policy"], Path(spec["base"]), "one", spec["op"], ALICE)
    Path(spec["result"]).write_text(
        json.dumps({"outcome": receipt.outcome, "fired": bool(fired)}), encoding="utf-8"
    )


def start_winner(spec: dict[str, Any], tmp: Path) -> tuple[Any, Path, Any, Any, Any]:
    ctx = multiprocessing.get_context("spawn")
    w_in_hook, l_probed, l_waiting = ctx.Event(), ctx.Event(), ctx.Event()
    spec_path = tmp / "vault-winner.json"
    result_path = tmp / "vault-winner.result"
    spec_path.write_text(json.dumps({**spec, "result": str(result_path)}), encoding="utf-8")
    proc = ctx.Process(target=winner_child, args=(str(spec_path), w_in_hook, l_probed, l_waiting))
    proc.start()
    return proc, result_path, w_in_hook, l_probed, l_waiting


__all__ = [
    "ALICE",
    "BOB",
    "KILL_MARKER",
    "OUT_REL",
    "ROWS",
    "STEPS",
    "VAULT_REL",
    "binding",
    "bound_descriptor",
    "close_all",
    "crash_child",
    "prepare",
    "publish",
    "sha",
    "start_winner",
    "vault_fingerprint",
]
