"""AT-V9 (DATE-RANGE-SENTINEL S5, section 4.4b rule 3): `io/source_dates.py` is held to a closed
vocabulary, so a walk of a container's storage cannot slip back in. It may call only the listed
`pyarrow.compute` functions, touch only the listed attributes and import only the listed names; a
layout it does not know is refused by type before this module counts anything."""

from __future__ import annotations

import ast
from pathlib import Path

import pyarrow as pa
import pytest

import decoy_engine.io.source_dates as module
from decoy_engine.io import source_dates

PC_ALLOWED = frozenset(
    {
        "min_max",
        "less",
        "greater",
        "or_",
        "and_",
        "invert",
        "fill_null",
        "sum",
        "local_timestamp",
        "cumulative_sum",
        "subtract",
        "take",
    }
)
# Type and schema accessors, the four array methods the check needs, the pyarrow constructors it
# builds output with, and the dataclass helpers that rebind a lazy source.
ATTRS_ALLOWED = frozenset(
    {
        "type",
        "unit",
        "tz",
        "value_type",
        "index_type",
        "ordered",
        "schema",
        "names",
        "types",
        "name",
        "cast",
        "filter",
        "chunks",
        "dictionary",
        "indices",
        "column",
        "num_columns",
        "from_arrays",
        "as_py",
        "is_date32",
        "is_date64",
        "is_dictionary",
        "int32",
        "int64",
        "scalar",
        "chunked_array",
        "Table",
        "RecordBatch",
        "ChunkedArray",
        "DictionaryArray",
        "DataType",
        "Schema",
        "is_dataclass",
        "fields",
        "replace",
    }
)
IMPORTS_ALLOWED = {
    "decoy_engine.io.bounded_reader": {
        "SourceDateTypeUnsupportedError",
        "SourceDateUnrepresentableError",
    },
    "decoy_engine._arrow_types": {
        "CALENDAR_FIRST_DAY_NUMBER",
        "CALENDAR_LAST_DAY_NUMBER",
        "is_admitted_date_shape",
        "is_date_dictionary",
        "is_date_leaf",
        "is_unclassified",
        "type_kind",
        "type_nodes",
    },
}
MODULES_ALLOWED = {
    "__future__",
    "collections.abc",
    "typing",
    "dataclasses",
    "pyarrow",
    "pyarrow.compute",
}


def _compute_aliases(tree: ast.AST) -> set[str]:
    """Every local name bound to `pyarrow.compute`: the import spellings and plain aliases."""
    aliases = {"pc", "_pc"}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            bound: str | None = None
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "pyarrow.compute" and a.asname:
                        bound = a.asname
            elif isinstance(node, ast.ImportFrom) and node.module == "pyarrow":
                for a in node.names:
                    if a.name == "compute":
                        bound = a.asname or "compute"
            elif isinstance(node, ast.Assign | ast.AnnAssign):
                value = node.value
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if isinstance(value, ast.Name) and value.id in aliases:
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id not in aliases:
                            aliases.add(target.id)
                            changed = True
            if bound is not None and bound not in aliases:
                aliases.add(bound)
                changed = True
    return aliases


def violations(text: str) -> list[str]:
    found: list[str] = []
    tree = ast.parse(text)
    compute = _compute_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            on_compute = isinstance(node.value, ast.Name) and node.value.id in compute
            allowed = PC_ALLOWED if on_compute else ATTRS_ALLOWED
            if node.attr not in allowed:
                found.append(f"{'pc.' if on_compute else '.'}{node.attr}")
        elif isinstance(node, ast.Import):
            found += [f"import {a.name}" for a in node.names if a.name not in MODULES_ALLOWED]
        elif isinstance(node, ast.ImportFrom):
            names = {a.name for a in node.names}
            if node.module == "pyarrow.compute":  # a bare name would dodge the attribute check
                found += [f"from pyarrow.compute import {n}" for n in names - PC_ALLOWED]
            elif node.module == "pyarrow":
                found += [f"from pyarrow import {n}" for n in names - {"compute"}]
            elif node.module in IMPORTS_ALLOWED:
                found += [
                    f"from {node.module} import {n}" for n in names - IMPORTS_ALLOWED[node.module]
                ]
            elif node.module not in MODULES_ALLOWED:
                found.append(f"from {node.module} import ...")
    return found


def test_source_dates_stays_inside_its_closed_vocabulary() -> None:
    assert violations(Path(module.__file__ or "").read_text()) == []


@pytest.mark.parametrize(
    "seed",
    [
        "x = pc.list_flatten(column)",
        "x = _pc.struct_field(column, 0)",
        "x = column.storage",
        "x = column.values",
        "x = column.flatten()",
        "x = column.keys",
        "x = column.items",
        "x = column.field(0)",
        "x = column.offsets",
        "x = column.buffers()",
        "x = column.run_ends",
        "import numpy",
        "from decoy_engine.profile import LazySource",
        "from decoy_engine._arrow_types import type_children",
        "from pyarrow.compute import list_flatten\nx = list_flatten(column)",
        "import pyarrow.compute as xc\nx = xc.cast(column)",
        "from pyarrow import compute as xc\nx = xc.filter(column, 0)",
        "import pyarrow.compute as xc\nyc = xc\nx = yc.cast(column)",
    ],
)
def test_a_seeded_walk_or_import_fails_the_vocabulary(seed: str) -> None:
    assert violations(seed) != []


def test_the_counting_function_raises_for_a_container_that_reached_it() -> None:
    """The gate refuses these first. If a gate ever lets one through, the count fails loudly
    instead of returning a number for storage it did not read (M-25)."""
    column = pa.chunked_array([pa.array([[0]], pa.list_(pa.date32()))])
    with pytest.raises(RuntimeError):
        source_dates._offending_rows(column)


def test_the_counting_function_returns_zero_for_a_type_with_no_date() -> None:
    assert (
        source_dates._offending_rows(pa.chunked_array([pa.array([[1]], pa.list_(pa.int8()))])) == 0
    )
