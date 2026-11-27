"""The type gate on the run routes (DATE-RANGE-SENTINEL S5, section 4.4b, AT-V3).

A resident table with a date inside a container, or a dictionary of one, is refused on every
route with `runtime/source_date_type_unsupported`, by table, column and kind, before a chunk is
profiled, staged or computed. The isolated parent gates the schema under the mapping key before
Arrow IPC admission, so the IPC-specific reasons never hide it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine import reasons
from decoy_engine.execution import run_pipeline, run_pipeline_isolated
from decoy_engine.execution._chunked import run_mask_pipeline_chunked
from decoy_engine.execution.native._chunked_entry import run_mask_chunked as run_native_chunked
from decoy_engine.fileaccess.adapters import arrow as arrow_adapter
from decoy_engine.io import SourceDateTypeUnsupportedError
from tests.unit.execution import _auto_chunk_support as support
from tests.unit.io.test_source_date_type_gate import _DateExt

TABLE = support.TABLE
CODE = reasons.runtime.SOURCE_DATE_TYPE_UNSUPPORTED
ROUTES = {"FF": {"execution_mode": "full_frame", "auto_chunk": False}, "AUTO": {}}


def _cfg(path: Path | None = None) -> dict[str, Any]:
    columns = [support.pass_col("id"), support.pass_col("events")]
    return support.make_cfg(columns, path=str(path) if path else "/dev/null")


def _declared(tmp_path: Path) -> Path:
    """A real source file the parent can profile, so the run reaches the source gate."""
    path = tmp_path / "declared.parquet"
    pq.write_table(pa.table({"id": [0, 1], "events": ["a", "b"]}), str(path))
    return path


def _dictionary_of_list() -> pa.Array:
    values = pa.array([[0], [1]], pa.list_(pa.date32()))
    return pa.DictionaryArray.from_arrays(pa.array([0, 1, 0], pa.int8()), values)


def _dictionary_of_extension() -> pa.Array:
    values = pa.ExtensionArray.from_storage(_DateExt(), pa.array([0, 1], pa.date32()))
    return pa.DictionaryArray.from_arrays(pa.array([0, 1, 0], pa.int8()), values)


def _table(events: pa.Array) -> pa.Table:
    return pa.table({"id": pa.array(range(len(events))), "events": events})


def _assert_refusal(exc: BaseException, kind: str) -> None:
    assert isinstance(exc, SourceDateTypeUnsupportedError)
    assert (exc.table, exc.column, exc.kind, exc.code) == (TABLE, "events", kind, CODE)
    assert exc.__cause__ is None and exc.__context__ is None


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("shape", ["dictionary_of_list", "dictionary_of_extension"])
def test_a_resident_dictionary_of_a_date_bearing_type_is_refused_on_ff_and_auto(
    route: str, shape: str
) -> None:
    table = _table(
        _dictionary_of_list() if shape == "dictionary_of_list" else _dictionary_of_extension()
    )
    with pytest.raises(SourceDateTypeUnsupportedError) as caught:
        run_pipeline(_cfg(), sources={TABLE: table}, **support.run_kwargs(**ROUTES[route]))
    _assert_refusal(caught.value, "dictionary")


@pytest.mark.parametrize("make", [_dictionary_of_list, _dictionary_of_extension])
def test_the_chunked_apis_refuse_a_dictionary_of_a_date_bearing_type(make: Any) -> None:
    table = _table(make())
    with pytest.raises(SourceDateTypeUnsupportedError) as caught:
        list(
            run_mask_pipeline_chunked(
                _cfg(),
                iter([table]),
                table=TABLE,
                engine_version=support.ENGINE_VERSION,
                source_schema=table.schema,
            )
        )
    _assert_refusal(caught.value, "dictionary")
    with pytest.raises(SourceDateTypeUnsupportedError) as caught:
        list(
            run_native_chunked(
                _cfg(), iter([table]), table=TABLE, engine_version=support.ENGINE_VERSION
            )
        )
    _assert_refusal(caught.value, "dictionary")


def test_an_empty_stream_with_a_supplied_schema_is_gated_on_the_oracle() -> None:
    schema = pa.schema(
        [("id", pa.int64()), ("events", pa.dictionary(pa.int8(), pa.list_(pa.date32())))]
    )
    with pytest.raises(SourceDateTypeUnsupportedError) as caught:
        list(
            run_mask_pipeline_chunked(
                _cfg(),
                iter([]),
                table=TABLE,
                engine_version=support.ENGINE_VERSION,
                source_schema=schema,
            )
        )
    _assert_refusal(caught.value, "dictionary")


@pytest.mark.parametrize("make", [_dictionary_of_list, _dictionary_of_extension])
def test_the_isolated_parent_gates_before_ipc_admission_and_staging(
    make: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def reached(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a rejected source reached staging")

    for name in ("write_table", "ipc_new_stream", "ipc_write_exact", "ipc_refusal"):
        monkeypatch.setattr(arrow_adapter, name, reached)
    table = _table(make())
    with pytest.raises(SourceDateTypeUnsupportedError) as caught:
        run_pipeline_isolated(
            _cfg(_declared(tmp_path)),
            {TABLE: table},
            engine_version=support.ENGINE_VERSION,
            isolate=True,
        )
    _assert_refusal(caught.value, "dictionary")
    result = run_pipeline_isolated(
        _cfg(_declared(tmp_path)),
        {TABLE: table},
        engine_version=support.ENGINE_VERSION,
        isolate=False,
    )
    assert result.outcome == "crashed" and result.outputs is None
    assert "SourceDateTypeUnsupportedError" in (result.error or "")
    assert "events" not in (result.error or "")


def test_a_non_date_ipc_refusal_keeps_its_own_reason(tmp_path: Path) -> None:
    from decoy_engine.io import UnsupportedColumnType

    dictionary = pa.DictionaryArray.from_arrays(
        pa.array([0, 1], pa.int8()),
        pa.DictionaryArray.from_arrays(pa.array([0, 0], pa.int8()), pa.array(["a"])),
    )
    with pytest.raises(UnsupportedColumnType):
        run_pipeline_isolated(
            _cfg(_declared(tmp_path)),
            {TABLE: _table(dictionary)},
            engine_version=support.ENGINE_VERSION,
            isolate=True,
        )
