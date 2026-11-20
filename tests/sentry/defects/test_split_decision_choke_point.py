"""One multi-table split decision per run (NONFK-OOM S4a, guard G-2).

`decide_multi_table_split` has two production call sites: `pipeline/_route_decision.decide_split`
(called by `_pipeline_context.decide_route`) for the ordinary run and `pipeline/_stream.py` for a run that requires streaming. The executor reads
`RouteDecision.split` and never decides. A third site would let the resident set the capacity stage
prices drift from the tables the executor dispatches.

The scan resolves `from m import decide_multi_table_split as d`, plain re-bindings and attribute
calls (`mod.decide_multi_table_split(...)`, which also covers `import m as mod`).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.sentry._call_resolution import resolved_calls

SRC = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"
TARGET = "decide_multi_table_split"
OWNER = SRC / "execution" / "_pipeline_multi_table.py"
SITES = {
    "execution/pipeline/_route_decision.py": 1,
    "execution/pipeline/_stream.py": 1,
}


def call_counts(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        if path == OWNER:
            continue
        found = len(resolved_calls(ast.parse(path.read_text(encoding="utf-8")), TARGET))
        if found:
            counts[path.relative_to(root).as_posix()] = found
    return counts


def test_the_split_has_exactly_the_two_production_call_sites() -> None:
    assert call_counts(SRC) == SITES


@pytest.mark.parametrize(
    "source",
    [
        f"{TARGET}(config)\n",
        f"from decoy_engine.execution import _pipeline_multi_table as m\nm.{TARGET}(config)\n",
        f"from x import {TARGET} as d\nd(config)\n",
        f"from x import {TARGET} as d\ne = d\ne(config)\n",
        f"import decoy_engine.execution._pipeline_multi_table as m\nm.{TARGET}(config)\n",
    ],
)
def test_every_spelling_of_a_call_is_counted(source: str, tmp_path: Path) -> None:
    (tmp_path / "executor.py").write_text(source, encoding="utf-8")
    assert call_counts(tmp_path) == {"executor.py": 1}
