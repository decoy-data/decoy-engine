"""E-F0: every text_mask route raises the same `StrategyError` for an unsupported pair.

The handler (full frame), the native chunked kernel and the out-of-core Python kernel each catch
the tagged `PipelineValidationError` from `mask_cell`. They must surface one value-free
`StrategyError(unsupported_strategy)` with no cause or context, so a consumer keying on the code
sees the same event whichever route ran.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.execution._errors import StrategyError, text_mask_unsupported_pair_error
from decoy_engine.execution._strategies._text_mask import TextMaskHandler
from decoy_engine.execution.native._kernels_scalar import native_text_mask
from decoy_engine.execution.out_of_core._mask_group_c import _text_mask_array
from decoy_engine.plan._types import ColumnSeed

_KEY = b"\xab" * 32
_COLUMN = "cell"
_CELL = "ssn 123-45-6789 here"
_PAIR = {"ssn": "date_shift"}


class _Ctx:
    mask_key = _KEY


def _seed() -> ColumnSeed:
    return ColumnSeed(
        namespace=None,
        strategy="text_mask",
        provider=None,
        backend_type="decoy_native",
        backend_version="1",
        cardinality_mode="bijective",
        deterministic=False,
        provider_config=(
            ("detectors", ("ssn",)),
            ("per_detector_strategy", (("ssn", "date_shift"),)),
        ),
    )


def _handler() -> StrategyError:
    with pytest.raises(StrategyError) as exc:
        TextMaskHandler().run(pd.DataFrame({_COLUMN: [_CELL]}), _COLUMN, _seed(), _Ctx())
    return exc.value


def _native_chunked() -> StrategyError:
    with pytest.raises(StrategyError) as exc:
        native_text_mask(
            pa.array([_CELL], pa.string()),
            mask_key=_KEY,
            column=_COLUMN,
            detectors=("ssn",),
            per_detector_strategy=_PAIR,
            unmatched_span_policy="redact",
            token="[R]",
            date_shift_bounds=(),
            sub_floor_span_policy=None,
        )
    return exc.value


def _out_of_core() -> StrategyError:
    cfg = {"detectors": ["ssn"], "per_detector_strategy": dict(_PAIR)}
    with pytest.raises(StrategyError) as exc:
        _text_mask_array(
            pa.array([_CELL], pa.string()), _seed(), job_seed=_KEY, cfg=cfg, column=_COLUMN
        )
    return exc.value


ROUTES: dict[str, Callable[[], StrategyError]] = {
    "handler": _handler,
    "native_chunked": _native_chunked,
    "out_of_core": _out_of_core,
}


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_route_raises_the_shared_strategy_error(route: str) -> None:
    err = ROUTES[route]()
    expected = text_mask_unsupported_pair_error(_COLUMN)
    assert err.code == expected.code == "unsupported_strategy"
    assert err.strategy == "text_mask"
    assert str(err) == str(expected)
    assert "123-45-6789" not in str(err)
    assert err.__cause__ is None and err.__context__ is None
