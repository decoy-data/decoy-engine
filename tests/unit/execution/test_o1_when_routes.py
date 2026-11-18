"""O1 acceptance (AT-O1a, AT-O1b, AT-O1f): `when:` on integer columns is exact beyond 2**53 and
selects blank rows by one NaN-style rule on every route and column class.

Plan: `docs/plans/2026-11-18-freeze-batch.md` rev 3.2, sections 4.3 and 8. Every cell first asserts
the route-owned witness of the lane that ran (the pipeline's own metrics, or a recorder around the
chunked leg's adapter), so a cell that silently ran elsewhere cannot pass. The expected selection is
the Python-integer reference in `_o1_when_support.py`.

Known limit (plan 5.3): there is no route registry, so the route list is the constants below.
A new route must add itself here.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

import pyarrow as pa
import pytest

from decoy_engine.execution._pandas_adapter import PandasExecutionAdapter
from decoy_engine.execution._pipeline import run_pipeline
from tests.native._b8_support import (
    run_mask_chunked_below_gate,
    run_mask_pipeline_chunked_below_gate,
)
from tests.native._chunked_entry_support import ENGINE_VERSION, key_provider, split
from tests.unit.execution._o1_when_support import (
    CLASSES,
    FLOAT_OPS,
    ID_SOURCE,
    M_SOURCE,
    OPS,
    VALUES,
    build_case,
    reference,
    selected_rows,
)

ALL_EXPRESSIONS = [*OPS, *FLOAT_OPS]
# Classes whose `v` is still an integer after the run (a top_code column becomes its label text).
INT_OUTPUT = ["plain", "fk", "declared", "anchor", "group_key"]
# The classes unified admission takes today. The others are asserted as the explicit fallback.
COMPANION = importlib.util.find_spec("decoy_engine_native") is not None
# With the companion installed `group_key` also runs natively and on the unified lane (it needs the
# raw-hex extension); without it the job takes the oracle and the full-frame lane.
UNIFIED_ADMITS = {"declared", "plain"} | ({"group_key"} if COMPANION else set())
CHUNK_SIZES = [1, 2, 3, len(VALUES)]
# `run_mask_chunked` takes plain columns natively; the other classes reroute to the oracle.
NATIVE_ADMITS = {"plain"} | ({"group_key"} if COMPANION else set())


def _run(cfg: dict[str, Any], tables: dict[str, pa.Table], **kw: Any) -> Any:
    return run_pipeline(cfg, tables, engine_version="o1", key_provider=key_provider(), **kw)


def _fk_fallback_witness(qm: dict[str, Any]) -> None:
    """A unified-requested job that unified admission rejects: no activation, and the physical
    fallback that handled it is the full-frame lane (plan 5.3)."""
    assert "unified_slice_activation" not in qm
    assert qm["execution"]["execution_mode"] == "full_frame"


def _witness(route: str, cls: str, qm: dict[str, Any]) -> None:
    if route == "full_frame":
        assert "unified_slice_activation" not in qm
        assert qm["execution"]["execution_mode"] == "full_frame"
    elif route == "unified":
        if cls in UNIFIED_ADMITS:
            assert "unified_slice_activation" in qm
        else:
            _fk_fallback_witness(qm)
    else:
        assert route == "sequential"
        assert qm["execution"]["execution_mode"] == "sequential"
        assert "unified_slice_activation" not in qm


def _kwargs(route: str) -> dict[str, Any]:
    return {
        "full_frame": {
            "execution_mode": "full_frame",
            "auto_chunk": False,
            "unified_slice_enabled": False,
        },
        "unified": {
            "execution_mode": "full_frame",
            "auto_chunk": False,
            "unified_slice_enabled": True,
        },
        "sequential": {
            "execution_mode": "sequential",
            "auto_chunk": False,
            "unified_slice_enabled": False,
        },
    }[route]


RESIDENT_CELLS = [
    *[("full_frame", c) for c in CLASSES],
    *[("unified", c) for c in CLASSES],
    ("sequential", "fk"),
]


@pytest.mark.parametrize(("route", "cls"), RESIDENT_CELLS)
def test_resident_routes_select_like_the_python_reference(
    tmp_path: Path, route: str, cls: str
) -> None:
    for expression in ALL_EXPRESSIONS:
        cfg, tables = build_case(cls, tmp_path, expression)
        result = _run(cfg, tables, **_kwargs(route))
        _witness(route, cls, result.quality_metrics)
        got = selected_rows(result.outputs["t"], M_SOURCE)
        assert got == reference(expression, VALUES), (route, cls, expression)


@contextmanager
def _adapter_calls() -> Iterator[list[Any]]:
    """The chunked oracle leg's production witness: one `PandasExecutionAdapter.run` per chunk."""
    calls: list[Any] = []
    real = PandasExecutionAdapter.run

    def spy(self: Any, *a: Any, **k: Any) -> Any:
        calls.append(1)
        return real(self, *a, **k)

    with mock.patch.object(PandasExecutionAdapter, "run", spy):
        yield calls


