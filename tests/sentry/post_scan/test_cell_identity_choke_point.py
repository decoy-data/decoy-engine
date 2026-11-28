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
    "internal/cell_atoms.py",
)
AUTHORITY = "internal/cell_identity.py"
# The canary compares its own canonical text form; that helper is the one exception.
CANARY = "verification/canary/_canonical.py"
CANARY_HELPER = "def canonical_cells"

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
    "numpy.unique",
    "numpy.isin",
    "pandas.unique",
    "pyarrow.compute.unique",
    "pyarrow.compute.count_distinct",
    "pyarrow.compute.is_in",
    "pyarrow.compute.index_in",
    "operator.eq",
    "operator.ne",
}
# Collections built from cells count or dedupe them.
COLLECTORS = {"set", "frozenset", "collections.Counter"}
CALL_PREFIXES = ("pandas.testing.",)
RETIRED_DEFS = {"identity_counts", "canonical_cells", "_compared", "_frozen", "key_text"}
# Built from parts: the module is retired, so the string-target sentry must not resolve it.
RETIRED_MODULE = "decoy_engine.internal." + "canonical_cell"
# Readers that yield cells, column annotations, and frame-like names whose subscripts are columns.
CELL_CALLS = {"_series", "_column", "_first", "_first_columns", "_aligned_source", "to_pandas"}
CELL_CALLS |= {"column"}
CELL_TYPES = {"Series", "Array", "ChunkedArray", "ndarray", "Column", "DataFrame", "Table"}
CELL_TYPES |= {"RecordBatch"}
FRAMES = {"df", "src_df", "out_df", "frame", "src_frame", "out_frame", "source", "output"}
FRAMES |= {"table", "src_table", "out_table", "batch"}
# Conversions that keep the cells they read.
PASS_THROUGH = {"reset_index", "tolist", "copy", "to_numpy", "to_list", "to_pylist"}


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


class _Guard(ast.NodeVisitor):
    def __init__(self, package: str | None = None) -> None:
        self.package = package
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
        if node.level and self.package:
            parts = self.package.split(".")
            base = ".".join(parts[: len(parts) - (node.level - 1)])
            module = f"{base}.{module}" if module else base
        if any(f"{module}.{n.name}".startswith(RETIRED_MODULE) for n in node.names):
            self.found.append(f"import {RETIRED_MODULE}")
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
            if isinstance(func, ast.Attribute) and func.attr in PASS_THROUGH:
                return self._is_cell(func.value)
        return False

    def _bind(self, target: ast.AST, cell: bool) -> None:
        for name in ast.walk(target):
            if isinstance(name, ast.Name):
                (self.cells.add if cell else self.cells.discard)(name.id)

    def _bind_pair(self, target: ast.AST, value: ast.AST) -> None:
        # `a, b = x, y` binds element by element.
        if (
            isinstance(target, (ast.Tuple, ast.List))
            and isinstance(value, (ast.Tuple, ast.List))
            and len(target.elts) == len(value.elts)
        ):
            for t, v in zip(target.elts, value.elts, strict=True):
                self._bind_pair(t, v)
        else:
            self._bind(target, self._is_cell(value))

    def visit_Assign(self, node: ast.Assign) -> None:
        self.generic_visit(node)
        for target in node.targets:
            self._bind_pair(target, node.value)

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
        elif resolved in COLLECTORS and any(self._is_cell(a) for a in args):
            self.found.append(f"{resolved} on cells")
        elif isinstance(func, ast.Attribute) and func.attr in METHODS and self._is_cell(func.value):
            self.found.append(f".{func.attr} on cells")
        self.generic_visit(node)


def violations(source: str, package: str | None = None) -> list[str]:
    guard = _Guard(package)
    guard.visit(ast.parse(source))
    return guard.found


def _scanned() -> list[tuple[str, str]]:
    found = []
    for path in files(*SCOPE):
        rel = path.relative_to(SRC).as_posix()
        if rel == AUTHORITY:
            continue
        package = ".".join(["decoy_engine", *Path(rel).parent.parts])
        excused = False
        for hit in violations(path.read_text(encoding="utf-8"), package):
            if not excused and (rel, hit) == (CANARY, CANARY_HELPER):
                excused = True
                continue
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
        "internal/cell_atoms.py",
    ):
        assert rel in scanned


def test_the_canary_exception_is_its_one_helper() -> None:
    hits = violations((SRC / CANARY).read_text(encoding="utf-8"))
    assert hits == [CANARY_HELPER]


