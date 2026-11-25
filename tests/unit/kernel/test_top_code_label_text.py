"""A top_code label that cannot encode as UTF-8 is refused at every entry, value-free.

A lone surrogate is valid Python text but has no UTF-8 form. Arrow fails on it when it builds the
label scalar, and the failure carries the whole label in its args. One predicate
(``contracts.label_text.is_utf8_text``) now gates the public strategy, the plan check and the
exported kernel, each failing with the existing top_code bounds code and no submitted text.
"""

from __future__ import annotations

import logging
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine import reasons
from decoy_engine.execution._errors import ExecutionError, StrategyError
from decoy_engine.execution._strategies import resolve_top_code_settings
from decoy_engine.kernel import top_code_array
from decoy_engine.plan._checks_top_code import check_top_code_config
from decoy_engine.plan._errors import PlanCompileError

CANARY = "CANARY\ud800secret"
BAD_FRAGMENTS = ("CANARY", "secret", "\ud800", "ud800")

OVER = {"cap": 89, "over_label": CANARY}
UNDER = {"cap": 89, "over_label": "90+", "floor": 40, "under_label": CANARY}
BAD_CFGS = [pytest.param(OVER, id="over_label"), pytest.param(UNDER, id="under_label")]


def _exception_text(exc: BaseException) -> str:
    parts = [str(exc), repr(exc), repr(exc.args)]
    link = exc.__cause__ or exc.__context__
    while link is not None:
        parts += [str(link), repr(link.args)]
        link = link.__cause__ or link.__context__
    return " ".join(parts)


def _assert_value_free(exc: BaseException, caplog: pytest.LogCaptureFixture) -> None:
    text = _exception_text(exc) + " " + caplog.text
    for fragment in BAD_FRAGMENTS:
        assert fragment not in text, fragment
    assert exc.__cause__ is None and exc.__context__ is None


@pytest.mark.parametrize("cfg", BAD_CFGS)
def test_strategy_resolver_refuses_unencodable_label(
    cfg: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG), pytest.raises(StrategyError) as raised:
        resolve_top_code_settings(cfg, "age")
    assert raised.value.code == reasons.runtime.TOP_CODE_BOUNDS_UNRESOLVABLE
    _assert_value_free(raised.value, caplog)


@pytest.mark.parametrize("cfg", BAD_CFGS)
def test_plan_check_refuses_unencodable_label(
    cfg: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    column = {"name": "age", "strategy": "top_code", "provider_config": cfg}
    config = {"tables": [{"name": "t", "columns": [column]}]}
    with caplog.at_level(logging.DEBUG), pytest.raises(PlanCompileError) as raised:
        check_top_code_config(config)
    assert raised.value.code in (
        reasons.plan.TOP_CODE_MISSING_OVER_LABEL,
        reasons.plan.TOP_CODE_MISSING_UNDER_LABEL,
    )
    _assert_value_free(raised.value, caplog)
    assert CANARY not in (raised.value.path or "")


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"over_label": CANARY}, id="over_label"),
        pytest.param({"over_label": "90+", "floor": 40, "under_label": CANARY}, id="under_label"),
    ],
)
def test_kernel_refuses_unencodable_label_even_when_no_row_uses_it(
    kwargs: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG), pytest.raises(ExecutionError) as raised:
        top_code_array(pa.array([42], pa.int64()), 89, **kwargs)
    assert raised.value.code == reasons.runtime.TOP_CODE_BOUNDS_UNRESOLVABLE
    _assert_value_free(raised.value, caplog)


def test_encodable_non_ascii_labels_still_work() -> None:
    out = top_code_array(pa.array([42, 95], pa.int64()), 89, "é≥ 90", 50, "<ü")
    assert out.labels.to_pylist() == ["<ü", "é≥ 90"]
