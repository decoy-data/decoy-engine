"""Byte parity of the batched `apply_windowed_date` against the per-row base loop.

The oracle and the corpus live in `_windowed_date_corpus.py`. The digest below was recorded from
origin/main 75fba3d855d71e3980a62afc3ce7f1187b72073d before any fast-path code existed. A failure in
this file is a stop, never an edit to the digest or the corpus.
"""

from __future__ import annotations

import datetime as dt
import warnings
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from decoy_engine.determinism._derive import DeriveContext, derive
from decoy_engine.generation._column_streams import WindowedDateStream
from decoy_engine.generation.pool._sampler import _derive_pool_indices
from decoy_engine.generators.derivation import with_table
from decoy_engine.transforms import windowed_date as wd
from decoy_engine.transforms.windowed_date import WindowedDateConfig, apply_windowed_date
from tests.unit.generation._windowed_date_corpus import (
    SEED8,
    SEED32,
    MyDate,
    build_cases,
    corpus_digest,
    outcome,
    reference_apply_windowed_date,
)

BASE_DIGEST = "efd24e5746f20b24f5ced9a4656a2d4125f363e05742b641d60c4091fdae6d7b"

CASES = build_cases()
CASE_IDS = [c.name for c in CASES]


# --- Step 0: the premise, on base -------------------------------------------------------------


def _row_corpus() -> list[int]:
    return [*range(5000), 2**31, 2**32 - 1, 2**40 + 7, 2**63 - 1]


@pytest.mark.parametrize("seed", [SEED8, SEED32], ids=["seed8", "seed32"])
def test_batched_derive_matches_per_row(seed: bytes) -> None:
    ns = "windowed_date/ev"
    rows = [*_row_corpus(), 9, 5, 2**33 + 1, 12]  # non-contiguous tail
    ctx = DeriveContext.for_column(seed, ns)
    batched = list(ctx.derive_sources(ns, (r.to_bytes(8, "big") for r in rows)))
    assert batched == [derive(seed, ns, r.to_bytes(8, "big")) for r in rows]


def test_pool_index_batch_is_not_byte_identical() -> None:
    """Records that the pool index kernel cannot stand in for the per-row draw (S2 deletes it)."""
    ns = "windowed_date/ev"
    rows = _row_corpus()
    span = 120
    pool = _derive_pool_indices(
        pd.Series(rows, dtype="int64"), seed=SEED8, namespace=ns, pool_size=span + 1
    )
    per_row = [
        wd._sample_offset(
            np.random.default_rng(
                int.from_bytes(derive(SEED8, ns, r.to_bytes(8, "big"))[:8], "big")
            ),
            0,
            span,
            "uniform",
        )
        for r in rows
    ]
    assert [int(x) for x in pool] != per_row


def test_output_digest_pinned() -> None:
    assert corpus_digest(apply_windowed_date) == BASE_DIGEST


# --- The corpus against the oracle ------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_fast_path_equals_reference_on_corpus(case: Any) -> None:
    got = outcome(apply_windowed_date, case)
    want = outcome(reference_apply_windowed_date, case)
    assert got == want
    if case.expect_error is not None:
        assert (want[0] == "err") == case.expect_error


def test_error_parity() -> None:
    n_err = 0
    for case in CASES:
        want = outcome(reference_apply_windowed_date, case)
        if want[0] != "err":
            continue
        n_err += 1
        got = outcome(apply_windowed_date, case)
        assert got[:3] == want[:3], case.name
        # The error is raised outside any except block: no cause, no context (value-free).
        assert got[3] is True and want[3] is True, case.name
    assert n_err >= 40


class _SpyParse:
    def __init__(self, real: Callable[..., Any]) -> None:
        self.real = real
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        return self.real(*args, **kwargs)


