"""bucket_perturb never passes a source value through (COLUMN-SHAPE-RULE slice E0).

Two old paths kept the source text in the output without saying so: a format that
resolved to None returned the whole column unchanged, and a non-null cell that did
not parse was kept as it was. Both are now refusals: the first raises a coded
runtime error, the second is a `format_error` row error. Both backends, every route.

Marker strings below stand in for cell values; no refusal or row error may carry one.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine import reasons, run_pipeline
from decoy_engine._execution_error import ExecutionError
from decoy_engine.config import PipelineConfig
from decoy_engine.errors import RowErrorsFailedError
from decoy_engine.execution import PandasExecutionAdapter
from decoy_engine.execution.native._bucket_perturb_ext import native_bucket_perturb
from decoy_engine.execution.native._companion_status import native_companion_status
from decoy_engine.execution.native._index_ext import load_compiled_index_kernel
from decoy_engine.plan import PlanCompileError
from decoy_engine.plan._types import ColumnSeed, SeedEnvelope, TableSeed
from decoy_engine.providers_v2 import get_default_registry
from decoy_engine.relationships._graph import RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceRegistry
from decoy_engine.transforms.bucket_perturb import FORMAT_ERROR_REASON, apply_bucket_perturb

_SEED = b"\xb0\x0c\xfe\x00\x12\x34\x56\x78"
_MARKER = "SECRETMARKER-4471"
_FMT = "%Y-%m-%d"
_NEEDS_COMPANION = pytest.mark.skipif(
    not native_companion_status().ok, reason="compiled decoy-engine-native companion unavailable"
)
_NEVER_A_DATE = [_MARKER, "zzz", "nothing", "???"]  # detection cannot read any of these
_MIXED = ["2024-06-15", None, _MARKER, "2024-08-20", "2024-13-45"]


def _no_marker(text: str) -> None:
    assert _MARKER not in text


# -- the transform itself ----------------------------------------------------------------


def test_transform_refuses_when_format_resolves_to_none() -> None:
    series = pd.Series(_NEVER_A_DATE)
    with pytest.raises(ExecutionError) as caught:
        apply_bucket_perturb(series, "month", _SEED, "dates", None)
    assert caught.value.code == reasons.runtime.BUCKET_PERTURB_REQUIRES_DATE_FORMAT
    _no_marker(str(caught.value))
    assert "date_format" in caught.value.message


def test_null_stays_null() -> None:
    errors: list[int] = []
    out = apply_bucket_perturb(
        pd.Series(["2024-06-15", None, "2024-08-20"]), "month", _SEED, "d", _FMT, errors
    )
    assert out.iloc[1] is None
    assert errors == []


def test_unparseable_cell_is_reported_by_the_transform() -> None:
    errors: list[int] = []
    out = apply_bucket_perturb(pd.Series(_MIXED), "month", _SEED, "d", _FMT, errors)
    assert errors == [2, 4]
    assert out.iloc[1] is None
    assert FORMAT_ERROR_REASON == "value is not a parseable date under bucket_perturb"
    _no_marker(FORMAT_ERROR_REASON)


def test_transform_without_a_row_channel_refuses_instead_of_passing_through() -> None:
    with pytest.raises(ExecutionError) as caught:
        apply_bucket_perturb(pd.Series(_MIXED), "month", _SEED, "d", _FMT)
    assert caught.value.code == reasons.runtime.BUCKET_PERTURB_UNPARSEABLE_NO_ROW_CHANNEL
    _no_marker(str(caught.value))
    assert "2 non-null" in caught.value.message


# -- the handler, pandas backend ----------------------------------------------------------


def _seed(provider_config: tuple[tuple[str, Any], ...]) -> ColumnSeed:
    return ColumnSeed(
        namespace="bp",
        strategy="bucket_perturb",
        provider="bucket_perturb",
        backend_type="faker",
        backend_version="v",
        cardinality_mode="reuse",
        deterministic=True,
        provider_config=provider_config,
        coherent_with=(),
    )


def _run_handler(values: list[Any], provider_config: tuple[tuple[str, Any], ...]) -> Any:
    plan = SimpleNamespace(
        seed_envelope=SeedEnvelope(
            job_seed=_SEED,
            per_table=(
                ("t", TableSeed(per_column=(("d", _seed(provider_config)),), per_group=())),
            ),
        )
    )
    table = pa.table({"d": pa.array(values, type=pa.string())})
    return PandasExecutionAdapter().run_single(
        plan,
        table,
        registry=get_default_registry(),
        relationship_graph=RelationshipGraph(edges=(), ordering=()),
        namespace_registry=NamespaceRegistry(bindings=()),
    )


def test_handler_refuses_when_format_resolves_to_none() -> None:
    with pytest.raises(ExecutionError) as caught:
        _run_handler(_NEVER_A_DATE, (("bucket", "month"),))
    assert caught.value.code == reasons.runtime.BUCKET_PERTURB_REQUIRES_DATE_FORMAT
    _no_marker(str(caught.value))


def test_unparseable_cell_is_row_error() -> None:
    result = _run_handler(_MIXED, (("bucket", "month"), ("date_format", _FMT)))
    records = result.row_errors
    assert [r.row_index for r in records] == [2, 4]
    assert {r.trigger for r in records} == {"format_error"}
    assert {r.column for r in records} == {"d"}
    assert {r.reason for r in records} == {FORMAT_ERROR_REASON}
    for record in records:
        _no_marker(repr(record))


def test_row_error_index_is_the_frame_position_past_a_preserved_row() -> None:
    result = _run_handler(
        ["9999-12-31", "2024-06-15", _MARKER, "2024-08-20"],
        (("bucket", "month"), ("date_format", _FMT), ("preserve_values", ["9999-12-31"])),
    )
    assert [r.row_index for r in result.row_errors] == [2]
    assert result.output.column("d").to_pylist()[0] == "9999-12-31"
    for record in result.row_errors:
        _no_marker(repr(record))


# Recorded from origin/main before this slice: valid rows must not move.
_CLEAN = ["2024-06-15", None, "2024-08-20", "2023-02-28"]
_GOLDEN = {
    "month": ["2024-06-26", None, "2024-08-18", "2023-02-14"],
    "quarter": ["2024-04-19", None, "2024-09-04", "2023-01-22"],
}


@pytest.mark.parametrize("bucket", ["month", "quarter"])
def test_explicit_format_output_unchanged(bucket: str) -> None:
    out = apply_bucket_perturb(pd.Series(_CLEAN), bucket, _SEED, "bp", _FMT)
    assert list(out) == _GOLDEN[bucket]


def test_handler_clean_run_has_no_row_errors() -> None:
    result = _run_handler(_CLEAN, (("bucket", "month"), ("date_format", _FMT)))
    assert result.row_errors == ()
    assert result.output.column("d").to_pylist()[1] is None


# -- the whole pipeline: full frame and chunked -------------------------------------------


def _config(tmp_path: Path, date_format: str | None) -> dict:
    cfg: dict[str, Any] = {"bucket": "month"}
    if date_format is not None:
        cfg["date_format"] = date_format
    col = {"name": "d", "strategy": "bucket_perturb", "namespace": "bp", "provider_config": cfg}
    return PipelineConfig.model_validate(
        {
            "version": 2,
            "global_settings": {"seed": 7},
            "sources": {
                "records": {
                    "type": "file",
                    "format": "csv",
                    "has_header": True,
                    "path": str(tmp_path / "records.csv"),
                }
            },
            "tables": [{"name": "records", "columns": [col]}],
            "targets": {
                "records": {"type": "file", "format": "csv", "path": str(tmp_path / "out.csv")}
            },
        }
    ).model_dump()


def _run(tmp_path: Path, values: list[Any], date_format: str | None, *, chunked: bool) -> Any:
    table = pa.table({"d": pa.array(values, type=pa.string())})
    table.to_pandas().to_csv(tmp_path / "records.csv", index=False)
    kwargs: dict[str, Any] = (
        {"auto_chunk_threshold_rows": 2, "chunk_size_rows": 2} if chunked else {"auto_chunk": False}
    )
    return run_pipeline(
        _config(tmp_path, date_format),
        sources={"records": table},
        engine_version="e0-test",
        **kwargs,
    )


@pytest.mark.parametrize("chunked", [False, True], ids=["full-frame", "chunked"])
def test_pipeline_refuses_when_format_resolves_to_none(tmp_path: Path, chunked: bool) -> None:
    # COLUMN-SHAPE E2, plan 2026-11-21-column-shape-rule section 3.2 (`bucket_perturb` on text:
    # `date_format` required, else `column_shape_required`): plan compile refuses before any row
    # is read. The transform and handler refusals stay as the backstop, pinned above.
    with pytest.raises(PlanCompileError) as caught:
        _run(tmp_path, _NEVER_A_DATE * 2, None, chunked=chunked)
    assert caught.value.code == reasons.plan.COLUMN_SHAPE_REQUIRED
    _no_marker(str(caught.value))


@pytest.mark.parametrize("chunked", [False, True], ids=["full-frame", "chunked"])
def test_pipeline_fails_on_unparseable_cell(tmp_path: Path, chunked: bool) -> None:
    with pytest.raises(RowErrorsFailedError) as caught:
        _run(tmp_path, ["2024-06-15", _MARKER, "2024-08-20", None], _FMT, chunked=chunked)
    assert {r.trigger for r in caught.value.records} == {"format_error"}
    assert {r.reason for r in caught.value.records} == {FORMAT_ERROR_REASON}
    _no_marker(str(caught.value))
    for record in caught.value.records:
        _no_marker(repr(record))


# -- native backend ------------------------------------------------------------------------


@_NEEDS_COMPANION
def test_native_unparseable_cell_is_reported_like_the_oracle() -> None:
    kernel = load_compiled_index_kernel()
    array = pa.array(_MIXED, type=pa.string())
    out, positions = native_bucket_perturb(
        array,
        bucket="month",
        date_format=_FMT,
        mask_key=_SEED,
        namespace="bp",
        index_kernel=kernel,
    )
    oracle_errors: list[int] = []
    oracle = apply_bucket_perturb(pd.Series(_MIXED), "month", _SEED, "bp", _FMT, oracle_errors)
    assert list(positions) == oracle_errors == [2, 4]
    assert out.to_pylist() == list(oracle)


@_NEEDS_COMPANION
def test_native_positions_rebase_past_preserved_rows() -> None:
    import numpy as np

    kernel = load_compiled_index_kernel()
    values = ["2024-06-15", "KEEP", _MARKER, "2024-08-20"]
    _, positions = native_bucket_perturb(
        pa.array(values, type=pa.string()),
        bucket="month",
        date_format=_FMT,
        mask_key=_SEED,
        namespace="bp",
        index_kernel=kernel,
        preserved=np.array([False, True, False, False]),
    )
    assert positions == (2,)


@_NEEDS_COMPANION
def test_native_explicit_format_output_unchanged() -> None:
    kernel = load_compiled_index_kernel()
    out, positions = native_bucket_perturb(
        pa.array(_CLEAN, type=pa.string()),
        bucket="quarter",
        date_format=_FMT,
        mask_key=_SEED,
        namespace="bp",
        index_kernel=kernel,
    )
    assert positions == ()
    assert out.to_pylist() == _GOLDEN["quarter"]


def test_messages_value_free() -> None:
    for code in (
        reasons.runtime.BUCKET_PERTURB_REQUIRES_DATE_FORMAT,
        reasons.runtime.BUCKET_PERTURB_UNPARSEABLE_NO_ROW_CHANNEL,
    ):
        _no_marker(reasons.get("runtime", code).summary)


# -- the one format_error builder, both operators --------------------------------------------


@pytest.mark.parametrize(
    "strategy, reason",
    [
        ("bucket_perturb", "value is not a parseable date under bucket_perturb"),
        ("date_shift", "value is not a parseable date under date_shift"),
    ],
)
def test_one_builder_serves_both_operators_value_free(strategy: str, reason: str) -> None:
    from decoy_engine.execution._operator_registry import OPERATORS
    from decoy_engine.execution.native._chunked_row_errors import format_error_records
    from decoy_engine.execution.native._date_shift_ext import format_error_row_errors

    operator_id = OPERATORS[strategy].operator_id
    rows = format_error_row_errors("c", (3, 5), operator_id)
    assert [(r.column, r.row_index, r.trigger, r.reason) for r in rows] == [
        ("c", 3, "format_error", reason),
        ("c", 5, "format_error", reason),
    ]
    records = format_error_records(
        "t", {"c": (3, 5)}, bucket_columns={"c"} if strategy == "bucket_perturb" else ()
    )
    assert [(r.table, r.column, r.row_index, r.reason) for r in records] == [
        ("t", "c", 3, reason),
        ("t", "c", 5, reason),
    ]


def test_sequential_bindings_and_a_mixed_records_call() -> None:
    from decoy_engine.execution._sequential_native_ops import (
        bucket_row_errors,
        date_shift_row_errors,
    )
    from decoy_engine.execution.native._chunked_row_errors import format_error_records

    bucket = FORMAT_ERROR_REASON
    shift = "value is not a parseable date under date_shift"
    assert [(r.row_index, r.reason) for r in bucket_row_errors("b", (1, 4))] == [
        (1, bucket),
        (4, bucket),
    ]
    assert [(r.row_index, r.reason) for r in date_shift_row_errors("d", (2,))] == [(2, shift)]
    records = format_error_records("t", {"b": (1,), "d": (2,)}, bucket_columns={"b"})
    assert [(r.column, r.row_index, r.reason) for r in records] == [
        ("b", 1, bucket),
        ("d", 2, shift),
    ]
