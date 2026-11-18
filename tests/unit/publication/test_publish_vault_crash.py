"""F22 5.5 rule V under SIGKILL (slice b2): an output bound without its durable vault is not a
state any crash can leave.

Plan `docs/plans/2026-10-30-f22-publication-replan.md` 7.2 row
`test_output_bound_vault_missing_unreachable`. A `spawn` child publishes a unit with a vault and
SIGKILLs itself before its `nth` durability step after the bind verdict: the vault file fsync
(so after the vault stage write), the vault `link`, each vault chain fsync, the stage fsync walk
(after the descriptor write), the output rename and each output chain fsync, and one run that
finishes. After every kill, a bound output implies a vault leaf whose sha256 is the descriptor's;
a retry in this process then publishes or reports `already_committed`, and a vault the killed
attempt linked keeps its inode (adopted, never rewritten).
"""

from __future__ import annotations

import signal
import sys
from pathlib import Path

import pytest

from tests.fileaccess.publication._chain_support import anchor_at
from tests.fileaccess.publication._dirmode_support import POLICIES
from tests.unit.publication._publish_support import run_spec
from tests.unit.publication._vault_publish_support import (
    KILL_MARKER,
    OUT_REL,
    STEPS,
    VAULT_REL,
    bound_descriptor,
    close_all,
    crash_child,
    prepare,
    publish,
    sha,
    vault_fingerprint,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX durable vault")
_MAX_STEPS = 80  # far above the steps one publish takes; reaching it is a failure


def _bound_implies_vault(leaf: Path, vleaf: Path) -> bool:
    bound = bound_descriptor(leaf)
    if bound is None:
        return True
    return vleaf.is_file() and sha(vleaf) == bound["vault"]["sha256"]


@pytest.mark.parametrize("policy", POLICIES)
def test_output_bound_vault_missing_unreachable(
    tmp_path: Path, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    cut: list[str] = []
    finished = False
    for nth in range(1, _MAX_STEPS):
        run = tmp_path / f"run-{nth}"
        base = run / "root"
        prepare(base)
        spec = {"base": str(base), "policy": policy, "kill_at": nth}
        code, result = run_spec(crash_child, spec, run)
        leaf, vleaf = base / OUT_REL, base / VAULT_REL
        if code == 0:
            assert result["outcome"] == "published"
            assert _bound_implies_vault(leaf, vleaf)
            finished = True
            break
        assert code == -signal.SIGKILL
        marker = run / KILL_MARKER
        assert marker.exists()  # non-vacuity: the child died at the named step
        cut.append(marker.read_text("utf-8"))
        assert _bound_implies_vault(leaf, vleaf), cut[-1]
        was_bound, linked = bound_descriptor(leaf) is not None, vault_fingerprint(vleaf)
        with monkeypatch.context() as patch:
            if policy == "ambient":
                anchor_at(patch, base)
            receipt, fds = publish(policy, base, "one", "op-1")
            close_all(fds)
        expected = "already_committed" if was_bound else "published"
        assert (receipt.outcome, receipt.durable) == (expected, True), (nth, cut[-1])
        assert _bound_implies_vault(leaf, vleaf)
        assert receipt.vault_digest == sha(vleaf)
        if linked is not None:
            assert vault_fingerprint(vleaf) == linked  # adopted in place, never rewritten
    assert finished, "the publish never finished"
    assert set(cut) == set(STEPS)  # non-vacuity: kills landed on fsync, link and rename steps
    assert cut.index("link") < cut.index("rename")
