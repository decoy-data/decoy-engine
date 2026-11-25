"""S1a (BUCKET-TOPCODE-NATIVE): the bucketize handler's range exits (B2, B3) and B4.

Independent literals throughout: no expectation is computed by the code under test.
B2: an integer width and a finite value of magnitude 2**53 or more is a row error and a null cell.
B3: an integer width and an infinity is the same. B4: a float width on an integer source of any
pandas dtype is converted to float64 first, so no dtype raises or quotes a value.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.contracts import bucketize_width
from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.contracts.format_error_reasons import format_error_reason
from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._row_errors import drain_row_errors
from decoy_engine.execution._strategies import _top_code
from decoy_engine.execution._strategies._bucketize import BucketizeStrategyHandler
from decoy_engine.plan import _checks_top_code
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.quarantine import compute_quarantine

RANGE_REASON = "value is out of range under bucketize"
NOT_NUMERIC = "value is not numeric under bucketize"
INF = float("inf")
TWO53 = 9007199254740992


def _seed(**pc: Any) -> ColumnSeed:
    return ColumnSeed(
        namespace=None,
        strategy="bucketize",
        provider="bucketize",
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


def _run(frame: pd.DataFrame, **pc: Any) -> tuple[pd.DataFrame, list[tuple[int, str]]]:
    ctx = _ctx()
    out, warnings = BucketizeStrategyHandler().run(frame.copy(), "n", _seed(**pc), ctx)
    assert warnings == []
    assert all(e.column == "n" and e.trigger == "format_error" for e in ctx.row_errors)
    return out, [(e.row_index, e.reason) for e in ctx.row_errors]


def _cells(series: pd.Series) -> list[Any]:
    return [None if pd.isna(v) else v for v in series.tolist()]


# value, lower, range, midpoint at width 10; None is a null output cell.
FLOAT_SOURCE = [
    (15.0, "10", "10-19", "15"),
    (float(TWO53), None, None, None),
    (25.0, "20", "20-29", "25"),
    (INF, None, None, None),
    (float("nan"), "NAN", "NAN", "NAN"),  # ordinary missing: unchanged, no record
    (1e19, None, None, None),
    (-INF, None, None, None),
    (-float(TWO53), None, None, None),
    (35.0, "30", "30-39", "35"),
]
BAD_POSITIONS = [1, 3, 5, 6, 7]


@pytest.mark.parametrize(("fmt", "col"), [("lower", 1), ("range", 2), ("midpoint", 3)])
def test_float_source_integer_width_exits(fmt: str, col: int) -> None:
    frame = pd.DataFrame({"n": [row[0] for row in FLOAT_SOURCE]})
    out, errors = _run(frame, width=10, format=fmt)
    want = [row[col] for row in FLOAT_SOURCE]
    got = _cells(out["n"])
    for position, (g, w) in enumerate(zip(got, want, strict=True)):
        if w == "NAN":
            assert g is None, position  # the original NaN is kept as missing
        else:
            assert g == w, position
    assert errors == [(i, RANGE_REASON) for i in BAD_POSITIONS]


def test_just_inside_the_bound_still_labels() -> None:
    frame = pd.DataFrame({"n": [9007199254740991.0, -9007199254740991.0]})
    lower, errors = _run(frame, width=10, format="lower")
    assert errors == []
    assert lower["n"].tolist() == ["9007199254740990", "-9007199254741000"]
    ranged, errors = _run(frame, width=10, format="range")
    assert errors == []
    assert ranged["n"].tolist() == [
        "9007199254740990-9007199254740999",
        "-9007199254741000--9007199254740991",
    ]


@pytest.mark.parametrize("kind", ["int64", "Int64", "int64[pyarrow]"])
def test_integer_source_exits_at_two_to_the_53(kind: str) -> None:
    values: list[Any] = [15, TWO53, TWO53 + 1, 25, -TWO53, 2**62 + 7]
    frame = pd.DataFrame({"n": pd.Series(values, dtype=kind)})
    out, errors = _run(frame, width=10, format="lower")
    assert _cells(out["n"]) == ["10", None, None, "20", None, None]
    assert errors == [(1, RANGE_REASON), (2, RANGE_REASON), (4, RANGE_REASON), (5, RANGE_REASON)]


def test_nullable_integer_null_is_not_an_error() -> None:
    frame = pd.DataFrame({"n": pd.Series([15, None, TWO53], dtype="Int64")})
    out, errors = _run(frame, width=10, format="range")
    assert _cells(out["n"]) == ["10-19", None, None]
    assert errors == [(2, RANGE_REASON)]


def test_uint32_max_and_int64_min_boundaries() -> None:
    frame = pd.DataFrame({"n": pd.Series([4294967295], dtype="uint32")})
    out, errors = _run(frame, width=10, format="lower")
    assert (out["n"].tolist(), errors) == (["4294967290"], [])
    frame = pd.DataFrame({"n": pd.Series([-(2**63)], dtype="int64")})
    out, errors = _run(frame, width=10, format="lower")
    assert (_cells(out["n"]), errors) == ([None], [(0, RANGE_REASON)])


def test_d7_and_range_records_are_disjoint_and_ordered() -> None:
    col = pd.Series(["15", "9007199254740992", "oops", "1e19", "25", None, "abc"], dtype=object)
    out, errors = _run(pd.DataFrame({"n": col}), width=10, format="lower")
    assert errors == [
        (1, RANGE_REASON),
        (2, NOT_NUMERIC),
        (3, RANGE_REASON),
        (6, NOT_NUMERIC),
    ]
    # D7 keeps the original text; the range cells are null; valid rows keep their labels.
    assert _cells(out["n"]) == ["10", None, "oops", None, "20", None, "abc"]


def test_quarantine_counts_each_bad_cell_once() -> None:
    frame = pd.DataFrame({"n": [15.0, 1e19, INF, float("nan"), 25.0, float(TWO53)]})
    ctx = _ctx()
    out, _ = BucketizeStrategyHandler().run(frame, "n", _seed(width=10, format="lower"), ctx)
    records = drain_row_errors(ctx.row_errors, table="t")
    assert [(r.row_index, r.trigger, r.reason) for r in records] == [
        (1, "format_error", RANGE_REASON),
        (2, "format_error", RANGE_REASON),
        (5, "format_error", RANGE_REASON),
    ]
    arrow = pa.Table.from_pandas(out, preserve_index=False)
    kept, entries, counts, total = compute_quarantine(
        {"t": arrow}, None, {"triggers": ["format_error"]}, row_errors=records
    )
    assert counts == {"format_error": 3}
    assert total == 3
    assert kept["t"].column("n").to_pylist() == ["10", None, "20"]
    # The quarantine file carries the masked row: the bad numeric cell is null, never retained.
    assert [e["n"] for e in entries] == [None, None, None]
    assert [e["_quarantine_reason"] for e in entries] == [RANGE_REASON] * 3


def test_declared_integer_lower_stays_nullable_integer() -> None:
    frame = pd.DataFrame({"n": [15.0, 1e19, 25.0, INF]})
    out, errors = _run(frame, width=10, format="lower", declared_integer_output=True)
    assert errors == [(1, RANGE_REASON), (3, RANGE_REASON)]
    arrow = pa.Array.from_pandas(out["n"])
    assert arrow.type == pa.int64()
    assert arrow.to_pylist() == [10, None, 20, None]


def test_float_width_never_exits() -> None:
    frame = pd.DataFrame({"n": [INF, -INF, 1e19]})
    out, errors = _run(frame, width=2.5, format="lower")
    assert errors == []
    assert out["n"].tolist() == ["inf", "-inf", "1e+19"]


def test_handler_does_not_mutate_a_nonbad_dtype() -> None:
    frame = pd.DataFrame({"n": np.array([15, 25], dtype="float32")})
    out, errors = _run(frame, width=10, format="midpoint")
    assert (out["n"].tolist(), errors) == (["15", "25"], [])


# -- B4: float width on an integer source -------------------------------------------------------

BIG = 9007199254740993


def _pyarrow_int_frame(values: list[int]) -> pd.DataFrame:
    table = pa.Table.from_pandas(pd.DataFrame({"n": np.array(values, dtype="int64")}))
    return table.to_pandas(types_mapper=pd.ArrowDtype)


B4_LABELS = {
    "lower": "9007199254740992.0",
    "range": "9007199254740992.0-9007199254740994.0",
    "midpoint": "9007199254740994.0",
}


@pytest.mark.parametrize("fmt", ["lower", "range", "midpoint"])
@pytest.mark.parametrize("kind", ["numpy", "masked", "arrow"])
def test_b4_float_width_over_large_integer(kind: str, fmt: str) -> None:
    if kind == "numpy":
        frame = pd.DataFrame({"n": np.array([BIG], dtype="int64")})
        nulls: list[int] = []
    elif kind == "masked":
        frame = pd.DataFrame({"n": pd.Series([BIG, None], dtype="Int64")})
        nulls = [1]
    else:
        frame = _pyarrow_int_frame([BIG])
        assert str(frame["n"].dtype) == "int64[pyarrow]"
        nulls = []
    out, errors = _run(frame, width=2.5, format=fmt)
    assert errors == []
    cells = _cells(out["n"])
    assert cells[0] == B4_LABELS[fmt]
    for i in nulls:
        assert cells[i] is None


@pytest.mark.parametrize(
    ("fmt", "label"), [("lower", "20.0"), ("range", "20.0-22.5"), ("midpoint", "21.25")]
)
@pytest.mark.parametrize("kind", ["numpy", "masked", "arrow"])
def test_b4_small_integers_unchanged(kind: str, fmt: str, label: str) -> None:
    frame = pd.DataFrame({"n": np.array([20], dtype="int64")})
    if kind == "masked":
        frame = pd.DataFrame({"n": pd.Series([20], dtype="Int64")})
    elif kind == "arrow":
        frame = _pyarrow_int_frame([20])
    out, errors = _run(frame, width=2.5, format=fmt)
    assert (out["n"].tolist(), errors) == ([label], [])


# -- the leaf reason and the shared bound -------------------------------------------------------


def test_reason_leaf_literal_and_unknown_strategy() -> None:
    assert format_error_reason("bucketize") == RANGE_REASON
    with pytest.raises(LookupError):
        format_error_reason("not_a_strategy")


def test_range_reason_text_has_one_production_owner() -> None:
    src = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"
    owners = []
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(n, ast.Constant) and n.value == RANGE_REASON for n in ast.walk(tree)):
            owners.append(path.relative_to(src).as_posix())
    assert owners == ["contracts/format_error_reasons.py"]


def test_exact_int_bound_is_one_constant() -> None:
    assert bucketize_width.EXACT_INT_BOUND == 2**53
    assert _top_code._MAX_EXACT_INT == bucketize_width.EXACT_INT_BOUND
    assert _checks_top_code.EXACT_INT_BOUND is bucketize_width.EXACT_INT_BOUND
    src = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"
    sharing = (
        "execution/_strategies/_bucketize.py",
        "execution/_strategies/_top_code.py",
        "plan/_checks_top_code.py",
        "kernel/_bucket.py",
        "contracts/bucketize_width.py",
    )
    definers = []
    for rel in sharing:
        path = src / rel
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Pow)
                and isinstance(node.left, ast.Constant)
                and node.left.value == 2
                and isinstance(node.right, ast.Constant)
                and node.right.value == 53
            ):
                definers.append(rel)
    assert definers == ["contracts/bucketize_width.py"]
