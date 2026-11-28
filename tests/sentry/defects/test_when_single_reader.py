# ruff: noqa: RUF001 - the fullwidth and ligature spellings are the subject of these tests
"""AT-S1e: a `when:` predicate's declared reads are the columns the evaluator reads.

`plan.column_access._when` is built on `when_column_refs`, the one producer of `WhenRead`, so the
chunk carry, the native admission and the evaluator's alias map cannot disagree. A read the
declaration misses would get a null placeholder and silently change the mask. The generic
pandas-expression scanner (`predicate_names`) serves derived and transform expressions, a
separate language, and is pinned by `test_transform_expression_readers_keep_the_generic_scanner`.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.errors import ValidationError
from decoy_engine.execution._when_gate import _aliased_frame
from decoy_engine.expressions._when_parser import alias_reads, parse_when
from decoy_engine.plan.column_access._declarations import _READS_UNKNOWN, SURFACE_DECLARATIONS
from tests.native._chunked_entry_support import make_config, passthrough, redact
from tests.native._rev9_support import run_entry_below_gate, run_public_below_gate, same_column

_WHEN = SURFACE_DECLARATIONS["surface:when"]

# (predicate, the columns it reads, written by hand: not derived from `when_column_refs`)
_VALID: dict[str, tuple[str, frozenset[str]]] = {
    "bare": ("x > 4", frozenset({"x"})),
    "two_columns": ("left > 0 and right == 'go'", frozenset({"left", "right"})),
    "quoted_dotted": ("`a.b` > 4", frozenset({"a.b"})),
    "quoted_fullwidth": ("`\uff58` > 4", frozenset({"\uff58"})),
    "quoted_ligature": ("`\ufb01le` > 4", frozenset({"\ufb01le"})),
    "source_bare": ("source.x > 4", frozenset({"x"})),
    "source_spaced": ("source . x > 4", frozenset({"x"})),
    "source_quoted": ("source.`my col` > 4", frozenset({"my col"})),
    "literal_holds_a_column_name": ("x == 'other'", frozenset({"x"})),
}
_INVALID = {
    "bare_fullwidth": "ｘ > 4",
    "bare_ligature": "ﬁle > 4",
    "source_bare_fullwidth": "source.ｘ > 4",
    "source_bare_ligature": "source.ﬁle > 4",
    "unparsable": "x >",
    "method_call": "x.notnull()",
}


def _evaluator_selects(expr: str, expected: frozenset[str]) -> int:
    """How many columns `_aliased_frame` takes from a frame holding `expected` and extras."""
    _, aliases = alias_reads(parse_when(expr))
    frame = pd.DataFrame({c: [1] for c in sorted(expected | {"unrelated"})})
    return len(_aliased_frame(frame, aliases).columns)


@pytest.mark.parametrize("case", _VALID)
def test_when_declared_reads_equal_the_hand_written_set_and_the_evaluator(case: str) -> None:
    expr, expected = _VALID[case]
    access = _WHEN({"name": "s", "strategy": "redact", "when": expr})
    assert not access.reads_unknown
    assert access.reads == expected
    assert _evaluator_selects(expr, expected) == len(expected)


def test_when_reads_keep_the_exact_quoted_text() -> None:
    assert _WHEN({"when": "`ｘ` > 4"}).reads == frozenset({"ｘ"})
    assert _WHEN({"when": "`ﬁle` > 4"}).reads == frozenset({"ﬁle"})
    assert _WHEN({"when": "x == 'other'"}).reads == frozenset({"x"})


@pytest.mark.parametrize("case", _INVALID)
def test_when_refusal_declares_reads_unknown(case: str) -> None:
    expr = _INVALID[case]
    with pytest.raises(ValidationError) as info:
        parse_when(expr)
    assert info.value.code == "when_outside_closed_grammar"
    assert _WHEN({"name": "s", "strategy": "redact", "when": expr}) == _READS_UNKNOWN


@pytest.mark.parametrize("configured", [False, True], ids=["unconfigured", "configured"])
def test_two_column_when_carries_both_reads_and_matches_the_oracle(configured: bool) -> None:
    expr = "left > 0 and right == 'go'"
    cols: list[dict[str, Any]] = [{**redact("s"), "when": expr}]
    if configured:
        cols += [passthrough("left"), passthrough("right")]
    chunks = [
        pa.table(
            {
                "s": ["alice", "bob", "carol"],
                "left": pa.array(left, pa.int64()),
                "right": ["go", "stop", "go"],
            }
        )
        for left in ([1, 5, 0], [9, 1, 5], [0, 6, 3])
    ]
    expected = run_public_below_gate(make_config(cols), chunks)
    out, sink, _ = run_entry_below_gate(make_config(cols), chunks)
    listed = [r.quality_metrics["chunked_route"]["pandas_read_passthrough"] for r in sink]
    assert listed == [["left", "right"]] * 3
    for got, want in zip(out, expected, strict=True):
        assert got.column("s").to_pylist() == want.column("s").to_pylist()
        assert same_column(got.column("left"), want.column("left"))
        assert same_column(got.column("right"), want.column("right"))
