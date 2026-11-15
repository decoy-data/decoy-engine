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


# The only places a format value may go: the table lookup, and an error message.
ALLOWED_SINKS = frozenset({"file_format", "repr", "shown"})
SEED_NAMES = frozenset({"fmt", "format", "file_fmt"})


def _is_format_read(node: ast.AST) -> bool:
    """`x.get("format")`, `x["format"]` or `getattr(x, "format")`."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "get":
            return any(isinstance(a, ast.Constant) and a.value == "format" for a in node.args)
        if isinstance(func, ast.Name) and func.id == "getattr":
            return any(isinstance(a, ast.Constant) and a.value == "format" for a in node.args[1:])
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value == "format"
    return False


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


def _names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _holds_format(node: ast.AST, tainted: set[str]) -> bool:
    """Whether `node` carries the format value. The table lookup and a message do not: what
    they return is a table entry or text, not the format."""
    if isinstance(node, ast.Call) and _call_name(node) in ALLOWED_SINKS:
        return False
    if _is_format_read(node) or (isinstance(node, ast.Name) and node.id in tainted):
        return True
    return any(_holds_format(child, tainted) for child in ast.iter_child_nodes(node))


def _tainted(func: ast.FunctionDef) -> set[str]:
    """Names that hold the format: seed names and every alias of one, to a fixed point."""
    tainted = set(SEED_NAMES)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(func):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            holds = _holds_format(value, tainted)
            if holds:
                for target in targets:
                    for name in _names_in(target):
                        if name not in tainted:
                            tainted.add(name)
                            changed = True
    return tainted


def format_branches(func: ast.FunctionDef) -> list[str]:
    """Format names used as literals, and any use of the format value (or an alias of it)
    other than aliasing it, passing it to the table lookup or naming it in a message.
    That covers comparisons, `match`, `in`, `getattr`, name building and another dict."""
    found: list[str] = []
    tainted = _tainted(func)
    parents = {child: parent for parent in ast.walk(func) for child in ast.iter_child_nodes(parent)}
    for node in ast.walk(func):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in FORMATS:
            found.append(f"literal {node.value!r}@{node.lineno}")
        is_use = (isinstance(node, ast.Name) and node.id in tainted) or _is_format_read(node)
        if not is_use:
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Assign | ast.AnnAssign | ast.NamedExpr) and node is parent.value:
            continue
        if (
            isinstance(parent, ast.Call)
            and node in parent.args
            and _call_name(parent) in ALLOWED_SINKS
        ):
            continue
        found.append(f"{type(parent).__name__.lower()}@{node.lineno}")
    return found


def module_format_tables(tree: ast.Module) -> list[int]:
    """Lines of a dict, set, tuple or list literal that names a format, other than the one
    `FILE_FORMATS` assignment. A second table of formats is a second dispatch."""
    skip: set[int] = set()
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
        if any(isinstance(t, ast.Name) and t.id == "FILE_FORMATS" for t in targets):
            skip.update(id(n) for n in ast.walk(node))
    lines: list[int] = []
    for node in ast.walk(tree):
        if id(node) in skip or not isinstance(node, ast.Dict | ast.Set | ast.Tuple | ast.List):
            continue
        elements = node.keys if isinstance(node, ast.Dict) else node.elts
        if any(
            isinstance(e, ast.Constant) and isinstance(e.value, str) and e.value in FORMATS
            for e in elements
            if e is not None
        ):
            lines.append(node.lineno)
    return lines


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


def test_the_approved_table_lookup_is_not_a_branch() -> None:
    source = 'def f(d):\n    fmt = d.get("format")\n    return file_format(fmt)\n'
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
