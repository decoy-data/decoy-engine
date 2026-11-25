"""GEN-STREAM-ALL S1a: one sibling-read rule for admission, window admission and the batch.

`stream.sibling_input` names the earlier column a column reads. The test swaps the rule and checks
that all three readers follow it; a site that still reads `col["anchor"]` itself would not.
"""

from __future__ import annotations

from typing import Any

import pytest

from decoy_engine.generation import stream as gen_stream
from decoy_engine.generation._admission import classify_plan
from decoy_engine.generation._window_admission import classify_window_table
from decoy_engine.generation.stream import _batches
from tests.parity import _f0_fixtures as fx
from tests.parity._fr0_support import prepared_config

_DOB: dict[str, Any] = {"name": "dob", "type": "faker", "faker_type": "date_of_birth"}
_EV: dict[str, Any] = {
    "name": "ev",
    "type": "windowed_date",
    "anchor": "dob",
    "min_days": 1,
    "max_days": 30,
}


def _config() -> dict[str, Any]:
    return prepared_config(fx.config([fx.table("t", 500, [dict(_DOB), dict(_EV)])]))


def _readers(
    config: dict[str, Any],
) -> tuple[str | None, tuple[tuple[str, str], ...], frozenset[str]]:
    cols = next(t for t in config["tables"] if t["name"] == "t")["generate_columns"]
    plan_reason = next(c.reason for c in classify_plan(config).columns if c.column == "ev")
    window = classify_window_table(config, "t", statistical_specs={})
    return plan_reason, window.class_b_reasons, _batches.sibling_read_names(cols)


def test_the_three_readers_agree_with_the_declared_anchor() -> None:
    plan_reason, window_reasons, read = _readers(_config())
    assert plan_reason == "eligible"
    assert dict(window_reasons).get("ev") is None
    assert read == frozenset({"dob"})


def test_the_three_readers_follow_a_changed_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    real = gen_stream.sibling_input

    def elsewhere(col: dict[str, Any]) -> str | None:
        return "absent" if col.get("type") == "windowed_date" else real(col)

    config = _config()
    monkeypatch.setattr(gen_stream, "sibling_input", elsewhere)
    plan_reason, window_reasons, read = _readers(config)
    assert plan_reason == "windowed_date_anchor_not_in_table"
    assert dict(window_reasons).get("ev") == "windowed_date_anchor_not_earlier"
    assert read == frozenset({"absent"})


@pytest.mark.parametrize(
    ("col", "expected"),
    [
        ({"type": "windowed_date", "anchor": "a"}, "a"),
        ({"type": "categorical", "condition_on": "p"}, "p"),
        ({"type": "statistical", "condition_on": "p"}, "p"),
        ({"type": "statistical"}, None),
        ({"type": "windowed_date", "anchor": 3}, None),
        ({"type": "faker", "anchor": "a", "condition_on": "p"}, None),
    ],
)
def test_sibling_input_names_the_read_column(col: dict[str, Any], expected: str | None) -> None:
    assert gen_stream.sibling_input(col) == expected
