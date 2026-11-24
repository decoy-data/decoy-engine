"""S1k: the array kernel against the pandas handlers, and the shared settings and renderers.

The handlers are the oracle. Each case runs the real handler on a pandas column and the kernel on
the same values as an Arrow array, then compares every cell, the bad positions and the warning
counts. The expected values in the literal tests are hand-worked, not read from either side.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine import reasons
from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._strategies import (
    BucketizeSettings,
    TopCodeSettings,
    render_exceptional_bucket_labels,
    render_exceptional_top_code,
    resolve_bucketize_settings,
    resolve_top_code_settings,
    top_code_warning,
)
from decoy_engine.execution._strategies._bucketize import BucketizeStrategyHandler
from decoy_engine.execution._strategies._top_code import TopCodeStrategyHandler
from decoy_engine.kernel import SparseLabels, bucketize_array, floor_multiple, top_code_array
from decoy_engine.plan._types import ColumnSeed

INF = math.inf
TWO53 = 2**53
RANGE_REASON = "value is out of range under bucketize"


def _seed(strategy: str, **pc: Any) -> ColumnSeed:
    return ColumnSeed(
        namespace=None,
        strategy=strategy,
        provider=strategy,
        backend_type="faker",
        backend_version="v",
        cardinality_mode="reuse",
        deterministic=False,
        provider_config=tuple(sorted(pc.items())),
        coherent_with=(),
    )


def _ctx() -> StrategyContext:
    stub: Any = SimpleNamespace()
    return StrategyContext(
        registry=stub,
        pool_cache=stub,
        relationship_graph=stub,
        namespace_registry=stub,
        job_seed=b"\x00" * 8,
        current_table="t",
        column_shapes={("t", "n"): ColumnShape.INTEGER},
    )


def _cells(series: pd.Series) -> list[Any]:
    return [None if pd.isna(v) else v for v in series.tolist()]


def _bucketize_handler(column: pd.Series, **pc: Any) -> tuple[list[Any], list[int]]:
    ctx = _ctx()
    out, warnings = BucketizeStrategyHandler().run(
        pd.DataFrame({"n": column.copy()}), "n", _seed("bucketize", **pc), ctx
    )
    assert warnings == []
    assert all(e.reason == RANGE_REASON for e in ctx.row_errors)
    return _cells(out["n"]), [e.row_index for e in ctx.row_errors]


def _top_code_handler(column: pd.Series, **pc: Any) -> tuple[list[Any], dict[str, Any] | None]:
    ctx = _ctx()
    out, warnings = TopCodeStrategyHandler().run(
        pd.DataFrame({"n": column.copy()}), "n", _seed("top_code", **pc), ctx
    )
    assert ctx.row_errors == []
    detail = dict(warnings[0].detail) if warnings else None
    return _cells(out["n"]), detail


INT64_EDGES: list[int | None] = [
    -(2**63), 2**63 - 1, 2**63 - 10, TWO53 - 1, TWO53, TWO53 + 1, 2**62 + 7,
    -TWO53, -TWO53 + 1, 0, 15, -15, None,
]  # fmt: skip
FLOAT_EDGES: list[float] = [
    INF, -INF, 1e19, -1e300, 5e-324, -5e-324, 0.0, -0.0, float(TWO53 - 1), float(TWO53),
    float(TWO53 + 2), -float(TWO53), 15.5, 99.9, -0.5, math.nan,
]  # fmt: skip


def _columns() -> list[tuple[str, pd.Series, pa.Array]]:
    ints = [v for v in INT64_EDGES if v is not None]
    return [
        ("int64", pd.Series(ints, dtype="int64"), pa.array(ints, pa.int64())),
        ("Int64", pd.Series(INT64_EDGES, dtype="Int64"), pa.array(INT64_EDGES, pa.int64())),
        (
            "int64[pyarrow]",
            pd.Series(INT64_EDGES, dtype="int64[pyarrow]"),
            pa.array(INT64_EDGES, pa.int64()),
        ),
        (
            "uint32",
            pd.Series([0, 4294967295, 7], dtype="uint32"),
            pa.array([0, 4294967295, 7], pa.uint32()),
        ),
        ("float64", pd.Series(FLOAT_EDGES), pa.array(FLOAT_EDGES, pa.float64())),
    ]


COLUMNS = _columns()


@pytest.mark.parametrize("fmt", ["lower", "range", "midpoint"])
@pytest.mark.parametrize("width", [10, 7, 2.5])
@pytest.mark.parametrize(("name", "column", "array"), COLUMNS, ids=[c[0] for c in COLUMNS])
def test_bucketize_kernel_equals_the_handler(
    name: str, column: pd.Series, array: pa.Array, width: int | float, fmt: str
) -> None:
    cells, bad = _bucketize_handler(column, width=width, format=fmt)
    result = bucketize_array(array, width, fmt)
    assert result.labels.to_pylist() == cells, name
    assert result.exit_positions.to_pylist() == bad, name


# Every column dtype, including a null-bearing int64[pyarrow], which the handler used to render
# through float64 ("-1.0" and lost digits past 2**53) while the kernel printed exact integers.
TOP_CODE_COLUMNS = COLUMNS


@pytest.mark.parametrize(
    ("name", "column", "array"), TOP_CODE_COLUMNS, ids=[c[0] for c in TOP_CODE_COLUMNS]
)
@pytest.mark.parametrize("floor", [None, 40])
def test_top_code_kernel_equals_the_handler(
    name: str, column: pd.Series, array: pa.Array, floor: int | None
) -> None:
    pc: dict[str, Any] = {"cap": 89, "over_label": "90+"}
    if floor is not None:
        pc |= {"floor": floor, "under_label": "under 40"}
    cells, detail = _top_code_handler(column, **pc)
    result = top_code_array(array, 89, "90+", floor, "under 40" if floor is not None else None)
    assert result.labels.to_pylist() == cells, name
    assert top_code_warning("n", result.over_count, result.under_count) == (
        None
        if detail is None
        else top_code_warning("n", detail["over_count"], detail["under_count"])
    )


def test_top_code_warning_builder_matches_the_handler_warning() -> None:
    ctx = _ctx()
    _, warnings = TopCodeStrategyHandler().run(
        pd.DataFrame({"n": pd.Series([10, 95, 99, 20], dtype="int64")}),
        "n",
        _seed("top_code", cap=89, over_label="90+", floor=15, under_label="low"),
        ctx,
    )
    built = top_code_warning("n", 2, 1)
    assert built is not None
    assert warnings == [built]
    assert built.code == reasons.warning.TOP_CODE_GENERALIZED
    assert built.provider == "top_code" and built.column == "n"
    assert dict(built.detail) == {"over_count": 2, "under_count": 1}
    assert top_code_warning("n", 0, 0) is None


# Literal settings: a preset beats width, an unknown format falls back to lower.
def test_bucketize_settings_resolution() -> None:
    assert resolve_bucketize_settings(
        {"preset": "by_decade", "width": 3}, "n"
    ) == BucketizeSettings(10, "lower", False)
    assert resolve_bucketize_settings({"width": 2.5, "format": "RANGE"}, "n") == BucketizeSettings(
        2.5, "range", False
    )
    assert resolve_bucketize_settings({"width": 5, "format": "bogus"}, "n").fmt == "lower"
    flagged = resolve_bucketize_settings({"width": 5, "declared_integer_output": True}, "n")
    assert flagged.declared_integer_output is True


@pytest.mark.parametrize(
    "cfg", [{}, {"width": 0}, {"width": -1}, {"width": True}, {"preset": "nope"}]
)
def test_bucketize_settings_fail_closed(cfg: dict[str, Any]) -> None:
    with pytest.raises(StrategyError) as err:
        resolve_bucketize_settings(cfg, "n")
    assert err.value.code == reasons.runtime.BUCKETIZE_WIDTH_UNRESOLVABLE


def test_top_code_settings_resolution() -> None:
    assert resolve_top_code_settings({"preset": "hipaa_age"}, "n") == TopCodeSettings(
        89, "90+", None, None
    )
    assert resolve_top_code_settings(
        {"cap": 50.5, "over_label": "hi", "floor": 10, "under_label": "lo"}, "n"
    ) == TopCodeSettings(50.5, "hi", 10, "lo")


@pytest.mark.parametrize(
    "cfg",
    [
        {},
        {"cap": 10},
        {"cap": 10, "over_label": ""},
        {"cap": True, "over_label": "x"},
        {"cap": TWO53, "over_label": "x"},
        {"cap": 10, "over_label": "x", "floor": 1},
        {"cap": 10, "over_label": "x", "floor": None, "under_label": "u"},
        {"preset": "nope"},
    ],
)
def test_top_code_settings_fail_closed(cfg: dict[str, Any]) -> None:
    with pytest.raises(StrategyError) as err:
        resolve_top_code_settings(cfg, "n")
    assert err.value.code == reasons.runtime.TOP_CODE_BOUNDS_UNRESOLVABLE


# Sparse exceptional positions: valid NaN under a pandas extension dtype.
def _nan_columns() -> list[tuple[str, pd.Series, pa.Array]]:
    values = np.array([math.nan, 4.0, 0.0, math.nan])
    mask = np.array([False, False, True, False])
    arrow = pa.array([math.nan, 4.0, None, math.nan], pa.float64())
    return [
        ("float64", pd.Series([math.nan, 4.0, math.nan, math.nan]), arrow),
        ("Float64", pd.Series(pd.arrays.FloatingArray(values, mask)), arrow),
        (
            "double[pyarrow]",
            pd.Series(pd.arrays.ArrowExtensionArray(arrow)),
            arrow,
        ),
    ]


NAN_COLUMNS = _nan_columns()


def _sparse(array: pa.Array, labels: pd.Series) -> SparseLabels:
    positions = [
        i for i, v in enumerate(array.to_pylist()) if isinstance(v, float) and math.isnan(v)
    ]
    return SparseLabels(
        pa.array(positions, pa.int64()), pa.array(labels.iloc[positions].tolist(), pa.string())
    )


@pytest.mark.parametrize("fmt", ["lower", "range", "midpoint"])
@pytest.mark.parametrize("width", [10, 7, 2.5])
@pytest.mark.parametrize(("name", "column", "array"), NAN_COLUMNS, ids=[c[0] for c in NAN_COLUMNS])
def test_bucketize_sparse_nan_labels_reproduce_the_handler(
    name: str, column: pd.Series, array: pa.Array, width: int | float, fmt: str
) -> None:
    cells, bad = _bucketize_handler(column, width=width, format=fmt)
    settings = resolve_bucketize_settings({"width": width, "format": fmt}, "n")
    nan_rows = [
        i for i, v in enumerate(array.to_pylist()) if isinstance(v, float) and math.isnan(v)
    ]
    rendered = render_exceptional_bucket_labels(column.iloc[nan_rows], settings)
    sparse = SparseLabels(pa.array(nan_rows, pa.int64()), pa.array(_cells(rendered), pa.string()))
    result = bucketize_array(array, width, fmt, exceptional=sparse)
    assert result.labels.to_pylist() == cells, name
    assert bad == []


@pytest.mark.parametrize(("name", "column", "array"), NAN_COLUMNS, ids=[c[0] for c in NAN_COLUMNS])
def test_top_code_sparse_nan_labels_reproduce_the_handler(
    name: str, column: pd.Series, array: pa.Array
) -> None:
    cells, detail = _top_code_handler(column, cap=89, over_label="90+")
    settings = resolve_top_code_settings({"cap": 89, "over_label": "90+"}, "n")
    nan_rows = [
        i for i, v in enumerate(array.to_pylist()) if isinstance(v, float) and math.isnan(v)
    ]
    rendered = render_exceptional_top_code(column.iloc[nan_rows], settings)
    sparse = SparseLabels(pa.array(nan_rows, pa.int64()), pa.array(_cells(rendered), pa.string()))
    result = top_code_array(array, 89, "90+", exceptional=sparse)
    assert result.labels.to_pylist() == cells, name
    assert detail is None


def test_exceptional_renderers_literals() -> None:
    # Extension NaN prints "nan" under top_code; ordinary float64 NaN is missing.
    ext = pd.Series(pd.arrays.FloatingArray(np.array([math.nan]), np.array([False])))
    top = resolve_top_code_settings({"cap": 89, "over_label": "90+"}, "n")
    assert _cells(render_exceptional_top_code(ext, top)) == ["nan"]
    assert _cells(render_exceptional_top_code(pd.Series([math.nan]), top)) == [None]
    flt = resolve_bucketize_settings({"width": 2.5, "format": "range"}, "n")
    assert _cells(render_exceptional_bucket_labels(ext, flt)) == ["nan-nan"]
    assert _cells(render_exceptional_bucket_labels(pd.Series([math.nan]), flt)) == [None]


def test_reconstructed_arrow_int_column_prints_exact_integers() -> None:
    """A null-bearing int64[pyarrow] column renders like the kernel, with no ".0" and no loss."""
    values = [-1, None, 95, TWO53 - 3]
    cap = TWO53 - 1
    cells, detail = _top_code_handler(
        pd.Series(values, dtype="int64[pyarrow]"), cap=cap, over_label="over"
    )
    assert cells == ["-1", None, "95", str(TWO53 - 3)]
    assert detail is None
    assert top_code_array(pa.array(values, pa.int64()), cap, "over").labels.to_pylist() == cells


def test_floor_multiple_takes_integers_without_quoting_them() -> None:
    values = pa.array([9007199254740993, -3, None], pa.int64())
    try:
        out = floor_multiple(values, 2.5)
    except pa.ArrowInvalid as exc:
        assert "9007199254740993" not in str(exc)
        raise
    expected = np.floor(np.array([9007199254740993, -3], dtype=np.float64) / 2.5) * 2.5
    assert out.to_pylist() == [*expected.tolist(), None]


_SECRET = "https://user:hunter2@host.example/x"


@pytest.mark.parametrize(
    "cfg",
    [
        {"cap": _SECRET, "over_label": "o"},
        {"preset": _SECRET},
        {"cap": 5, "over_label": "o", "floor": _SECRET, "under_label": "u"},
        {"cap": 5, "over_label": "o", "floor": 1, "under_label": [_SECRET]},
    ],
)
def test_top_code_resolver_errors_omit_supplied_values(cfg: dict[str, Any]) -> None:
    with pytest.raises(StrategyError) as info:
        resolve_top_code_settings(cfg, "n")
    text = str(info.value)
    assert "hunter2" not in text and "host.example" not in text
    assert info.value.code == reasons.runtime.TOP_CODE_BOUNDS_UNRESOLVABLE
    assert "n" in text or "floor" in text or "under_label" in text
