"""O1 acceptance (AT-O1c, AT-O1d): `when_eval_frame` and the predicate evaluator against the
Python-integer reference, for every ingestion dtype a route can hand them.

Plan: `docs/plans/2026-11-18-freeze-batch.md` rev 3.2, sections 4.3 and 8.
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np
import pandas as pd
import pytest

from tests.unit.execution._o1_when_support import BIG, L, reference

_RNG = random.Random(20261118)
_INT_POOL = [
    0, 1, -1, 5, BIG - 1, BIG, BIG + 1, BIG + 2, -BIG, -BIG - 1, -BIG + 1,
    2**63 - 1, -(2**63), -(2**63) + 1, 2**62, 12345678901234567,
]  # fmt: skip
_FLOAT_POOL = [0.0, 5.5, float(BIG), float(BIG) + 2.0, float(2**62), -float(BIG), 1e300, -1e300]
_FORMS = [
    "v == {a}", "v != {a}", "v < {a}", "v <= {a}", "v > {a}", "v >= {a}",
    "v in [{a}, {b}]", "v not in [{a}, {b}]", "not (v == {a})", "not (v < {a})",
    "v == {a} and v != {b}", "v == {a} or v == {b}", "{a} < v",
]  # fmt: skip


def _eval(frame: pd.DataFrame, expression: str) -> list[bool]:
    from decoy_engine.execution._when_gate import _eval_predicate

    mask = _eval_predicate(frame, expression, "redact", column="m")
    return [bool(x) for x in mask.to_numpy(dtype=bool)]


def _frames(values: list[int | None]) -> list[tuple[str, pd.DataFrame]]:
    """The frames a route can build for one integer column: nullable dtype always, numpy int64 when
    there is no blank and every value fits, numpy uint64 likewise."""
    out = [("Int64", pd.DataFrame({"v": pd.array(values, dtype="Int64")}))]
    if all(x is not None and -(2**63) <= x < 2**63 for x in values):
        out.append(("int64", pd.DataFrame({"v": np.array(values, dtype=np.int64)})))
    if all(x is not None and 0 <= x < 2**64 for x in values):
        out.append(("uint64", pd.DataFrame({"v": np.array(values, dtype=np.uint64)})))
    return out


def _literal() -> str:
    return _RNG.choice(
        [*map(str, _INT_POOL), *map(repr, _FLOAT_POOL), str(_RNG.randint(-(2**63), 2**63 - 1))]
    )


def _case() -> tuple[list[int | None], str]:
    n = _RNG.randint(1, 8)
    values: list[int | None] = [
        None
        if _RNG.random() < 0.25
        else _RNG.choice([*_INT_POOL, _RNG.randint(-(2**63), 2**63 - 1)])
        for _ in range(n)
    ]
    return values, _RNG.choice(_FORMS).format(a=_literal(), b=_literal())


GENERATED = [_case() for _ in range(400)]


@pytest.mark.parametrize(("values", "expression"), GENERATED)
def test_generated_frames_equal_the_python_integer_reference(
    values: list[Any], expression: str
) -> None:
    for dtype, frame in _frames(values):
        assert _eval(frame, expression) == reference(expression, values), (
            dtype,
            values,
            expression,
        )


@pytest.mark.parametrize("dtype", ["Int64", "int64"])
@pytest.mark.parametrize(
    ("expression", "want"),
    [
        (f"v == {L}", False),
        (f"v != {L}", True),
        (f"v < {L}", True),
        (f"v >= {L}", False),
        (f"v == {float(BIG + 1)}", True),  # that float literal is 2**53 exactly
        (f"{L} == v", False),
    ],
)
def test_chunk_size_one_with_an_in_range_value_and_an_out_of_range_literal(
    dtype: str, expression: str, want: bool
) -> None:
    """The literal alone selects exact evaluation: the chunk holds only 2**53, which fits."""
    frame = dict(_frames([BIG]))[dtype]
    assert _eval(frame, expression) == [want]


def test_value_outside_the_float_range_with_a_small_literal() -> None:
    for dtype, frame in _frames([BIG + 1, BIG + 2, 5]):
        assert _eval(frame, f"v == {BIG + 2}") == [False, True, False], dtype
        assert _eval(frame, f"v > {BIG}") == [True, True, False], dtype


def test_int64_against_a_float_literal_is_exact_not_float64() -> None:
    frame = dict(_frames([BIG + 1, BIG]))["int64"]
    assert _eval(frame, f"v == {float(BIG)}") == [False, True]


def test_when_eval_frame_holds_python_ints_and_nan_never_pd_na() -> None:
    from decoy_engine.execution._when_gate import when_eval_frame

    frame = pd.DataFrame(
        {"v": pd.array([BIG + 1, None], dtype="Int64"), "s": ["a", None], "other": [1, 2]}
    )
    got = when_eval_frame(frame, ("v", "s"), {"v": (L,), "s": ("a",)})
    assert list(got.columns) == ["v", "s"]
    assert got.index.equals(frame.index)
    assert got["v"].dtype == object
    assert got["v"].iloc[0] == BIG + 1 and isinstance(got["v"].iloc[0], int)
    assert got["v"].iloc[1] is not pd.NA and got["v"].isna().tolist() == [False, True]
    small = when_eval_frame(frame, ("v",), {"v": (5,)})
    assert small["v"].dtype == object  # the value is out of range, whatever the literal


def test_in_range_nullable_integer_with_in_range_literals_becomes_float_with_nan() -> None:
    from decoy_engine.execution._when_gate import when_eval_frame

    frame = pd.DataFrame({"v": pd.array([1, None], dtype="Int64")})
    got = when_eval_frame(frame, ("v",), {"v": (5,)})
    assert got["v"].dtype == np.float64
    assert np.isnan(got["v"].iloc[1])


# AT-O1d: an FK integer key read by `when:` stays exact (the DE-10 contract), on every resident route.
@pytest.mark.parametrize("route", ["full_frame", "sequential"])
def test_fk_key_read_by_when_stays_exact(tmp_path: Any, route: str) -> None:
    from decoy_engine.execution._pipeline import run_pipeline
    from tests.native._chunked_entry_support import key_provider
    from tests.unit.execution._o1_when_support import M_SOURCE, VALUES, build_case, selected_rows

    cfg, tables = build_case("fk", tmp_path, f"v == {L}")
    out = run_pipeline(
        cfg,
        tables,
        engine_version="o1",
        key_provider=key_provider(),
        execution_mode=route,
        auto_chunk=False,
        unified_slice_enabled=False,
    )
    assert out.quality_metrics["execution"]["execution_mode"] == route
    assert selected_rows(out.outputs["t"], M_SOURCE) == reference(f"v == {L}", VALUES)


@pytest.mark.parametrize("values", [[BIG, None], [BIG - 1, None, 5], [None]])
@pytest.mark.parametrize(
    "expression",
    [
        f"v == {L}",
        f"v != {L}",
        f"v < {L}",
        f"v >= {L}",
        f"v in [{L}]",
        f"v not in [{L}]",
        f"not (v == {L})",
        f"v == {float(BIG + 1)}",
        f"v > {float(BIG - 1)}",
    ],
)
def test_blank_bearing_chunk_of_in_range_values_with_an_out_of_range_literal(
    values: list[Any], expression: str
) -> None:
    """The literal alone forces exact evaluation: float64 would round the literal to 2**53."""
    frame = dict(_frames(values))["Int64"]
    assert _eval(frame, expression) == reference(expression, values)


def test_python_engine_error_is_value_free_and_has_no_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The exact-integer path evaluates with pandas' Python engine. Its failure carries no
    expression, no literal and no chained cause, as the numexpr path does."""
    import logging

    from decoy_engine.execution._errors import StrategyError

    frame = pd.DataFrame({"v": pd.array([BIG + 1, None], dtype="Int64")})
    # The wide literal selects the object path; a string literal against it cannot compare.
    expression = f"v == {L} and v == 'secret-literal-123'"
    with caplog.at_level(logging.DEBUG, logger="decoy_engine.execution._when_gate"):
        with pytest.raises(StrategyError) as info:
            _eval(frame, expression)
    assert info.value.code == "when_expression_error"
    assert info.value.__cause__ is None and info.value.__context__ is None
    assert "secret-literal-123" not in str(info.value)
    assert str(L) not in str(info.value)
    assert all(
        "secret-literal-123" not in r.getMessage() and str(L) not in r.getMessage()
        for r in caplog.records
    )


def test_duplicate_column_labels_hand_the_frame_back_unchanged() -> None:
    from decoy_engine.execution._when_gate import when_eval_frame

    frame = pd.DataFrame([[1, 2]], columns=["v", "v"])
    assert when_eval_frame(frame, ("v",), {"v": (1,)}) is frame