_PARENT, _, _LEAF = RETIRED_MODULE.rpartition(".")
SEEDS = {
    "aliased numpy equal": (
        "from numpy import equal as eq\ndef f(df):\n    s = df['a']\n    eq(s, s)",
        "numpy.equal",
    ),
    "qualified alias": (
        "import pyarrow.compute as pc\ndef f(b):\n    x = _series(b, 'a')\n    pc.equal(x, x)",
        "pyarrow.compute.equal",
    ),
    "module alias": (
        "import numpy as np\ndef f(df):\n    np.array_equal(df['a'], df['b'])",
        "numpy.array_equal",
    ),
    "pandas testing": (
        "import pandas as pd\ndef f(df):\n    pd.testing.assert_series_equal(df['a'], df['b'])",
        "pandas.testing.assert_series_equal",
    ),
    "loop over paired cells": (
        "def f(src_df, out_df):\n    for a, b in zip(src_df['v'], out_df['v']):\n        a == b",
        "== on cells",
    ),
    "comprehension over cells": (
        "def f(df):\n    s = df['v']\n    [a != 1 for a in s]",
        "== on cells",
    ),
    "assigned binding": (
        "def f(b):\n    s = _series(b, 'v')\n    t = s\n    t.eq(1)",
        ".eq on cells",
    ),
    "positional column": ("def f(x):\n    x.iloc[:, 0].nunique()", ".nunique on cells"),
    "object cells": ("def f(s):\n    t = s.astype(object)\n    t == 1", "== on cells"),
    "annotated series": (
        "def f(src: pd.Series, out: pd.Series):\n    return (src == out).sum()",
        "== on cells",
    ),
    "residual reader": (
        "def f(df, c):\n    s = _first(df, c)\n    return (s == s).sum()",
        "== on cells",
    ),
    "arrow to pandas": ("def f(a):\n    a.to_pandas().value_counts()", ".value_counts on cells"),
    "retired import": (f"import {RETIRED_MODULE}", f"import {RETIRED_MODULE}"),
    "retired from-import": (f"from {_PARENT} import {_LEAF}", f"import {RETIRED_MODULE}"),
    "retired local comparator": ("def _frozen(v):\n    return v", "def _frozen"),
    "tuple assignment": (
        "def f(t):\n    s, o = _series(t, 'a'), _series(t, 'b')\n    s == o",
        "== on cells",
    ),
    "table subscripts": (
        "def f(src_table, out_table):\n    return src_table['a'] == out_table['a']",
        "== on cells",
    ),
    "annotated frame": ("def f(t: pd.DataFrame):\n    return t['a'].eq(1)", ".eq on cells"),
    "numpy conversion": (
        "def f(df):\n    s = df['a']\n    return (s.to_numpy() == s.to_numpy()).all()",
        "== on cells",
    ),
    "numpy unique": (
        "import numpy as np\ndef f(df):\n    return len(np.unique(df['a']))",
        "numpy.unique",
    ),
    "arrow count distinct": (
        "import pyarrow.compute as pc\ndef f(b):\n    return pc.count_distinct(_column(b, 'a'))",
        "pyarrow.compute.count_distinct",
    ),
    "set of cells": ("def f(df):\n    return len(set(df['a']))", "set on cells"),
    "counter of cells": (
        "from collections import Counter\ndef f(df):\n    return Counter(df['a'])",
        "collections.Counter on cells",
    ),
    "batch column": (
        "def f(batch):\n    c = batch.column(0)\n    return c.unique()",
        ".unique on cells",
    ),
    "operator equal": (
        "import operator\ndef f(df):\n    return operator.eq(df['a'], df['b'])",
        "operator.eq",
    ),
}


@pytest.mark.parametrize("name", list(SEEDS))
def test_each_seeded_comparison_is_flagged(name: str) -> None:
    source, label = SEEDS[name]
    assert label in violations(source), name


def test_a_relative_import_of_the_retired_module_is_flagged() -> None:
    source = f"from ..internal.{_LEAF} import x"
    assert violations(source, "decoy_engine.verification") == [f"import {RETIRED_MODULE}"]


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
    assert violations(SEEDS["loop over paired cells"][0]) == []


def test_removing_alias_resolution_misses_its_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_Guard, "_resolved", lambda self, node: _dotted(node))
    assert violations(SEEDS["aliased numpy equal"][0]) == []
    assert violations(SEEDS["qualified alias"][0]) == []


def test_the_scan_reads_real_files() -> None:
    assert Path(SRC / AUTHORITY).is_file()
    assert len(list(files(*SCOPE))) > 20
