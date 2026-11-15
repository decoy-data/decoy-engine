"""AT-E4 guard: the file-format dispatch lives in one table.

`_build_file_source` (resident) and `build_lazy_source` (lazy) both look a format up in
`FILE_FORMATS` in `profile/_lazy_build.py`. A format name or a comparison on the format inside
either function is a second dispatch, so a format added later would have to be edited in two
places. Written before the implementation; do not weaken a check to make it pass.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "decoy_engine" / "profile"
FORMATS = frozenset({"csv", "parquet", "fixed_width"})
BUILDERS = (("_readers.py", "_build_file_source"), ("_lazy_build.py", "build_lazy_source"))


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def _is_format_expr(node: ast.expr) -> bool:
    """`fmt`, `format`, or a `.get("format")` / `["format"]` read."""
    if isinstance(node, ast.Name):
        return node.id in {"fmt", "format", "file_format"}
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
    ):
        return any(isinstance(a, ast.Constant) and a.value == "format" for a in node.args)
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value == "format"
    return False


def format_branches(func: ast.FunctionDef) -> list[str]:
    """Format names used as literals, and comparisons or matches on the format."""
    found: list[str] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in FORMATS:
            found.append(f"literal {node.value!r}@{node.lineno}")
        if isinstance(node, ast.Compare) and any(
            _is_format_expr(n) for n in (node.left, *node.comparators)
        ):
            found.append(f"compare@{node.lineno}")
        if isinstance(node, ast.Match) and _is_format_expr(node.subject):
            found.append(f"match@{node.lineno}")
    return found


def _tree(rel: str) -> ast.Module:
    return ast.parse((SRC / rel).read_text(encoding="utf-8"))


def test_neither_builder_branches_on_format_outside_the_table() -> None:
    for rel, name in BUILDERS:
        assert format_branches(_function(_tree(rel), name)) == [], (rel, name)


def test_the_table_holds_every_format_so_the_guard_is_not_vacuous() -> None:
    text = (SRC / "_lazy_build.py").read_text(encoding="utf-8")
    for name in FORMATS:
        assert f'"{name}"' in text


def _seed(source: str, name: str) -> list[str]:
    return format_branches(_function(ast.parse(source), name))


def test_a_seeded_format_branch_is_seen() -> None:
    cases = [
        'def f(d):\n    fmt = d.get("format")\n    if fmt == "csv":\n        return 1\n',
        'def f(d):\n    if d["format"] in ("a", "b"):\n        return 1\n',
        'def f(d):\n    if d.get("format") != d.get("x"):\n        return 1\n',
        'def f(d):\n    fmt = d.get("format")\n    match fmt:\n        case _:\n            return 1\n',
        'def f(d):\n    return {"parquet": 1}\n',
    ]
    for source in cases:
        assert _seed(source, "f") != [], source


def test_a_table_lookup_is_not_a_branch() -> None:
    source = 'def f(d):\n    fmt = d.get("format")\n    return TABLE.get(fmt)\n'
    assert _seed(source, "f") == []


# Round 2: aliases, getattr and an external dict are dispatch too.
SEEDED_DISPATCH = {
    "alias": (
        'def f(d):\n    fmt = d["format"]\n    other = fmt\n    if other == d["x"]:\n'
        "        return 1\n"
    ),
    "alias_in_tuple": (
        'def f(d, names):\n    kind = d.get("format")\n    if kind in names:\n        return 1\n'
    ),
    "getattr_name": (
        'def f(d, mod):\n    fmt = d.get("format")\n    return getattr(mod, fmt)(d)\n'
    ),
    "getattr_built_name": (
        'def f(d, mod):\n    fmt = d.get("format")\n    return getattr(mod, "_" + fmt)(d)\n'
    ),
    "external_dict_subscript": ('def f(d):\n    fmt = d.get("format")\n    return OTHER[fmt](d)\n'),
    "external_dict_get": ('def f(d):\n    return OTHER.get(d.get("format"))(d)\n'),
}


def test_every_seeded_dispatch_shape_is_seen() -> None:
    for label, source in SEEDED_DISPATCH.items():
        assert _seed(source, "f") != [], label


def test_a_format_keyed_dict_outside_the_table_is_seen() -> None:
    source = 'DISPATCH = {"csv": 1, "parquet": 2}\nFILE_FORMATS = {"csv": 1}\n'
    assert module_format_tables(ast.parse(source)) == [1]


def test_the_two_modules_hold_no_format_keyed_table_but_the_one() -> None:
    for rel, _ in BUILDERS:
        assert module_format_tables(_tree(rel)) == [], rel


def test_the_approved_lookup_helper_is_not_a_branch() -> None:
    source = (
        'def f(d):\n    fmt = d.get("format")\n    entry = file_format(fmt)\n'
        "    return repr(fmt), entry\n"
    )
    assert _seed(source, "f") == []
