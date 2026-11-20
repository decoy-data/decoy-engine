"""Build a signed bundle directory on disk for the bundle-route tests (synthetic keys, per test)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from decoy_engine.signed_evidence import (
    EVIDENCE_FILENAME,
    SIGNATURE_FILENAME,
    LocalEs256Signer,
    TrustPolicy,
)
from decoy_engine.signed_evidence import _boundary as boundary
from tests.unit.signed_evidence import _factory as f


def make_bundle(tmp_path: Path) -> tuple[Path, Any, LocalEs256Signer, TrustPolicy]:
    """``(dir, signed, signer, policy)``: ``dir`` holds the statement, signature and ``artifacts/``."""
    signer = f.new_signer()
    policy = f.policy_for(signer)
    signed = boundary.sign_evidence(f.base_draft(), signer=signer)
    root = tmp_path / "bundle"
    f.write_artifacts(root / "artifacts")
    (root / EVIDENCE_FILENAME).write_bytes(signed.statement)
    (root / SIGNATURE_FILENAME).write_bytes(signed.signature)
    return root, signed, signer, policy


def open_fd_count() -> int:
    for base in ("/proc/self/fd", "/dev/fd"):
        if os.path.isdir(base):
            return len(os.listdir(base))
    raise RuntimeError("no descriptor directory")
