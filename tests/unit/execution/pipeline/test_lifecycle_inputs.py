"""F24 84-E1: sample reads, format rules and `estimate_job` wiring of the lifecycle estimate."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import PipelineConfig, estimate_job
from decoy_engine.execution.pipeline import _lifecycle as lc
from decoy_engine.execution.pipeline import _lifecycle_inputs as li
from decoy_engine.profile._lazy_build import FILE_FORMATS

MARKER = "SEEDED-MARKER-7f3a"
PATH_MARKER = "pathmarker9c1d"


def _config(
    tmp_path: Path,
    *,
    fmt: str,
    src: str,
    column: dict[str, Any] | list[dict[str, Any]],
    target: str = "parquet",
    extra_src: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source: dict[str, Any] = {"type": "file", "path": src, "format": fmt, **(extra_src or {})}
    if fmt == "csv":
        source["has_header"] = True
    raw = {
        "version": 2,
        "global_settings": {"seed": 7},
        "sources": {"t": source},
        "targets": {
            "t": {"type": "file", "path": str(tmp_path / f"out.{target}"), "format": target}
        },
        "tables": [{"name": "t", "columns": column if isinstance(column, list) else [column]}],
    }
    return PipelineConfig.model_validate(raw).model_dump()


def _csv(tmp_path: Path, header: str, rows: list[str], name: str = "t.csv") -> str:
    path = tmp_path / name
    path.write_text(header + "\n" + "\n".join(rows) + "\n")
    return str(path)


def _redact(name: str) -> dict[str, Any]:
    return {"name": name, "strategy": "redact"}


def _csv_job(tmp_path: Path, rows: int = 200) -> dict[str, Any]:
    src = _csv(tmp_path, "a,b", [f"v{i},w{i}" for i in range(rows)])
    return _config(tmp_path, fmt="csv", src=src, column=[_redact("a"), _redact("b")])


# --- AT-E1-6 -----------------------------------------------------------------------------


def test_a_csv_mask_job_gets_a_lifecycle_peak_and_the_estimated_rows_note(tmp_path: Path) -> None:
    est = estimate_job(_csv_job(tmp_path), tmp_path)
    assert est.priceable is True, est
    assert est.lifecycle_peak_bytes is not None
    assert [name for name, _ in est.phase_bytes] == ["ingest", "execute", "write"]
    assert est.lifecycle_peak_bytes == max(b for _, b in est.phase_bytes)
    assert est.limiting_phase in {"ingest", "execute", "write"}
    assert "row counts estimated from file size" in est.notes


def test_an_exact_row_count_adds_no_estimated_note(tmp_path: Path) -> None:
    table = pa.table({"n": pa.array(list(range(100)), type=pa.int64())})
    path = tmp_path / "t.parquet"
    pq.write_table(table, path)
    cfg = _config(tmp_path, fmt="parquet", src=str(path), column=_redact("n"))
    est = estimate_job(cfg, tmp_path)
    assert est.lifecycle_peak_bytes is not None
    assert "row counts estimated from file size" not in est.notes


# --- AT-E1-7, AT-E1-14 -------------------------------------------------------------------


def test_a_dictionary_column_leaves_the_lifecycle_at_defaults_and_names_it(
    tmp_path: Path,
) -> None:
    # The classifier prices no dictionary column. (A list column never gets this far: the
    # profiler itself raises on it, so `estimate_job` reports route "unknown".)
    col = pa.array(["a", "b", "a"]).dictionary_encode()
    path = tmp_path / "t.parquet"
    pq.write_table(pa.table({"col": col}), path)
    cfg = _config(tmp_path, fmt="parquet", src=str(path), column=_redact("col"))
    est = estimate_job(cfg, tmp_path)
    assert est.priceable is False
    assert est.lifecycle_peak_bytes is None and est.limiting_phase is None
    assert est.phase_bytes == ()
    assert any("t.col" in n for n in est.notes)


def test_a_list_column_never_raises(tmp_path: Path) -> None:
    table = pa.table({"col": pa.array([[1], [2]], type=pa.list_(pa.int64()))})
    path = tmp_path / "t.parquet"
    pq.write_table(table, path)
    est = estimate_job(
        _config(tmp_path, fmt="parquet", src=str(path), column=_redact("col")), tmp_path
    )
    assert est.priceable is False and est.lifecycle_peak_bytes is None


def test_a_string_column_empty_in_the_sample_is_unpriced_not_width_zero(tmp_path: Path) -> None:
    src = _csv(tmp_path, "a,b", [f"v{i}," for i in range(50)])
    cfg = _config(tmp_path, fmt="csv", src=src, column=[_redact("a"), _redact("b")])
    est = estimate_job(cfg, tmp_path)
    assert est.lifecycle_peak_bytes is None and est.phase_bytes == ()
    assert any("t.b" in n for n in est.notes)


# --- AT-E1-8 -----------------------------------------------------------------------------


def test_the_csv_sample_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from decoy_engine.profile import _csv_reader

    seen: list[int | None] = []
    real = li.read_csv_source

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs.get("nrows"))
        return real(*args, **kwargs)

    monkeypatch.setattr(li, "read_csv_source", spy)
    assert li.read_csv_source is not _csv_reader.read_csv_source
    est = estimate_job(_csv_job(tmp_path, rows=30_000), tmp_path)
    assert est.lifecycle_peak_bytes is not None
    assert seen and all(n is not None and n <= 10_000 for n in seen)


def test_the_parquet_sample_is_one_bounded_batch_and_never_a_full_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decoy_engine.profile import _readers

    batch_rows: list[int] = []
    real_open = _readers.LazySource.open_batches

    def spy_open(self: Any, rows: int, **kwargs: Any) -> Any:
        batch_rows.append(rows)
        return real_open(self, rows, **kwargs)

    full_reads: list[int] = []

    def no_full(self: Any, *a: Any, **k: Any) -> Any:
        full_reads.append(1)
        raise AssertionError("whole-table read")

    monkeypatch.setattr(_readers.LazySource, "open_batches", spy_open)
    monkeypatch.setattr(_readers.LazySource, "to_table", no_full)
    monkeypatch.setattr(_readers.ParquetFileSource, "to_frame", no_full)
    table = pa.table({"n": pa.array(list(range(30_000)), type=pa.int64())})
    path = tmp_path / "t.parquet"
    pq.write_table(table, path)
    cfg = _config(tmp_path, fmt="parquet", src=str(path), column=_redact("n"))
    est = estimate_job(cfg, tmp_path)
    assert est.lifecycle_peak_bytes is not None
    assert batch_rows and all(r <= 10_000 for r in batch_rows)
    assert full_reads == []


# --- AT-E1-10 ----------------------------------------------------------------------------


def test_no_cell_value_or_path_reaches_the_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / PATH_MARKER
    folder.mkdir()
    src = _csv(folder, "a,b", [f"{MARKER}{i},x" for i in range(50)])
    cfg = _config(tmp_path, fmt="csv", src=src, column=[_redact("a"), _redact("b")])
    ok = estimate_job(cfg, tmp_path)
    assert MARKER not in repr(ok) and PATH_MARKER not in repr(ok)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise ValueError(f"{MARKER} at {PATH_MARKER}")

    monkeypatch.setattr(li, "read_csv_source", boom)
    bad = estimate_job(cfg, tmp_path)
    assert MARKER not in repr(bad) and PATH_MARKER not in repr(bad)
    assert bad.lifecycle_peak_bytes is None
    assert any("ValueError" in n for n in bad.notes)


# --- AT-E1-11, AT-E1-12 ------------------------------------------------------------------


def _parquet_job(tmp_path: Path, rows: int = 100) -> dict[str, Any]:
    table = pa.table({"n": pa.array(list(range(rows)), type=pa.int64())})
    path = tmp_path / "t.parquet"
    pq.write_table(table, path)
    return _config(tmp_path, fmt="parquet", src=str(path), column=_redact("n"))


def _functions(module: Any) -> list[str]:
    return [
        name
        for name, fn in inspect.getmembers(module, inspect.isfunction)
        if fn.__module__ == module.__name__ and not name.startswith("__")
    ]


@pytest.mark.parametrize("module", [lc, li], ids=["lifecycle", "inputs"])
def test_a_failing_lifecycle_function_never_changes_the_existing_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: Any
) -> None:
    cfg = _parquet_job(tmp_path)
    clean = estimate_job(cfg, tmp_path)
    assert clean.lifecycle_peak_bytes is not None
    names = _functions(module)
    assert names
    for name in names:
        with monkeypatch.context() as m:

            def boom(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError(f"{MARKER}")

            m.setattr(module, name, boom)
            est = estimate_job(cfg, tmp_path)
        assert (est.route, est.priceable, est.peak_bytes, est.runtime) == (
            clean.route,
            clean.priceable,
            clean.peak_bytes,
            clean.runtime,
        ), name
        assert MARKER not in repr(est), name
        if est.lifecycle_peak_bytes is None:
            assert est.phase_bytes == () and est.limiting_phase is None, name
            assert any("RuntimeError" in n for n in est.notes), name


@pytest.mark.parametrize("entry", ["read_samples", "lifecycle_peak"])
def test_the_entry_points_default_the_fields_when_they_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    module = li if entry == "read_samples" else lc

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("x")

    monkeypatch.setattr(module, entry, boom)
    est = estimate_job(_parquet_job(tmp_path), tmp_path)
    assert est.lifecycle_peak_bytes is None
    assert any("RuntimeError" in n for n in est.notes)


def test_the_route_does_not_depend_on_the_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decoy_engine.execution import _pipeline_routing as routing

    widths: list[Any] = []
    real = routing.decide_execution_route

    def spy(*args: Any, **kwargs: Any) -> Any:
        widths.append(kwargs.get("largest_table_rows"))
        return real(*args, **kwargs)

    monkeypatch.setattr(routing, "decide_execution_route", spy)
    cfg = _csv_job(tmp_path)
    with_lifecycle = estimate_job(cfg, tmp_path)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("x")

    monkeypatch.setattr(li, "read_samples", boom)
    without = estimate_job(cfg, tmp_path)
    assert with_lifecycle.route == without.route
    assert widths[0] == widths[1]


# --- AT-E1-15 ----------------------------------------------------------------------------


def test_column_types_come_from_the_file_not_from_the_pandas_label(tmp_path: Path) -> None:
    ids = pa.array([None if i % 4 == 0 else i for i in range(2000)], type=pa.int32())
    path = tmp_path / "t.parquet"
    pq.write_table(pa.table({"n": ids}), path)
    cfg = _config(tmp_path, fmt="parquet", src=str(path), column=_redact("n"))
    est = estimate_job(cfg, tmp_path)
    ingest = dict(est.phase_bytes)["ingest"]
    from decoy_engine.execution._mem_estimate import route_intercept_bytes

    arrow = 4 * 2000 + 250
    # Parquet ingest: the Arrow table plus the largest row group from the footer.
    group = pq.ParquetFile(path).metadata.row_group(0).total_byte_size
    assert ingest == route_intercept_bytes("full_frame") + arrow + group


# --- AT-E1-20 ----------------------------------------------------------------------------


def test_the_format_rules_cover_exactly_the_file_formats() -> None:
    assert set(li.SAMPLE_READERS) == set(FILE_FORMATS)
    assert set(lc.INGEST_TRANSIENT) == set(FILE_FORMATS)
    assert set(lc.WRITE_TRANSIENT) == set(FILE_FORMATS)


def test_an_unknown_source_format_gives_defaults_and_a_note() -> None:
    outcome = li.read_samples(
        {"sources": {"t": {"type": "file", "path": "x", "format": "xml"}}}, [_Named("t")]
    )
    assert outcome.tables is None
    assert outcome.notes == (lc.NOTE_SOURCE_FORMAT.format(table="t"),)


def test_a_cloud_source_gives_defaults_and_a_note() -> None:
    outcome = li.read_samples({"sources": {"t": {"type": "s3", "format": "csv"}}}, [_Named("t")])
    assert outcome.tables is None
    assert outcome.notes == (lc.NOTE_SOURCE_NOT_LOCAL.format(table="t"),)


class _Named:
    def __init__(self, name: str) -> None:
        self.name = name
        self.row_count = 1
        self.row_count_exact = True
        self.columns = ()


# --- AT-E1-21 ----------------------------------------------------------------------------


def test_every_lifecycle_note_matches_a_constant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes: list[str] = []
    notes += estimate_job(_csv_job(tmp_path), tmp_path).notes

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise OSError("x")

    with monkeypatch.context() as m:
        m.setattr(li, "read_csv_source", boom)
        notes += estimate_job(_csv_job(tmp_path), tmp_path).notes
    with monkeypatch.context() as m:
        m.setattr(lc, "lifecycle_peak", boom)
        notes += estimate_job(_csv_job(tmp_path), tmp_path).notes
    lifecycle_notes = [n for n in notes if "lifecycle" in n or n.startswith("row counts")]
    assert len(lifecycle_notes) >= 3
    assert all(lc.note_matches_shape(n) for n in lifecycle_notes), lifecycle_notes


# --- AT-E1-28 (layout side) --------------------------------------------------------------


def test_an_unreadable_target_layout_leaves_the_write_term_unpriced(tmp_path: Path) -> None:
    cfg = _csv_job(tmp_path)
    cfg["targets"]["t"] = {
        "type": "file",
        "path": str(tmp_path / "o.txt"),
        "format": "fixed_width",
        "layout": "not-a-layout",
    }
    outcome = li.read_samples(cfg, _profile_tables(cfg, tmp_path))
    assert outcome.tables is not None
    attached = li.attach_targets(outcome.tables, cfg)
    assert attached.tables is None
    assert attached.notes == (lc.NOTE_LAYOUT.format(table="t"),)


def _profile_tables(cfg: dict[str, Any], base: Path) -> list[Any]:
    from decoy_engine.execution._guards import prepare_declared_execution_sources
    from decoy_engine.profile import DeclarationRequest, profile_source

    prepared = prepare_declared_execution_sources(DeclarationRequest.for_descriptors(cfg))
    return list(profile_source(cfg, seed=7, declared=prepared).tables)


# --- AT-E1-29: output specs from the plan -------------------------------------------------

ROWS = 2000


def _int_job(tmp_path: Path, column: dict[str, Any]) -> dict[str, Any]:
    table = pa.table({"n": pa.array(list(range(ROWS)), type=pa.int64())})
    path = tmp_path / "t.parquet"
    pq.write_table(table, path)
    return _config(tmp_path, fmt="parquet", src=str(path), column=column)


def _string_cell_execute(width: float) -> int | None:
    from decoy_engine.execution._mem_estimate import (
        ColumnSizeSpec,
        TableSizeSpec,
        estimate_peak_bytes,
    )

    spec = ColumnSizeSpec("n", "object", string_width_bytes=width)
    return estimate_peak_bytes((TableSizeSpec("t", ROWS, (spec,)),), "full_frame").estimated_bytes


@pytest.mark.parametrize(
    ("column", "width"),
    [
        ({"name": "n", "strategy": "hash", "namespace": "ns"}, 64.0),
        ({"name": "n", "strategy": "hash", "namespace": "ns", "truncate": 12}, 12.0),
        ({"name": "n", "strategy": "hash", "namespace": "ns", "truncate": 100}, 64.0),
        ({"name": "n", "strategy": "redact"}, 8.0),
        ({"name": "n", "strategy": "redact", "redact_with": "XX"}, 2.0),
    ],
    ids=["hash", "hash-truncate-12", "hash-truncate-100", "redact", "redact-xx"],
)
def test_an_int_column_is_priced_as_the_string_its_strategy_writes(
    tmp_path: Path, column: dict[str, Any], width: float
) -> None:
    est = estimate_job(_int_job(tmp_path, column), tmp_path)
    assert est.lifecycle_peak_bytes is not None, est.notes
    phases = dict(est.phase_bytes)
    assert phases["execute"] == _string_cell_execute(width)
    from decoy_engine.execution._mem_estimate import route_intercept_bytes

    # Inputs 8 bytes a row; outputs a 4-byte offset plus the payload a row.
    expected_write = route_intercept_bytes("full_frame") + 8 * ROWS + int(ROWS * (4 + width))
    assert phases["write"] == expected_write


def test_passthrough_keeps_the_input_cell(tmp_path: Path) -> None:
    est = estimate_job(_int_job(tmp_path, {"name": "n", "strategy": "passthrough"}), tmp_path)
    from decoy_engine.execution._mem_estimate import (
        ColumnSizeSpec,
        TableSizeSpec,
        estimate_peak_bytes,
    )

    spec = ColumnSizeSpec("n", "int64")
    base = estimate_peak_bytes((TableSizeSpec("t", ROWS, (spec,)),), "full_frame")
    assert dict(est.phase_bytes)["execute"] == base.estimated_bytes


def test_a_strategy_that_declares_nothing_leaves_an_int_column_unpriced(tmp_path: Path) -> None:
    est = estimate_job(_int_job(tmp_path, {"name": "n", "strategy": "shuffle"}), tmp_path)
    assert est.lifecycle_peak_bytes is None and est.phase_bytes == ()
    assert lc.NOTE_OUTPUT_WIDTH.format(column="t.n") in est.notes


def test_peak_bytes_and_route_ignore_the_output_specs(tmp_path: Path) -> None:
    from decoy_engine.execution._mem_estimate import (
        ColumnSizeSpec,
        TableSizeSpec,
        estimate_peak_bytes,
    )

    est = estimate_job(
        _int_job(tmp_path, {"name": "n", "strategy": "hash", "namespace": "ns"}), tmp_path
    )
    inputs = estimate_peak_bytes(
        (TableSizeSpec("t", ROWS, (ColumnSizeSpec("n", "int64"),)),), "full_frame"
    )
    assert est.peak_bytes == inputs.estimated_bytes
    assert est.route == "full_frame"


def test_an_fk_child_column_takes_its_parent_keys_output(tmp_path: Path) -> None:
    parent = pa.table({"id": pa.array(list(range(1000)), type=pa.int64())})
    child = pa.table(
        {
            "id": pa.array(list(range(2000)), type=pa.int64()),
            "pid": pa.array([i % 1000 for i in range(2000)], type=pa.int64()),
        }
    )
    pq.write_table(parent, tmp_path / "p.parquet")
    pq.write_table(child, tmp_path / "c.parquet")
    hashed = {"strategy": "hash", "namespace": "ns_p"}
    raw = {
        "version": 2,
        "global_settings": {"seed": 7},
        "sources": {
            n: {"type": "file", "path": str(tmp_path / f"{n}.parquet"), "format": "parquet"}
            for n in ("p", "c")
        },
        "targets": {
            n: {"type": "file", "path": str(tmp_path / f"{n}.out.parquet"), "format": "parquet"}
            for n in ("p", "c")
        },
        "tables": [
            {"name": "p", "columns": [{"name": "id", **hashed}]},
            {
                "name": "c",
                "columns": [
                    {"name": "id", "strategy": "passthrough"},
                    # A shorter truncate than the parent's: the edge decides the child's output.
                    {"name": "pid", **hashed, "truncate": 12},
                ],
            },
        ],
        "relationships": [
            {
                "parent": {"table": "p", "columns": ["id"]},
                "children": [{"table": "c", "columns": ["pid"]}],
                "orphan_policy": "preserve",
                "namespace": "ns_p",
            }
        ],
    }
    est = estimate_job(PipelineConfig.model_validate(raw).model_dump(), tmp_path)
    assert est.lifecycle_peak_bytes is not None, est.notes
    from decoy_engine.execution._mem_estimate import route_intercept_bytes

    arrow_in = 8 * 1000 + 8 * 2000 + 8 * 2000
    # Outputs: parent id and child pid are 64-byte tokens; the child's own id stays int64.
    arrow_out = (1000 * 68) + 8 * 2000 + (2000 * 68)
    assert (
        dict(est.phase_bytes)["write"] == route_intercept_bytes("full_frame") + arrow_in + arrow_out
    )
