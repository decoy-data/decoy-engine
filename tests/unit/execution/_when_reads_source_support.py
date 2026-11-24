"""Builders for the WHEN-READS-SOURCE (S2) tests: a status column that an earlier node masks and
a gated column whose `when:` reads it, run through one route."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pyarrow as pa

from decoy_engine.execution import run_pipeline
from tests._declared_schema import declare_rest
from tests.native._chunked_entry_support import (
    ENGINE_VERSION,
    TABLE,
    hash_col,
    key_provider,
    make_config,
    redact,
    truncate,
)

NS = "ns"


def status_source(rows: int = 2000, active: int = 600) -> pa.Table:
    """`active` rows with status 'active', the rest 'idle'; the gated column holds source text."""
    status = ["active" if i < active else "idle" for i in range(rows)]
    return pa.table(
        {
            "status": pa.array(status, pa.string()),
            "zz_email": pa.array([f"user{i}@example.test" for i in range(rows)], pa.string()),
        }
    )


def gated_column(kind: str, name: str, when: str) -> dict[str, Any]:
    base = {"redact": redact(name), "hash": hash_col(name, NS), "truncate": truncate(name, 2)}
    return {**base[kind], "when": when}


def config_for(
    kind: str, *, status: str = "status", gated: str = "zz_email", status_kind: str = "hash"
) -> dict[str, Any]:
    """`status` is masked by `status_kind` (hash in `ns` or redact); `gated` carries
    `when: status == 'active'` (read by name)."""
    earlier = hash_col(status, NS) if status_kind == "hash" else redact(status)
    return make_config([earlier, gated_column(kind, gated, f"{status} == 'active'")])


def run_full_frame(config: dict[str, Any], source: pa.Table, tmp_path: Path, **kwargs: Any) -> Any:
    config = copy.deepcopy(config)
    (tmp_path / "s.csv").write_text(",".join(source.column_names) + "\n" + "x," * 1 + "x\n")
    config["sources"][TABLE] = {
        "type": "file",
        "format": "csv",
        "has_header": True,
        "path": str(tmp_path / "s.csv"),
    }
    config["targets"][TABLE] = {"type": "file", "format": "csv", "path": str(tmp_path / "o.csv")}
    declare_rest(config)
    opts = {"execution_mode": "full_frame", "auto_chunk": False, "unified_slice_enabled": False}
    return run_pipeline(
        config,
        {TABLE: source},
        engine_version=ENGINE_VERSION,
        key_provider=key_provider(),
        **{**opts, **kwargs},
    )


def changed_rows(out: pa.Table, source: pa.Table, column: str) -> list[bool]:
    """Per row: the output differs from the source value (the row was masked)."""
    return [
        a != b
        for a, b in zip(
            out.column(column).to_pylist(), source.column(column).to_pylist(), strict=True
        )
    ]
