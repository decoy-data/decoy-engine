"""An empty source gives the same output types on every route.

A fixed-width layout declares each field's type, so a file with no record still has a schema.
The lazy read takes it from the layout; the resident read (the engine's `read_fixed_width`,
converted with `pa.Table.from_pandas` as the CLI and platform do) must give the same one, or
an untouched column leaves as `null` on one route and as its declared type on another.

Each route test also asserts the lane the run took, so a route that silently falls back to
another one cannot pass in its place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import read_fixed_width
from decoy_engine.execution import ParquetTransactionalSink, run_pipeline
from decoy_engine.plan import PlanCompileError
from decoy_engine.profile import FixedWidthLazySource, LazySource
from decoy_engine.progress import CallbackSink
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
ONE_RECORD = b"   1abcdef   1.5ghijkl\n"

# route -> (source is lazy, run_pipeline knobs, lane the route event must report).
# The chunked lanes need `execution_mode="stream"`: the size threshold cannot admit a
# zero-row source, and a stream run skips it.
_STREAM = {"execution_mode": "stream", "chunk_size_rows": 1}
ROUTES: dict[str, tuple[bool, dict[str, Any], str | None]] = {
    "full_frame": (False, {"auto_chunk": False, "unified_slice_enabled": False}, None),
    "chunked": (False, _STREAM, "chunked"),
    "lazy": (True, {"resident_fallback": True}, "pandas_fallback"),
    "lazy_chunked": (True, _STREAM, "chunked"),
}
UNIFIED_ACTIVATION = "unified_slice_activation"


def _config(source: dict[str, Any], names: list[str], *, hashed: bool = True) -> dict[str, Any]:
    columns = [{"name": n, "strategy": "passthrough"} for n in names]
    if hashed:
        columns.append({"name": "h", "strategy": "hash", "namespace": "ns_h"})
    return {
        "version": 2,
        "global_settings": {"seed": 1},
        "sources": {"t": source},
        "tables": [{"name": "t", "columns": columns}],
    }


def _run(cfg: dict[str, Any], source: Any, route: str, tmp_path: Path) -> pa.Schema:
    _, knobs, lane = ROUTES[route]
    events: list[Any] = []
    target = tmp_path / f"out-{route}"
    sink = ParquetTransactionalSink(target) if knobs is _STREAM else None
    result = run_pipeline(
        cfg,
        sources={"t": source},
        sink=sink,
        engine_version="empty-source-parity",
        key_provider=key_provider(),
        progress=CallbackSink(events.append),
        **knobs,
    )
    lanes = [e.lane for e in events if e.kind == "route"]
    assert lanes == [lane], f"{route} ran on {lanes}"
    out = pq.read_table(target / "t.parquet") if sink is not None else result.outputs["t"]
    assert out.num_rows == 0
    return out.schema.remove_metadata()


def _untouched(schema: pa.Schema) -> pa.Schema:
    """The passthrough columns; the hashed one is checked on its own below."""
    return pa.schema([f for f in schema if f.name != "h"])


def _fixed_width(tmp_path: Path, layout: dict[str, Any] = LAYOUT) -> tuple[dict[str, Any], Path]:
    path = tmp_path / "e.dat"
    path.write_bytes(b"")
    return {"type": "file", "format": "fixed_width", "path": str(path), "layout": layout}, path


def _fixed_width_source(descriptor: dict[str, Any], path: Path, lazy: bool) -> Any:
    if lazy:
        return FixedWidthLazySource.from_descriptor(descriptor, table="t")
    return pa.Table.from_pandas(read_fixed_width(path, descriptor["layout"]), preserve_index=False)


def _unified(cfg: dict[str, Any], source: Any) -> pa.Schema:
    result = run_pipeline(
        cfg,
        sources={"t": source},
        engine_version="empty-source-parity",
        key_provider=key_provider(),
        auto_chunk=False,
        unified_slice_enabled=True,
    )
    assert UNIFIED_ACTIVATION in result.quality_metrics, "the unified slice did not admit"
    out = result.outputs["t"]
    assert out.num_rows == 0
    return out.schema.remove_metadata()


def test_resident_read_of_an_empty_file_has_the_layout_schema(tmp_path: Path) -> None:
    descriptor, path = _fixed_width(tmp_path)
    resident = _fixed_width_source(descriptor, path, lazy=False)
    lazy = FixedWidthLazySource.from_descriptor(descriptor, table="t")
    assert resident.schema.remove_metadata() == lazy.schema
    for name, want in DECLARED.items():
        assert resident.schema.field(name).type == want, name


def test_a_capped_read_of_zero_records_has_the_layout_schema(tmp_path: Path) -> None:
    path = tmp_path / "f.dat"
    path.write_bytes(ONE_RECORD)
    frame = read_fixed_width(path, LAYOUT, max_records=0)
    schema = pa.Table.from_pandas(frame, preserve_index=False).schema
    assert [schema.field(n).type for n in DECLARED] == list(DECLARED.values())


@pytest.mark.parametrize("route", list(ROUTES))
def test_empty_fixed_width_file_writes_declared_types_on_every_route(
    tmp_path: Path, route: str
) -> None:
    descriptor, path = _fixed_width(tmp_path)
    cfg = _config(descriptor, list(DECLARED))
    schema = _run(cfg, _fixed_width_source(descriptor, path, ROUTES[route][0]), route, tmp_path)
    for name, want in DECLARED.items():
        assert schema.field(name).type == want, f"{route}: {name}"
    lazy = _run(cfg, _fixed_width_source(descriptor, path, lazy=True), "lazy", tmp_path)
    assert _untouched(schema) == _untouched(lazy), route


_PANDAS_ZERO_ROW_HASH = pytest.mark.xfail(
    strict=True, reason="hash on a zero-row frame gives double on the pandas lanes"
)


@pytest.mark.parametrize(
    "route",
    [
        pytest.param(r, marks=_PANDAS_ZERO_ROW_HASH) if r in {"full_frame", "lazy"} else r
        for r in ROUTES
    ],
)
def test_the_hashed_column_of_an_empty_file_is_string(tmp_path: Path, route: str) -> None:
    descriptor, path = _fixed_width(tmp_path)
    cfg = _config(descriptor, list(DECLARED))
    source = _fixed_width_source(descriptor, path, ROUTES[route][0])
    assert _run(cfg, source, route, tmp_path).field("h").type == pa.string()


@pytest.mark.parametrize("route", list(ROUTES))
def test_zero_row_parquet_writes_its_types_on_every_route(tmp_path: Path, route: str) -> None:
    path = tmp_path / "e.parquet"
    typed = pa.schema([("i", pa.int64()), ("s", pa.string()), ("h", pa.string())])
    pq.write_table(typed.empty_table(), path)
    descriptor = {"type": "file", "format": "parquet", "path": str(path)}
    cfg = _config(descriptor, ["i", "s"])
    source = LazySource(path) if ROUTES[route][0] else pq.read_table(path)
    schema = _run(cfg, source, route, tmp_path)
    assert schema.field("i").type == pa.int64()
    assert schema.field("s").type == pa.string()
    assert _untouched(schema) == _untouched(_run(cfg, LazySource(path), "lazy", tmp_path)), route


# The unified slice admits passthrough only on bool, int64 and string, and a hash node only
# with the compiled companion, so its fixture keeps to an int and a text field.
_UNIFIED_LAYOUT: dict[str, Any] = {"columns": LAYOUT["columns"][:2]}


def test_empty_fixed_width_file_is_admitted_to_the_unified_slice(tmp_path: Path) -> None:
    descriptor, path = _fixed_width(tmp_path, _UNIFIED_LAYOUT)
    cfg = _config(descriptor, ["i", "s"], hashed=False)
    schema = _unified(cfg, _fixed_width_source(descriptor, path, lazy=False))
    assert schema == pa.schema([("i", pa.int64()), ("s", pa.string())])
    assert schema == _run(cfg, _fixed_width_source(descriptor, path, lazy=True), "lazy", tmp_path)


def test_zero_row_parquet_is_admitted_to_the_unified_slice(tmp_path: Path) -> None:
    path = tmp_path / "e.parquet"
    typed = pa.schema([("i", pa.int64()), ("s", pa.string())])
    pq.write_table(typed.empty_table(), path)
    cfg = _config(
        {"type": "file", "format": "parquet", "path": str(path)}, ["i", "s"], hashed=False
    )
    assert _unified(cfg, pq.read_table(path)) == typed


@pytest.mark.parametrize("lazy", [False, True], ids=["resident", "lazy"])
@pytest.mark.parametrize("body", [b"", ONE_RECORD], ids=["empty", "one_record"])
def test_a_string_when_on_an_int_field_is_refused_for_an_empty_file_too(
    tmp_path: Path, body: bytes, lazy: bool
) -> None:
    # The int field is typed on an empty file now, so the plan check that refuses a string
    # output under `when` on a numeric column gives the same coded answer as on a filled file.
    descriptor, path = _fixed_width(tmp_path)
    path.write_bytes(body)
    cfg = _config(descriptor, ["s", "f"])
    cfg["tables"][0]["columns"].insert(
        0,
        {
            "name": "i",
            "strategy": "redact",
            "when": "i > 2",
            "provider_config": {"redact_with": "X"},
        },
    )
    with pytest.raises(PlanCompileError) as caught:
        run_pipeline(
            cfg,
            sources={"t": _fixed_width_source(descriptor, path, lazy)},
            engine_version="empty-source-parity",
            key_provider=key_provider(),
            resident_fallback=True,
        )
    assert caught.value.code == "when_string_output_on_numeric_unsupported"
    assert caught.value.path == "tables.t.columns.i.when"
