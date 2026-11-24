"""One output-assembly path (UF-DOMAIN S1): a masked pandas frame becomes an output table only in
`table_from_pandas_keeping_source_types`, so no route can bring back a pandas type round trip
for a column no rule changed.

Pure AST over `src/decoy_engine/execution/`: a call to `Table.from_pandas`, `RecordBatch.from_pandas`
or `Schema.from_pandas` is red unless its (module, function) is listed in `ALLOWED` with the reason
it does not build an output table. Output-bound code calls the assembler instead.

Named limits: a conversion reached through an alias of `pa` or through `getattr` is not modelled,
and `pa.array(..., from_pandas=True)` (a column, not a table) is out of scope. The list may only
shrink: an entry whose call site is gone fails.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXECUTION = ROOT / "src" / "decoy_engine" / "execution"
ASSEMBLER = ("execution/pipeline/_source_types.py", "table_from_pandas_keeping_source_types")
CONSTRUCTORS = frozenset({"Table", "RecordBatch", "Schema"})

ALLOWED: dict[tuple[str, str], str] = {
    ASSEMBLER: "the one assembler",
    ("execution/_mixed_fk_bridge.py", "_write_back_fk_column"): (
        "converts one FK key column to read back its resolved Arrow type; the stitch writes that "
        "column, not a table"
    ),
    ("execution/_transforms_table.py", "_apply_ops"): (
        "infers the schema of the columns a transform derives; no table is built"
    ),
    ("execution/_unified_slice_admission.py", "cheap_admission"): (
        "the admission-only round trip that checks the frame converts as the oracle would; the "
        "result is compared, never published"
    ),
    ("execution/pipeline/_lifecycle_inputs.py", "_read_csv"): "reads a source sample (input)",
    (
        "execution/pipeline/_lifecycle_inputs.py",
        "_read_fixed_width",
    ): "reads a source sample (input)",
}


def _sites(source: str) -> list[str]:
    """The enclosing function name of every table-level `from_pandas` call in `source`."""
    found: list[str] = []

    def walk(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = (
                child.name
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                else function
            )
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "from_pandas"
                and isinstance(child.func.value, ast.Attribute)
                and child.func.value.attr in CONSTRUCTORS
            ):
                found.append(function)
            walk(child, inner)

    walk(ast.parse(source), "<module>")
    return found


def _live() -> Counter[tuple[str, str]]:
    live: Counter[tuple[str, str]] = Counter()
    for path in sorted(EXECUTION.rglob("*.py")):
        rel = "execution/" + path.relative_to(EXECUTION).as_posix()
        for function in _sites(path.read_text(encoding="utf-8")):
            live[(rel, function)] += 1
    return live


def test_only_the_assembler_and_listed_non_output_sites_convert_a_frame() -> None:
    stray = sorted(set(_live()) - set(ALLOWED))
    assert not stray, f"a frame becomes a table outside the one assembler: {stray}"


def test_every_listed_site_still_exists() -> None:
    stale = sorted(set(ALLOWED) - set(_live()))
    assert not stale, f"remove the stale entry (the list may only shrink): {stale}"


def test_the_assembler_is_the_output_path_of_every_pandas_route() -> None:
    for module in ("_pandas_adapter.py", "_sequential.py", "_unified_slice_evidence.py"):
        text = (EXECUTION / module).read_text(encoding="utf-8")
        assert "table_from_pandas_keeping_source_types(" in text, module


_SEEDED_DIRECT = """
import pyarrow as pa

def reconstruct_source_shaped_output(frame, source, untouched):
    return pa.Table.from_pandas(frame, preserve_index=False)
"""

_SEEDED_ASSEMBLER = """
from decoy_engine.execution.pipeline._source_types import table_from_pandas_keeping_source_types

def reconstruct_source_shaped_output(frame, source, untouched):
    return table_from_pandas_keeping_source_types(frame, source, untouched)
"""


def test_scan_sees_a_direct_conversion_and_ignores_the_assembler_call() -> None:
    assert _sites(_SEEDED_DIRECT) == ["reconstruct_source_shaped_output"]
    assert _sites(_SEEDED_ASSEMBLER) == []


def test_scan_sees_record_batch_and_schema_conversions() -> None:
    code = (
        "def f(x):\n    a = pa.RecordBatch.from_pandas(x)\n    return pa.Schema.from_pandas(x), a\n"
    )
    assert _sites(code) == ["f", "f"]
