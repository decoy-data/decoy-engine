"""The detectors and the post-scan runner turn cells into text only through `internal/cell_text`.

A second conversion rule is how a byte-encoded email read as `b'...'` or `<memory at ...>` and
passed the scan, and how an undecodable byte column raised a decode error that names its bytes.
This scan walks the AST of the modules that feed cells to the detectors and fails on any other
text conversion: `str`/`repr`/`format`/`ascii` called on anything, a text dtype given to `astype`
or `cast`, `str` passed as a function (`.map(str)`, `.apply(str)`), and an f-string that formats a
value. Aliases count: `S = str`, `from builtins import str as S`, `import builtins as b; b.str`,
`np.str_`. The few calls that read a table or column name (never a cell) are listed in ALLOWLIST.
A site's key carries the loop it sits in, so an entry pins both the call and what its argument
iterates over: `str(c) for c in frame.columns` is a name, `str(c) for c in cells` is not.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
SCANNED = ("detection/_scoring.py", "verification/postmask/runner.py")

_TEXT_BUILTINS = frozenset({"str", "repr", "format", "ascii"})
_NUMPY_TEXT = frozenset({"str_", "unicode_", "bytes_", "string_"})
_TEXT_DTYPE = re.compile(r"[<>=|]?(?:u\d*|str\d*|string(?:\[\w+\])?|unicode)")
_TEXT_TYPE_FACTORIES = frozenset(
    {"string", "large_string", "utf8", "large_utf8", "string_view", "StringDtype"}
)

_RUNNER = "verification/postmask/runner.py"

# `module::function::source for target in iterable` of a conversion that reads a name, not a cell.
ALLOWLIST: dict[str, str] = {
    f"{_RUNNER}::run_post_mask::str(name) for name in output_frames": (
        "a table name for tables_checked, not a cell"
    ),
    f"{_RUNNER}::run_post_mask_tables::str(name) for name in output_tables": (
        "a table name for tables_checked, not a cell"
    ),
    f"{_RUNNER}::_frame_table::str(c) for c in frame.columns": (
        "a column name of the frame, not a cell"
    ),
    f"{_RUNNER}::_frame_table::str(c) for (n, c) in reversed(list(enumerate(other.columns)))": (
        "a column name of the other frame, matched to the frame's, not a cell"
    ),
}


def _is_text_dtype(node: ast.expr, aliases: set[str], modules: set[str]) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _TEXT_DTYPE.fullmatch(node.value.lower()) is not None
    if isinstance(node, ast.Call):  # pa.string(), pd.StringDtype()
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        return name in _TEXT_TYPE_FACTORIES
    return _is_text_callable(node, aliases, modules)


def _is_text_callable(node: ast.expr, aliases: set[str], modules: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in aliases
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        owner = node.value.id
        if owner in modules and node.attr in _TEXT_BUILTINS:
            return True
        return node.attr in _NUMPY_TEXT
    return False


def _aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Names bound to a text builtin, and names bound to the `builtins` module."""
    aliases, modules = set(_TEXT_BUILTINS), {"builtins", "__builtins__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.asname or a.name for a in node.names if a.name == "builtins")
        elif isinstance(node, ast.ImportFrom) and node.module in {"builtins", "numpy"}:
            wanted = _TEXT_BUILTINS if node.module == "builtins" else _NUMPY_TEXT
            aliases.update(a.asname or a.name for a in node.names if a.name in wanted)
    changed = True
    while changed:  # `S = str` then `T = S`
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and _is_text_callable(node.value, aliases, modules):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id not in aliases:
                        aliases.add(target.id)
                        changed = True
    return aliases, modules


def _function_of(tree: ast.Module) -> dict[ast.AST, str]:
    owner: dict[ast.AST, str] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):  # an inner function is walked later and wins
                owner[node] = fn.name
    return owner


def _loop_of(tree: ast.Module) -> dict[ast.AST, str]:
    """For each node in a loop body, ` for target in iterable` of the innermost loop around it."""
    loop: dict[ast.AST, str] = {}
    comps = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)
    for node in ast.walk(tree):  # outer loops first, so an inner loop is walked later and wins
        if isinstance(node, comps):
            text = "".join(
                f" for {ast.unparse(g.target)} in {ast.unparse(g.iter)}" for g in node.generators
            )
            body = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            text = f" for {ast.unparse(node.target)} in {ast.unparse(node.iter)}"
            body = node.body
        else:
            continue
        for part in body:
            for inner in ast.walk(part):
                loop[inner] = text
    return loop


def _is_type_name(node: ast.expr) -> bool:
    """`type(x).__name__`: a class name, which is value-free."""
    return isinstance(node, ast.Attribute) and node.attr == "__name__"


