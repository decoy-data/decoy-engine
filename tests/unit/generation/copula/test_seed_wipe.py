"""The owner's census exception (plan section 14): every copula frame drops the caller's seed after
use, and no frame or output keeps it.

A profiler hook sees each `decoy_engine.generation.copula` frame as it returns or unwinds, after
its own wipe has run and before Python frees its locals; that is the last moment a frame could
still hold the seed. Raised errors are also walked with the census frame walker, and the model and
the sampled frame are searched in every form a caller can keep or write.
"""

from __future__ import annotations

import json
import pickle
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import FrameType
from typing import Any

import pandas as pd
import pytest

from decoy_engine.generation.copula import fit_gaussian_copula, sample_gaussian_copula
from tests.fileaccess.census_support import leaks

from ._fixtures import numeric_frame, snapshot

CANARY = b"COPULA-SEED-CANARY-" + b"q" * 13
_NEEDLES = (CANARY, CANARY.hex().encode(), repr(CANARY)[2:-1].encode())
_PACKAGE = "decoy_engine.generation.copula"


def _holds_canary(value: object) -> bool:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return any(n in raw for n in _NEEDLES)
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return False  # the seed never becomes a cell; repr of a large frame proves nothing
    try:
        shown = repr(value).encode("latin1", "replace")
    except Exception:
        return False
    return any(n in shown for n in _NEEDLES)


@contextmanager
def _exits(seen: list[str] | None = None) -> Iterator[list[str]]:
    """Every copula frame exit whose locals still hold the canary, as `qualname local`; `seen`
    collects the name of every copula frame that exited."""
    found: list[str] = []
    seen = [] if seen is None else seen

    def hook(frame: FrameType, event: str, _arg: object) -> None:
        if event != "return" or not str(frame.f_globals.get("__name__", "")).startswith(_PACKAGE):
            return
        name = getattr(frame.f_code, "co_qualname", frame.f_code.co_name)
        seen.append(name)
        found.extend(f"{name} {k}" for k, v in frame.f_locals.items() if _holds_canary(v))

    previous = sys.getprofile()
    sys.setprofile(hook)
    try:
        yield found
    finally:
        sys.setprofile(previous)


_FRAME = numeric_frame(2, n=400)
_SNAPSHOT = snapshot(_FRAME)


def test_every_frame_drops_the_seed_before_it_returns() -> None:
    seen: list[str] = []
    with _exits(seen) as found:
        model = fit_gaussian_copula(_FRAME, _SNAPSHOT, seed=CANARY)
        sample_gaussian_copula(model, 50, seed=CANARY, start=7)
    # The hook saw every frame that binds the seed, so an empty list is a finding.
    assert {"fit_gaussian_copula", "sample_gaussian_copula", "check_seed"} <= set(seen)
    assert found == []


_REFUSALS: dict[str, Callable[[], object]] = {
    "fit, frame not a DataFrame": lambda: fit_gaussian_copula(
        "not a frame",  # type: ignore[arg-type]
        _SNAPSHOT,
        seed=CANARY,
    ),
    "fit, snapshot of another frame": lambda: fit_gaussian_copula(
        _FRAME, snapshot(numeric_frame(3, n=400)), seed=CANARY
    ),
    "sample, negative start": lambda: sample_gaussian_copula(
        fit_gaussian_copula(_FRAME, _SNAPSHOT, seed=CANARY), 5, seed=CANARY, start=-1
    ),
    "sample, model not a model": lambda: sample_gaussian_copula(
        object(),  # type: ignore[arg-type]
        5,
        seed=CANARY,
    ),
    "check, seed too short": lambda: fit_gaussian_copula(_FRAME, _SNAPSHOT, seed=CANARY[:15]),
}


@pytest.mark.parametrize("case", sorted(_REFUSALS))
def test_a_refused_call_leaves_no_frame_holding_the_seed(case: str) -> None:
    with _exits() as found:
        with pytest.raises((TypeError, ValueError)) as caught:
            _REFUSALS[case]()
    assert found == []
    canary = CANARY[:15] if "short" in case else CANARY
    assert leaks(caught.value, canary) == []


def _outputs() -> dict[str, Any]:
    model = fit_gaussian_copula(_FRAME, _SNAPSHOT, seed=CANARY)
    rows = sample_gaussian_copula(model, 50, seed=CANARY)
    return {"model": model, "rows": rows}


def test_no_output_keeps_the_seed() -> None:
    out = _outputs()
    model, rows = out["model"], out["rows"]
    forms: dict[str, bytes] = {
        "model repr": repr(model).encode(),
        "model dict": json.dumps(model.to_dict()).encode(),
        "model pickle": pickle.dumps(model),
        "model attributes": repr(vars(model)).encode(),
        "rows repr": repr(rows).encode(),
        "rows csv": rows.to_csv().encode(),
        "rows pickle": pickle.dumps(rows),
        "rows attrs": repr(rows.attrs).encode(),
    }
    assert [name for name, raw in forms.items() if any(n in raw for n in _NEEDLES)] == []
