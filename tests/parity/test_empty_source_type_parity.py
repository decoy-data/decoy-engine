"""An empty source gives the same output types on every route.

A fixed-width layout declares each field's type, so a file with no record still has a schema.
The lazy read takes it from the layout; the resident read (the engine's `read_fixed_width`,
converted with `pa.Table.from_pandas` as the CLI and platform do) must give the same one, or
an untouched column leaves as `null` on one route and as its declared type on another.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import read_fixed_width
from decoy_engine.execution import run_pipeline
from decoy_engine.profile._lazy_fixed_width import FixedWidthLazySource
from decoy_engine.profile._readers import LazySource
from tests.native._chunked_entry_support import key_provider

LAYOUT: dict[str, Any] = {
    "columns": [
        {"name": "i", "start": 0, "width": 4, "type": "int", "align": "right"},
        {"name": "s", "start": 4, "width": 6},
        {"name": "f", "start": 10, "width": 6, "type": "float", "align": "right"},
        {"name": "h", "start": 16, "width": 6},
    ]
}
# What the layout declares, written out here rather than read from the engine's own map.
DECLARED = {"i": pa.int64(), "s": pa.string(), "f": pa.float64()}

# Resident routes take the whole table; lazy routes take the file.
ROUTES: dict[str, dict[str, Any]] = {
    "full_frame": {"auto_chunk": False, "unified_slice_enabled": False},
    "unified": {"auto_chunk": False, "unified_slice_enabled": True},
    "chunked": {"auto_chunk": True, "auto_chunk_threshold_rows": 1, "chunk_size_rows": 1},
    "lazy": {"resident_fallback": True},
    "lazy_chunked": {
        "resident_fallback": True,
        "auto_chunk_threshold_rows": 1,
        "chunk_size_rows": 1,
    },
}


def _config(source: dict[str, Any], names: list[str]) -> dict[str, Any]:
    columns = [{"name": n, "strategy": "passthrough"} for n in names]
    columns.append({"name": "h", "strategy": "hash", "namespace": "ns_h"})
    return {
        "version": 2,
        "global_settings": {"seed": 1},
        "sources": {"t": source},
        "tables": [{"name": "t", "columns": columns}],
    }


def _run(cfg: dict[str, Any], source: Any, route: str) -> pa.Schema:
    result = run_pipeline(
        cfg,
        sources={"t": source},
        engine_version="empty-source-parity",
        key_provider=key_provider(),
        **ROUTES[route],
    )
    out = result.outputs["t"]
    assert out.num_rows == 0
    return out.schema.remove_metadata()


def _fixed_width(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    path = tmp_path / "e.dat"
    path.write_bytes(b"")
    return {"type": "file", "format": "fixed_width", "path": str(path), "layout": LAYOUT}, path


def _fixed_width_source(descriptor: dict[str, Any], path: Path, route: str) -> Any:
    if route.startswith("lazy"):
        return FixedWidthLazySource.from_descriptor(descriptor, table="t")
    return pa.Table.from_pandas(read_fixed_width(path, LAYOUT), preserve_index=False)


def test_resident_read_of_an_empty_file_has_the_layout_schema(tmp_path: Path) -> None:
    descriptor, path = _fixed_width(tmp_path)
    resident = pa.Table.from_pandas(read_fixed_width(path, LAYOUT), preserve_index=False)
    lazy = FixedWidthLazySource.from_descriptor(descriptor, table="t")
    assert resident.schema.remove_metadata() == lazy.schema
    for name, want in DECLARED.items():
        assert resident.schema.field(name).type == want, name


def test_a_capped_read_of_zero_records_has_the_layout_schema(tmp_path: Path) -> None:
    path = tmp_path / "f.dat"
    path.write_text("   1abcdef   1.5ghijkl\n", encoding="utf-8")
    frame = read_fixed_width(path, LAYOUT, max_records=0)
    schema = pa.Table.from_pandas(frame, preserve_index=False).schema
    assert [schema.field(n).type for n in DECLARED] == list(DECLARED.values())


@pytest.mark.parametrize("route", list(ROUTES))
def test_empty_fixed_width_file_writes_declared_types_on_every_route(
    tmp_path: Path, route: str
) -> None:
    descriptor, path = _fixed_width(tmp_path)
    cfg = _config(descriptor, list(DECLARED))
    schema = _run(cfg, _fixed_width_source(descriptor, path, route), route)
    for name, want in DECLARED.items():
        assert schema.field(name).type == want, f"{route}: {name}"
    # The masked column too: every route agrees with the lazy run.
    lazy = _run(cfg, FixedWidthLazySource.from_descriptor(descriptor, table="t"), "lazy")
    assert schema == lazy, route


@pytest.mark.parametrize("route", list(ROUTES))
def test_zero_row_parquet_writes_its_types_on_every_route(tmp_path: Path, route: str) -> None:
    path = tmp_path / "e.parquet"
    typed = pa.schema([("i", pa.int64()), ("s", pa.string()), ("h", pa.string())])
    pq.write_table(typed.empty_table(), path)
    descriptor = {"type": "file", "format": "parquet", "path": str(path)}
    cfg = _config(descriptor, ["i", "s"])
    source = LazySource(path) if route.startswith("lazy") else pq.read_table(path)
    schema = _run(cfg, source, route)
    assert schema.field("i").type == pa.int64()
    assert schema.field("s").type == pa.string()
    assert schema == _run(cfg, LazySource(path), "lazy"), route
