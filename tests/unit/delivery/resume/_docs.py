"""Hand-built resume store documents for the record and plan tests.

Built with `json` and `hashlib` only, never with the engine codec, so a test that decodes one
checks the reader against the plan's wire rules (4.2), not against the writer.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

RUN_SCHEMA = "decoy-resume-run/v1"
TABLE_SCHEMA = "decoy-resume-table/v1"
KIB = 1 << 10


def canonical(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def tagged(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode()).hexdigest()


def bare(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def fingerprint(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "config_hash": bare("config"),
        "components": [["decoy-cli", "1.0.0"], ["decoy-engine", "0.23.0"], ["pyarrow", "18.0.0"]],
        "key_check": "0123456789abcdef",
        "key_version": "v1",
        "chunk_size": 50000,
    }
    body.update(over)
    return body


def entry(index: int, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "index": index,
        "name_digest": tagged(f"name-{index}"),
        "binding_digest": tagged(f"binding-{index}"),
    }
    body.update(over)
    return body


def run_doc(tables: int = 5, **over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema": RUN_SCHEMA,
        "run_id": "20261116T101500123456Z-0a1b2c3d",
        "invocation_id": "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
        "operation_id": "run-0a1b2c3d",
        "route": "chunked",
        "fingerprint": fingerprint(),
        "tables": [entry(i) for i in range(tables)],
    }
    doc.update(over)
    return doc


def artifact(index: int = 0, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "path": f"tables/{index}-0123456789ab.parquet",
        "role": "table",
        "rows": 1200,
        "sha256": bare(f"file-{index}"),
        "size": 48213,
    }
    body.update(over)
    return body


def table_doc(index: int = 0, **over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema": TABLE_SCHEMA,
        "index": index,
        "name_digest": tagged(f"name-{index}"),
        "binding_digest": tagged(f"binding-{index}"),
        "artifact": artifact(index),
        "source_sha256": tagged(f"source-{index}"),
        "fingerprint_digest": tagged("fingerprint"),
    }
    doc.update(over)
    return doc


def edit(doc: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """A deep copy of ``doc`` with the dotted ``path`` set to ``value`` (``DELETE`` drops it)."""
    out = copy.deepcopy(doc)
    node: Any = out
    *head, last = path.split(".")
    for part in head:
        node = node[int(part)] if isinstance(node, list) else node[part]
    if value is DELETE:
        del node[last]
    elif isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value
    return out


DELETE = object()
