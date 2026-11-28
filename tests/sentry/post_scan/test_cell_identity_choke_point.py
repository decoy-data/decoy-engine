"""PM-1: `internal/cell_identity.py` is the only place post-scan code compares or counts cells.

An AST guard over the comparison paths. It resolves import aliases (`from numpy import equal as
eq`, `import pyarrow.compute as pc`), follows cell bindings through assignment, indexing, loops
and comprehensions, and flags an equality operator, a listed method or a listed library call
applied to them. It also flags imports of the retired canonical module and local copies of the
retired comparators. A detector's frequency count of its own matches reads no cell binding, so
it is not a comparison. Plan: docs/plans/2026-11-27-pm1-comparison-redesign.md, item 7 and
R2-D2.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.sentry.post_scan._scan import SRC, files

SCOPE = (
    "verification",
    "execution/pipeline/post_scan",
    "detection",
    "internal/cell_text.py",
)
AUTHORITY = "internal/cell_identity.py"
# The canary compares its own canonical text form; that helper is the one exception.
ALLOWED = {("verification/canary/_canonical.py", "def canonical_cells")}

METHODS = {"equals", "eq", "ne", "compare", "isin", "duplicated", "drop_duplicates", "unique"}
METHODS |= {"value_counts", "nunique", "factorize"}
CALLS = {
    "numpy.equal",
    "numpy.not_equal",
    "numpy.array_equal",
    "numpy.array_equiv",
    "pyarrow.compute.equal",
    "pyarrow.compute.not_equal",
    "pyarrow.Array.equals",
    "pandas.util.hash_pandas_object",
    "pandas.util.hash_array",
    "pandas.core.util.hashing.hash_pandas_object",
    "pandas.core.util.hashing.hash_array",
    "pandas.factorize",
}
CALL_PREFIXES = ("pandas.testing.",)
RETIRED_DEFS = {"identity_counts", "canonical_cells", "_compared", "_frozen", "key_text"}
RETIRED_MODULE = "decoy_engine.internal.canonical_cell"
# Readers that yield cells, column annotations, and frame-like names whose subscripts are columns.
CELL_CALLS = {"_series", "_column", "_first", "_first_columns", "_aligned_source", "to_pandas"}
CELL_TYPES = {"Series", "Array", "ChunkedArray", "ndarray"}
FRAMES = {"df", "src_df", "out_df", "frame", "src_frame", "out_frame", "source", "output"}


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


class _Guard(ast.NodeVisitor):
    def __init__(self) -> None:
        self.aliases: dict[str, str] = {}
        self.cells: set[str] = set()
        self.found: list[str] = []

    # -- imports and definitions
    def visit_Import(self, node: ast.Import) -> None:
        for name in node.names:
            if name.name.startswith(RETIRED_MODULE):
                self.found.append(f"import {name.name}")
            self.aliases[name.asname or name.name.split(".")[0]] = (
                name.name if name.asname else name.name.split(".")[0]
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module.startswith(RETIRED_MODULE):
            self.found.append(f"import {module}")
        for name in node.names:
            self.aliases[name.asname or name.name] = f"{module}.{name.name}"

    def _define(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if node.name in RETIRED_DEFS:
            self.found.append(f"def {node.name}")
        outer = set(self.cells)
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            note = arg.annotation
            names = (
                {
                    n.attr if isinstance(n, ast.Attribute) else getattr(n, "id", None)
                    for n in ast.walk(note)
                }
                if note
                else set()
            )
            self._bind(ast.Name(arg.arg), bool(names & CELL_TYPES))
        self.generic_visit(node)
        self.cells = outer

    visit_FunctionDef = visit_AsyncFunctionDef = _define  # noqa: N815

    # -- cell bindings
    def _resolved(self, node: ast.AST) -> str | None:
        dotted = _dotted(node)
        if dotted is None:
            return None
        head, _, rest = dotted.partition(".")
        base = self.aliases.get(head, head)
        return f"{base}.{rest}" if rest else base

    def _is_cell(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.cells
        if isinstance(node, ast.Subscript):
            value = node.value
            if isinstance(value, ast.Attribute) and value.attr in {"iloc", "loc", "iat", "at"}:
                return True
            if isinstance(value, ast.Name) and (value.id in FRAMES or value.id in self.cells):
                return True
            return self._is_cell(value)
        if isinstance(node, ast.Attribute) and node.attr in {"iloc", "values", "array"}:
            return self._is_cell(node.value)
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else _dotted(func)
            if name in CELL_CALLS:
                return True
            if isinstance(func, ast.Attribute) and func.attr == "astype":
                return any(isinstance(a, ast.Name) and a.id == "object" for a in node.args)
            if name in {"zip", "enumerate", "list", "tuple", "iter"}:
                return any(self._is_cell(a) for a in node.args)
            if isinstance(func, ast.Attribute) and func.attr in {"reset_index", "tolist", "copy"}:
                return self._is_cell(func.value)
        return False

    def _bind(self, target: ast.AST, cell: bool) -> None:
        for name in ast.walk(target):
            if isinstance(name, ast.Name):
                (self.cells.add if cell else self.cells.discard)(name.id)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.generic_visit(node)
        for target in node.targets:
            self._bind(target, self._is_cell(node.value))

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.generic_visit(node)
        if node.value is not None:
            self._bind(node.target, self._is_cell(node.value))

    def visit_For(self, node: ast.For) -> None:
        self._bind(node.target, self._is_cell(node.iter))
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self._bind(node.target, self._is_cell(node.iter))
        self.generic_visit(node)

    def _comprehension(self, node: ast.AST) -> None:
        # Generators bind before the element is read.
        for gen in node.generators:  # type: ignore[attr-defined]
            self.visit(gen)
        for field in ("elt", "key", "value"):
            child = getattr(node, field, None)
            if child is not None:
                self.visit(child)

    visit_ListComp = visit_SetComp = visit_GeneratorExp = visit_DictComp = _comprehension  # noqa: N815

    # -- comparisons
    def visit_Compare(self, node: ast.Compare) -> None:
        operands = [node.left, *node.comparators]
        if any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops) and any(
            self._is_cell(o) for o in operands
        ):
            self.found.append("== on cells")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        resolved = self._resolved(func)
        args = [*node.args, *(k.value for k in node.keywords)]
        if resolved is not None and (resolved in CALLS or resolved.startswith(CALL_PREFIXES)):
            if any(self._is_cell(a) for a in args):
                self.found.append(resolved)
        elif isinstance(func, ast.Attribute) and func.attr in METHODS and self._is_cell(func.value):
            self.found.append(f".{func.attr} on cells")
        self.generic_visit(node)


def violations(source: str) -> list[str]:
    guard = _Guard()
    guard.visit(ast.parse(source))
    return guard.found


def _scanned() -> list[tuple[str, str]]:
    found = []
    for path in files(*SCOPE):
        rel = path.relative_to(SRC).as_posix()
        if rel == AUTHORITY:
            continue
        for hit in violations(path.read_text(encoding="utf-8")):
            if (rel, hit) not in ALLOWED:
                found.append((rel, hit))
    return found


def test_only_the_authority_compares_cells() -> None:
    assert _scanned() == []


def test_the_scope_reaches_every_comparison_path() -> None:
    scanned = {p.relative_to(SRC).as_posix() for p in files(*SCOPE)}
    for rel in (
        "verification/postmask/_column_facts.py",
        "verification/postmask/policy_validation.py",
        "verification/postmask/residual_pii.py",
        "verification/postmask/runner.py",
        "execution/pipeline/post_scan/_gate.py",
        "execution/pipeline/post_scan/_suite.py",
        "internal/cell_text.py",
    ):
        assert rel in scanned


def test_the_canary_exception_is_its_one_helper() -> None:
    hits = violations((SRC / "verification/canary/_canonical.py").read_text(encoding="utf-8"))
    assert set(hits) <= {hit for _, hit in ALLOWED}


SEEDS = {
    "aliased numpy equal": "from numpy import equal as eq\ndef f(df):\n    s = df['a']\n    eq(s, s)",
    "qualified alias": "import pyarrow.compute as pc\ndef f(b):\n    x = _series(b, 'a')\n    pc.equal(x, x)",
    "module alias": "import numpy as np\ndef f(df):\n    np.array_equal(df['a'], df['b'])",
    "pandas testing": "import pandas as pd\ndef f(df):\n    pd.testing.assert_series_equal(df['a'], df['b'])",
    "loop over paired cells": (
        "def f(src_df, out_df):\n    for a, b in zip(src_df['v'], out_df['v']):\n        a == b"
    ),
    "comprehension over cells": "def f(df):\n    s = df['v']\n    [a != 1 for a in s]",
    "assigned binding": "def f(b):\n    s = _series(b, 'v')\n    t = s\n    t.eq(1)",
    "positional column": "def f(x):\n    x.iloc[:, 0].nunique()",
    "object cells": "def f(s):\n    t = s.astype(object)\n    t == 1",
    "annotated series": "def f(src: pd.Series, out: pd.Series):\n    return (src == out).sum()",
    "residual reader": "def f(df, c):\n    s = _first(df, c)\n    return (s == s).sum()",
    "arrow to pandas": "def f(a):\n    a.to_pandas().value_counts()",
    "retired import": "from decoy_engine.internal.canonical_cell import canonical_cell",
    "retired local comparator": "def _frozen(v):\n    return v",
}


@pytest.mark.parametrize("name", list(SEEDS))
def test_each_seeded_comparison_is_flagged(name: str) -> None:
    assert violations(SEEDS[name]), name


CLEAN = {
    "detector frequency count": "def f(matches):\n    return matches.value_counts()",
    "metadata comparison": "def f(finding):\n    return finding['severity'] == 'fail'",
    "schema names": "def f(table):\n    return table.schema.names == ['a']",
    "provider frozen helper elsewhere": "def frozen_value(v):\n    return v",
}


@pytest.mark.parametrize("name", list(CLEAN))
def test_an_unrelated_comparison_is_not_flagged(name: str) -> None:
    assert violations(CLEAN[name]) == []


def test_removing_loop_tracking_misses_its_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_Guard, "visit_For", lambda self, node: self.generic_visit(node))
    assert violations(SEEDS["loop over paired cells"]) == []


def test_removing_alias_resolution_misses_its_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_Guard, "_resolved", lambda self, node: _dotted(node))
    assert violations(SEEDS["aliased numpy equal"]) == []
    assert violations(SEEDS["qualified alias"]) == []


def test_the_scan_reads_real_files() -> None:
    assert Path(SRC / AUTHORITY).is_file()
    assert len(list(files(*SCOPE))) > 20
