"""AT-A2: a reference table that cannot load refuses the run instead of blanking every state.

Fail-before: `_build_state_map` caught the load failure, warned and returned `{}`, so every state
value was `""` and the cascade suppressed rows the table would have kept. The lazy-load cell
pins that a cascade without `state` never reads the zip5 table.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import pytest

from decoy_engine import reasons
from decoy_engine.errors import DecoyError
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.reference_tables import load_table as real_load_table
from decoy_engine.transforms import geo_generalize

_ZIP5 = "us_zip5_city_state"
_MARKER = "CANARY-PATH-5E1F"


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"zip": ["90210", "10001", "60601"]})


def _loader(calls: list[str], *, fail: BaseException | None) -> Any:
    def load(name: str, *args: Any, **kwargs: Any) -> Any:
        calls.append(name)
        if name == _ZIP5 and fail is not None:
            raise fail
        return real_load_table(name, *args, **kwargs)

    return load


@pytest.mark.parametrize(
    "failure",
    [FileNotFoundError(_MARKER), ValueError(_MARKER), PermissionError(_MARKER)],
    ids=lambda e: type(e).__name__,
)
def test_a_failed_zip5_load_raises_a_coded_execution_error(
    failure: BaseException, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(geo_generalize, "load_table", _loader([], fail=failure))
    cfg = geo_generalize.GeoGeneralizeConfig(type="zip", cascade=["zip5", "state", "suppress"])
    with caplog.at_level(logging.DEBUG), pytest.raises(ExecutionError) as err:
        geo_generalize.cascade_zip_column(_frame(), "zip", cfg)
    exc = err.value
    assert exc.code == str(reasons.runtime.REFERENCE_TABLE_UNAVAILABLE)
    assert exc.code == "reference_table_unavailable"
    assert reasons.find("runtime", exc.code) is not None
    assert _ZIP5 in str(exc)
    assert _MARKER not in str(exc) and _MARKER not in repr(exc.args)
    assert exc.__cause__ is None and exc.__context__ is None
    assert isinstance(exc, DecoyError)
    assert _MARKER not in caplog.text


def test_a_cascade_without_state_never_loads_the_zip5_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(geo_generalize, "load_table", _loader(calls, fail=FileNotFoundError()))
    cfg = geo_generalize.GeoGeneralizeConfig(type="zip", cascade=["zip5", "zip3", "suppress"])
    out, _evidence = geo_generalize.cascade_zip_column(_frame(), "zip", cfg)
    assert _ZIP5 not in calls
    assert len(out) == 3


def test_a_cascade_with_state_loads_the_table_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(geo_generalize, "load_table", _loader(calls, fail=None))
    cfg = geo_generalize.GeoGeneralizeConfig(type="zip", cascade=["zip5", "state", "suppress"])
    geo_generalize.cascade_zip_column(_frame(), "zip", cfg)
    assert calls.count(_ZIP5) == 1
