# ruff: noqa: RUF001 - the fullwidth and ligature spellings are the subject of these tests
"""AT-S1e: a `when:` predicate's declared reads are the columns the evaluator reads.

`_column_access._when` is built on `when_column_refs`, the one producer of `WhenRead`, so the
chunk carry, the native admission and the evaluator's alias map cannot disagree. A read the
declaration misses would get a null placeholder and silently change the mask. The generic
pandas-expression scanner (`predicate_names`) serves derived and transform expressions, a
separate language, and is pinned by `test_transform_expression_readers_keep_the_generic_scanner`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.errors import ValidationError
from decoy_engine.execution._column_access import _READS_UNKNOWN, SURFACE_DECLARATIONS
from decoy_engine.execution._when_gate import _aliased_frame
from decoy_engine.expressions._when_parser import alias_reads, parse_when
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


# ---------------------------------------------------------------------------
# WHEN-READS-SOURCE S2: every `_eval_predicate` caller evaluates over original values.
# ---------------------------------------------------------------------------

_SRC = Path(__file__).resolve().parents[3] / "src" / "decoy_engine" / "execution"
# (file, the one allowed first argument as source text, why it holds original values)
_EVAL_CALLERS = {
    "_when_gate.py": ("source", "`when_source_frame`: the live frame with pre-mask snapshots"),
    "native/_when_mask.py": ("frame", "the raw chunk the source produced, before any mask"),
    "_unified_slice_when.py": ("frame", "the unified slice's source frame, before any mask"),
}


def _eval_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text())
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_eval_predicate"
    ]


def test_every_predicate_evaluation_reads_an_allowed_frame() -> None:
    """A new `_eval_predicate` caller, or a caller that changes its frame argument, fails here
    until it is added to `_EVAL_CALLERS` with its reason."""
    found = {
        str(p.relative_to(_SRC)): [ast.unparse(c.args[0]) for c in calls]
        for p in _SRC.rglob("*.py")
        if (calls := _eval_calls(p))
    }
    assert found == {name: [arg] for name, (arg, _why) in _EVAL_CALLERS.items()}


def test_the_gate_frame_comes_from_when_source_frame() -> None:
    tree = ast.parse((_SRC / "_when_gate.py").read_text())
    gate = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "run_with_when_gate"
    )
    assigned = [
        ast.unparse(n.value)
        for n in ast.walk(gate)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "source" for t in n.targets)
    ]
    assert len(assigned) == 1 and assigned[0].startswith("when_source_frame(")


def test_the_unified_slice_passes_the_candidate_source_frame() -> None:
    """`compute_when_masks` must get the candidate's source frame, never a frame the run masked."""
    tree = ast.parse((_SRC / "_unified_slice.py").read_text())
    args = [
        ast.unparse(n.args[0])
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "compute_when_masks"
    ]
    assert args == ["candidate.source_frame"]