def _per_chunk_selection(outputs: list[pa.Table]) -> list[bool]:
    return [
        x
        for o in outputs
        for x in selected_rows(
            o, [M_SOURCE[ID_SOURCE.index(i)] for i in o.column("id").to_pylist()]
        )
    ]


CHUNKED_CLASSES = [c for c in CLASSES if c not in ("fk", "declared")]


@pytest.mark.parametrize("size", CHUNK_SIZES)
@pytest.mark.parametrize("cls", CHUNKED_CLASSES)
def test_chunked_oracle_selects_like_the_python_reference(
    tmp_path: Path, cls: str, size: int
) -> None:
    for expression in ALL_EXPRESSIONS:
        cfg, tables = build_case(cls, tmp_path, expression)
        chunks = split(tables["t"], size)
        with _adapter_calls() as calls:
            out = list(
                run_mask_pipeline_chunked_below_gate(
                    cfg,
                    chunks,
                    table="t",
                    source_schema=tables["t"].schema,
                    engine_version=ENGINE_VERSION,
                    key_provider=key_provider(),
                )
            )
        assert len(calls) == len(chunks), "the chunked oracle leg did not run per chunk"
        assert _per_chunk_selection(out) == reference(expression, VALUES), (cls, size, expression)


@pytest.mark.parametrize("size", CHUNK_SIZES)
@pytest.mark.parametrize("cls", CHUNKED_CLASSES)
def test_chunked_native_selects_like_the_python_reference(
    tmp_path: Path, cls: str, size: int
) -> None:
    for expression in ALL_EXPRESSIONS:
        cfg, tables = build_case(cls, tmp_path, expression)
        ev: list[Any] = []
        out = list(
            run_mask_chunked_below_gate(
                cfg,
                split(tables["t"], size),
                table="t",
                engine_version=ENGINE_VERSION,
                key_provider=key_provider(),
                route_evidence_sink=ev,
            )
        )
        if cls in NATIVE_ADMITS:
            assert ev[0].native_admitted is True, ev[0]
        else:
            assert ev[0].native_admitted is False, ev[0]
            assert ev[0].reroute_reason, ev[0]
        assert _per_chunk_selection(out) == reference(expression, VALUES), (cls, size, expression)


# -- AT-O1f: the passed-through integer column keeps its integer type ----------------------------


def _types(outputs: list[pa.Table]) -> set[str]:
    return {str(o.schema.field("v").type) for o in outputs}


@pytest.mark.parametrize(("route", "cls"), [r for r in RESIDENT_CELLS if r[1] in INT_OUTPUT])
def test_resident_routes_write_the_blank_bearing_integer_as_int64(
    tmp_path: Path, route: str, cls: str
) -> None:
    cfg, tables = build_case(cls, tmp_path, OPS[0])
    result = _run(cfg, tables, **_kwargs(route))
    _witness(route, cls, result.quality_metrics)
    assert result.outputs["t"].schema.field("v").type == pa.int64(), (route, cls)


@pytest.mark.parametrize("size", CHUNK_SIZES)
@pytest.mark.parametrize("cls", [c for c in CHUNKED_CLASSES if c in INT_OUTPUT])
def test_chunked_routes_write_the_blank_bearing_integer_as_int64(
    tmp_path: Path, cls: str, size: int
) -> None:
    cfg, tables = build_case(cls, tmp_path, OPS[0])
    chunks = split(tables["t"], size)
    with _adapter_calls() as calls:
        out = list(
            run_mask_pipeline_chunked_below_gate(
                cfg,
                chunks,
                table="t",
                source_schema=tables["t"].schema,
                engine_version=ENGINE_VERSION,
                key_provider=key_provider(),
            )
        )
    assert len(calls) == len(chunks)
    assert _types(out) == {"int64"}, (cls, size)


@pytest.mark.parametrize("cls", sorted(UNIFIED_ADMITS))
@pytest.mark.parametrize("expression", [OPS[0], OPS[1], OPS[7]])
def test_unified_flag_on_and_off_agree_on_values_types_and_metadata(
    tmp_path: Path, cls: str, expression: str
) -> None:
    cfg, tables = build_case(cls, tmp_path, expression)
    on = _run(cfg, tables, **_kwargs("unified"))
    assert "unified_slice_activation" in on.quality_metrics
    off = _run(cfg, tables, **_kwargs("full_frame"))
    assert "unified_slice_activation" not in off.quality_metrics
    a, b = on.outputs["t"], off.outputs["t"]
    assert a.equals(b)
    assert a.schema.equals(b.schema, check_metadata=True)