def conversions(module: str, text: str) -> list[str]:
    """`module::function::source` of every text conversion in `text`, with the loop around it."""
    tree = ast.parse(text)
    aliases, modules = _aliases(tree)
    owner = _function_of(tree)
    loop = _loop_of(tree)
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if _is_text_callable(func, aliases, modules):
                found.append(node)
                continue
            if isinstance(func, ast.Attribute) and func.attr in {"astype", "cast"}:
                args = [*node.args, *(k.value for k in node.keywords)]
                if any(_is_text_dtype(a, aliases, modules) for a in args):
                    found.append(node)
                    continue
            passed = [*node.args, *(k.value for k in node.keywords)]
            if any(_is_text_callable(a, aliases, modules) for a in passed):
                found.append(node)
        elif isinstance(node, ast.FormattedValue) and not _is_type_name(node.value):
            found.append(node)
    return sorted(
        {f"{module}::{owner.get(n, '<module>')}::{ast.unparse(n)}{loop.get(n, '')}" for n in found}
    )


def _live() -> list[str]:
    return [
        site
        for rel in SCANNED
        for site in conversions(rel, (SRC / rel).read_text(encoding="utf-8"))
    ]


def test_scanned_modules_convert_cells_only_through_cell_text() -> None:
    assert [site for site in _live() if site not in ALLOWLIST] == []


def test_every_allowlisted_site_still_exists() -> None:
    assert set(ALLOWLIST) - set(_live()) == set(), "stale ALLOWLIST entry (shrink it)"


def test_scanned_modules_read_through_the_shared_rule() -> None:
    """Removing a conversion is not enough: each module still reads columns through cell_text."""
    for rel in SCANNED:
        text = (SRC / rel).read_text(encoding="utf-8")
        assert "from decoy_engine.internal.cell_text import" in text, rel


SEEDED = {
    "astype(str)": "def f(s):\n    return s.astype(str)\n",
    "astype('str')": "def f(s):\n    return s.astype('str')\n",
    "astype('U')": "def f(s):\n    return s.astype('U')\n",
    "astype('string')": "def f(s):\n    return s.astype(dtype='string')\n",
    "astype(np.str_)": "import numpy as np\ndef f(s):\n    return s.astype(np.str_)\n",
    "str(cell)": "def f(v):\n    return str(v)\n",
    "repr(cell)": "def f(v):\n    return repr(v)\n",
    "format(cell)": "def f(v):\n    return format(v)\n",
    "map(str)": "def f(s):\n    return s.map(str)\n",
    "apply(str)": "def f(s):\n    return s.apply(str)\n",
    "list(map(str))": "def f(s):\n    return list(map(str, s))\n",
    "assigned alias": "S = str\nT = S\ndef f(v):\n    return T(v)\n",
    "imported alias": "from builtins import str as S\ndef f(v):\n    return S(v)\n",
    "module-qualified": "import builtins as b\ndef f(v):\n    return b.str(v)\n",
    "numpy alias": "from numpy import str_ as S\ndef f(s):\n    return s.astype(S)\n",
    "f-string": "def f(v):\n    return f'{v}'\n",
    "pyarrow cast": "import pyarrow as pa\ndef f(a):\n    return a.cast('string')\n",
    "pyarrow type": "import pyarrow as pa\ndef f(a):\n    return a.cast(pa.string())\n",
    "pandas dtype": "import pandas as pd\ndef f(s):\n    return s.astype(pd.StringDtype())\n",
}


def test_each_seeded_conversion_is_caught() -> None:
    missed = [name for name, text in SEEDED.items() if not conversions("m.py", text)]
    assert missed == []


def test_value_free_text_is_not_a_conversion() -> None:
    clean = (
        "from decoy_engine.internal.cell_text import column_text\n"
        "def f(s, exc):\n"
        "    t = column_text(s)\n"
        "    return t, f'raised {type(exc).__name__}', s.astype(object), s.astype('uint8')\n"
    )
    assert conversions("m.py", clean) == []


def test_sites_are_keyed_by_function() -> None:
    assert conversions("m.py", SEEDED["str(cell)"]) == ["m.py::f::str(v)"]


# The allowlisted spelling `str(c)` in `_frame_table`, but over cells, not column names.
_CELL_LOOPS = {
    "for loop over cells": (
        "def _frame_table(name, frame, other):\n"
        "    for c in frame.iloc[:, 0]:\n"
        "        yield str(c)\n"
    ),
    "comprehension over cells": (
        "def _frame_table(name, frame, other):\n    return [str(c) for c in frame.iloc[:, 0]]\n"
    ),
    "no loop": "def _frame_table(name, frame, other):\n    c = frame.iloc[0, 0]\n    return str(c)\n",
    "inner loop over cells": (
        "def _frame_table(name, frame, other):\n"
        "    for c in frame.columns:\n"
        "        for c in frame[c]:\n"
        "            yield str(c)\n"
    ),
}


def test_an_allowlisted_call_over_cells_is_not_allowed() -> None:
    allowed = {
        name: [site for site in conversions(_RUNNER, text) if site in ALLOWLIST]
        for name, text in _CELL_LOOPS.items()
    }
    assert allowed == {name: [] for name in _CELL_LOOPS}
    assert all(conversions(_RUNNER, text) for text in _CELL_LOOPS.values())