@pytest.mark.parametrize("case", [c for c in CASES if c.admitted], ids=lambda c: c.name)
def test_fast_path_is_taken(case: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _SpyParse(wd._parse_anchor)
    monkeypatch.setattr(wd, "_parse_anchor", spy)
    outcome(apply_windowed_date, case)
    assert spy.calls == 0


@pytest.mark.parametrize(
    "name", ["date_subclass", "mixed_str_and_date", "mixed_date_and_datetime", "err_empty_string"]
)
def test_reference_path_is_taken_for_unadmitted(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    case = next(c for c in CASES if c.name == name)
    spy = _SpyParse(wd._parse_anchor)
    monkeypatch.setattr(wd, "_parse_anchor", spy)
    outcome(apply_windowed_date, case)
    assert spy.calls > 0


def test_date_subclass_cells_are_reference_pathed() -> None:
    assert type(MyDate(2000, 1, 1)) is not dt.date  # guards the corpus premise


def test_batch_boundaries_do_not_change_output() -> None:
    rng = np.random.default_rng(5)
    base = np.datetime64("1980-01-01")
    n = 70_000
    anchors: list[Any] = [str(base + int(d)) for d in rng.integers(0, 15_000, size=n)]
    for k in range(0, n, 97):
        anchors[k] = None
    col = {"anchor": "dob", "min_days": 1, "max_days": 40, "distribution": "early"}
    seed = int.from_bytes(SEED8, "big")

    def run(size: int, limit: int) -> list[Any]:
        stream = WindowedDateStream(with_table({**col, "name": "ev"}, "t"), seed=seed)
        out: list[Any] = []
        for start in range(0, limit, size):
            stop = min(start + size, limit)
            out.extend(stream.next_batch_from(start, stop - start, {"dob": anchors[start:stop]}))
        return out

    full = run(65_536, n)
    assert run(32_768, n) == full
    assert run(1, 400) == full[:400]
    assert run(7, 400) == full[:400]
    assert sum(v is None for v in full) > 0


# --- Property test ----------------------------------------------------------------------------

_ISO_POOL: st.SearchStrategy[Any] = st.one_of(
    st.dates(min_value=dt.date(1650, 1, 1), max_value=dt.date(2250, 12, 31)).map(str),
    st.datetimes(min_value=dt.datetime(1650, 1, 1), max_value=dt.datetime(2250, 12, 31)).map(
        lambda d: d.isoformat(sep="T")
    ),
    st.sampled_from(
        [
            "2024-02-30",
            "2000/01/01",
            "",
            "NaT",
            "2000-01-01Z",
            "2000-01-01T24:00",
            "2000-01-01T23:59:60",
            "2000-01-01 07:08",
            "2000-01-01T07:08:09.123456789",
            "1969-12-31T23:59:59.5",
        ]
    ),
)
_CELL = st.one_of(
    _ISO_POOL,
    st.just(None),
    st.just(pd.NaT),
    st.just(float("nan")),
    st.integers(0, 3),
)


@st.composite
def _batches(draw: st.DrawFn) -> dict[str, Any]:
    shape = draw(st.sampled_from(["str", "str_typed_noise", "date", "datetime", "timestamp"]))
    n = draw(st.integers(0, 12))
    if shape == "str":
        cells = draw(st.lists(st.one_of(_ISO_POOL, st.none()), min_size=n, max_size=n))
    elif shape == "str_typed_noise":
        cells = draw(st.lists(_CELL, min_size=n, max_size=n))
    elif shape == "date":
        cells = draw(
            st.lists(
                st.one_of(
                    st.dates(min_value=dt.date(1600, 1, 1), max_value=dt.date(2300, 1, 1)),
                    st.none(),
                ),
                min_size=n,
                max_size=n,
            )
        )
    elif shape == "datetime":
        cells = draw(
            st.lists(
                st.one_of(
                    st.datetimes(
                        min_value=dt.datetime(1600, 1, 1), max_value=dt.datetime(2300, 1, 1)
                    ),
                    st.none(),
                ),
                min_size=n,
                max_size=n,
            )
        )
    else:
        cells = [
            None if c is None else pd.Timestamp(c)
            for c in draw(
                st.lists(
                    st.one_of(
                        st.datetimes(
                            min_value=dt.datetime(1650, 1, 1), max_value=dt.datetime(2250, 1, 1)
                        ),
                        st.none(),
                    ),
                    min_size=n,
                    max_size=n,
                )
            )
        ]
    lo = draw(st.integers(-500, 500))
    hi = draw(st.integers(lo, lo + draw(st.sampled_from([0, 3, 400, 150_000]))))
    use_pos = draw(st.booleans())
    pos = None
    if use_pos:
        pos = draw(st.lists(st.integers(-2, 2**40), min_size=n, max_size=n))
    return {
        "cells": cells,
        "lo": lo,
        "hi": hi,
        "dist": draw(st.sampled_from(["uniform", "early", "late"])),
        "offset": draw(st.sampled_from([0, 65_536, 2**32])),
        "pos": pos,
        "seed": draw(st.sampled_from([SEED8, SEED32])),
    }


def _run(fn: Callable[..., Any], b: dict[str, Any]) -> tuple[Any, ...]:
    cfg = WindowedDateConfig(anchor="a", min_days=b["lo"], max_days=b["hi"], distribution=b["dist"])
    df = pd.DataFrame({"a": pd.Series(b["cells"], dtype=object)})
    try:
        return (
            "ok",
            fn(cfg, df, b["seed"], "windowed_date/p", row_offset=b["offset"], positions=b["pos"]),
        )
    except Exception as exc:
        return (
            "err",
            type(exc).__name__,
            str(exc),
            exc.__cause__ is None and exc.__context__ is None,
        )


@settings(
    max_examples=400,
    derandomize=True,
    database=None,
    deadline=None,
    suppress_health_check=list(HealthCheck),
)
@given(_batches())
def test_fast_path_equals_reference_property(b: dict[str, Any]) -> None:
    assert _run(apply_windowed_date, b) == _run(reference_apply_windowed_date, b)


# --- Warnings and interrupts ------------------------------------------------------------------


def test_fast_path_emits_no_warning() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for case in CASES:
            if not case.expect_error:
                outcome(apply_windowed_date, case)
    assert [str(w.message) for w in caught] == []


def test_interrupt_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    case = next(c for c in CASES if c.name == "main_uniform")
    spy = _SpyParse(wd._parse_anchor)
    monkeypatch.setattr(wd, "_parse_anchor", spy)

    def boom(*_a: Any, **_k: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(wd, "_vector_parse", boom)
    with pytest.raises(KeyboardInterrupt):
        outcome(apply_windowed_date, case)
    assert spy.calls == 0
