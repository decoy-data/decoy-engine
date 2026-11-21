"""A valid expectations document and its pin, for the expectations and CLI-shaped tests."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from tests.unit.signed_evidence import _corpus
from tests.unit.signed_evidence import _factory as f


def catalog_doc() -> dict[str, Any]:
    return json.loads((_corpus.CORPUS / "shared" / "catalog-strict.json").read_bytes())


def valid_doc() -> dict[str, Any]:
    return {
        "v": 1,
        "tenant": f.TENANT,
        "job_id": "job-1001",
        "attempt_id": "attempt-1",
        "bundle_id": "bundle-001",
        "snapshot_id": "snap-001",
        "artifacts": [
            {"id": a.id, "sha256": a.sha256.removeprefix("sha256:"), "media_type": a.media_type}
            for a in f.expected_artifacts()
        ],
        "unbound_outputs": 0,
        "catalog": catalog_doc(),
    }


def encode(doc: Any) -> bytes:
    return json.dumps(doc, indent=2).encode()


def pin(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()
