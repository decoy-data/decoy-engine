"""GEN-INHERIT E2: a formula with `references` is filled after the column loop.

It holds None until the post-pass after every other column is drawn, so a column of another type
that reads it while it is drawn is refused like a forward read, at both validate and compile.
The helpers are the ones `test_generate_columns.py` asserts every generate-column refusal with.
"""

from __future__ import annotations

from typing import Any

from tests.unit.plan.checks.test_generate_columns import (
    FORWARD,
    assert_accepted,
    assert_refused,
    cfg,
    derived,
    formula,
    generated,
    p,
    seq,
)


def _filled_late(name: str = "f") -> dict[str, Any]:
    return formula(name, "'north' if int(a) % 2 else 'south'", ["a"])


def _drawn_now(name: str = "f") -> dict[str, Any]:
    return formula(name, "'north'")


def _conditional(on: str = "f") -> dict[str, Any]:
    return {
        "name": "tier",
        "type": "categorical",
        "categories": ["basic", "plus"],
        "condition_on": on,
        "by": {"north": {"categories": ["gold"]}},
    }


def _joint_snapshot(tmp_path: Any) -> str:
    import json

    import pandas as pd

    from decoy_engine.quality.snapshot import compute_distribution_snapshot

    df = pd.DataFrame({"f": ["north", "south"] * 60, "tier": ["gold", "silver"] * 60})
    path = tmp_path / "joint.json"
    snap = compute_distribution_snapshot(df, joint_columns=[("f", "tier")])
    path.write_text(json.dumps(snap), encoding="utf-8")
    return str(path)


def _fitted(snapshot: str) -> dict[str, Any]:
    return {
        "name": "tier",
        "type": "statistical",
        "snapshot_file": snapshot,
        "allow_real_categories": True,
        "condition_on": "f",
    }


def test_a_conditional_categorical_reading_a_formula_filled_late_is_refused() -> None:
    config = cfg([seq("a"), _filled_late(), _conditional()])
    assert_refused(config, FORWARD, p("tier", "condition_on"))


def test_a_fitted_condition_on_reading_a_formula_filled_late_is_refused(tmp_path: Any) -> None:
    config = cfg([seq("a"), _filled_late(), _fitted(_joint_snapshot(tmp_path))])
    assert_refused(config, FORWARD, p("tier", "condition_on"))


def test_a_derived_column_reading_a_formula_filled_late_is_refused() -> None:
    config = cfg([seq("a"), formula("f", "int(a) * 2", ["a"]), derived("f + 1")])
    assert_refused(config, FORWARD, p("x", "expression"))


def test_a_formula_drawn_in_the_loop_may_be_read_by_any_type(tmp_path: Any) -> None:
    conditional = cfg([seq("a"), _drawn_now(), _conditional()])
    assert_accepted(conditional)
    assert generated(conditional, "tier") == ["gold"] * 5
    assert_accepted(cfg([seq("a"), _drawn_now(), _fitted(_joint_snapshot(tmp_path))]))


def test_a_formula_reading_a_formula_filled_late_is_unchanged() -> None:
    chain = cfg([seq("a"), _filled_late(), formula("g", "f + '!'", ["f"])])
    assert_accepted(chain)
    assert generated(chain, "g") == ["north!", "south!"] * 2 + ["north!"]
    later = cfg([seq("a"), formula("g", "f + '!'", ["f"]), _filled_late()])
    assert_refused(later, FORWARD, p("g", "references.0"))
    reader = cfg([seq("a"), _filled_late(), formula("g", "f + '!'", ["f"]), _conditional("g")])
    assert_refused(reader, FORWARD, p("tier", "condition_on"))
