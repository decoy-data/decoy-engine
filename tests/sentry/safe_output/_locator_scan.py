"""The rules of the locator single-copy sentry (LOCATOR-CREDS section 5).

`decoy_engine/_locator.py` is the one place that parses `://`, `//`, `@` or URL userinfo out of
a locator. This walk flags the spellings a contributor writes by habit; it is a tripwire, not a
proof (deliberate evasion with `eval`, `getattr` on built strings or `codecs` is V2-LOG):

1. a regex call whose pattern holds a marker, also inside a character class; the pattern may be
   a literal, a module-level `str` constant, or a concatenation or f-string of these;
2. a marker used as text: the text argument of a split, find, strip-like or starts-with call
   (bound, or unbound as `str.split(x, "@")`), an operand of `in`, `not in`, `==` or `!=`, or an
   element of a tuple, set or list literal;
3. an attribute read of `.netloc`, `.username`, `.password` or `.hostname`;
4. a call to `urlsplit`, `urlparse`, or a urllib3, yarl, furl or rfc3986 URL constructor.

Keys are `<file under decoy_engine>::<qualname>::<rule>`; output names sites, never text.
Import aliases come from `tests/sentry/_call_resolution.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.sentry._call_resolution import local_names

MARKERS = ("://", ":/", ":\\", "//", "\\\\", "@")
EXEMPT = "_locator.py"
_REGEX_FUNCS = frozenset(
    {"compile", "match", "search", "fullmatch", "sub", "subn", "findall", "finditer", "split"}
)
_TEXT_METHODS = frozenset(
    {
        "split",
        "rsplit",
        "partition",
        "rpartition",
        "find",
        "rfind",
        "index",
        "rindex",
        "startswith",
        "endswith",
        "count",
        "replace",
    }
)
_URL_ATTRS = frozenset({"netloc", "username", "password", "hostname"})
_URL_PARSERS = ("urlsplit", "urlparse")
_URL_LIBS = frozenset({"urllib3", "yarl", "furl", "rfc3986"})


def _text(node: ast.AST, consts: dict[str, str]) -> str:
    """The literal text of an expression: constants, module constants, `+` and f-strings."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id, "")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _text(node.left, consts) + _text(node.right, consts)
    if isinstance(node, ast.JoinedStr):
        return "".join(
            _text(v.value if isinstance(v, ast.FormattedValue) else v, consts) for v in node.values
        )
    return ""


def _constants(tree: ast.Module) -> dict[str, str]:
    consts: dict[str, str] = {}
    for _ in range(3):  # a constant built from an earlier constant
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    text = _text(node.value, consts)
                    if text:
                        consts[target.id] = text
    return consts


# In a pattern a literal backslash is written `\\`, so `:\` alone is a colon before a class such as
# `\d`; the escaped pair already covers the "colon, backslash" marker there.
REGEX_MARKERS = tuple(m for m in MARKERS if m != ":\\")


def _has_marker(text: str, markers: tuple[str, ...] = MARKERS) -> bool:
    return any(m in text for m in markers)


class _Visitor(ast.NodeVisitor):
    def __init__(self, tree: ast.Module) -> None:
        self.consts = _constants(tree)
        self.scope: list[str] = []
        self.found: set[tuple[str, str]] = set()
        self.url_calls = {n for t in _URL_PARSERS for n in local_names(tree, t)}
        self.lib_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in _URL_LIBS:
                self.lib_names.update(a.asname or a.name for a in node.names)
            elif isinstance(node, ast.Import):
                self.lib_names.update(
                    a.asname or a.name.split(".")[0]
                    for a in node.names
                    if a.name.split(".")[0] in _URL_LIBS
                )
        self.regex_names = {n for t in _REGEX_FUNCS for n in local_names(tree, t)}

    def _hit(self, rule: str) -> None:
        self.found.add((".".join(self.scope) or "<module>", rule))

    def _scoped(self, node: ast.AST, name: str) -> None:
        self.scope.append(name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scoped(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scoped(node, node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scoped(node, node.name)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _URL_ATTRS and isinstance(node.ctx, ast.Load):
            self._hit("url-attr")
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        if any(isinstance(op, (ast.In, ast.NotIn, ast.Eq, ast.NotEq)) for op in node.ops):
            for operand in (node.left, *node.comparators):
                if _has_marker(_text(operand, self.consts)):
                    self._hit("marker-compare")
        self.generic_visit(node)

    def _literal(self, node: ast.Tuple | ast.Set | ast.List) -> None:
        if any(_has_marker(_text(e, self.consts)) for e in node.elts):
            self._hit("marker-literal")
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        self._literal(node)

    def visit_Set(self, node: ast.Set) -> None:
        self._literal(node)

    def visit_List(self, node: ast.List) -> None:
        self._literal(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in self.url_calls or (
            (isinstance(func, ast.Name) and func.id in self.lib_names)
            or (isinstance(func, ast.Attribute) and _root_name(func) in self.lib_names)
        ):
            self._hit("url-call")
        is_regex = (isinstance(func, ast.Name) and func.id in self.regex_names) or (
            isinstance(func, ast.Attribute) and func.attr in _REGEX_FUNCS
        )
        if is_regex and node.args and _has_marker(_text(node.args[0], self.consts), REGEX_MARKERS):
            self._hit("regex")
        if isinstance(func, ast.Attribute) and func.attr in _TEXT_METHODS and node.args:
            unbound = isinstance(func.value, ast.Name) and func.value.id == "str"
            idx = 1 if unbound else 0
            if len(node.args) > idx and _has_marker(_text(node.args[idx], self.consts)):
                self._hit("marker-call")
        self.generic_visit(node)


def _root_name(node: ast.Attribute) -> str:
    base: ast.expr = node
    while isinstance(base, ast.Attribute):
        base = base.value
    return base.id if isinstance(base, ast.Name) else ""


def scan_source(source: str, rel: str) -> set[str]:
    """Baseline keys for one module's text (`rel` is its path under `decoy_engine`)."""
    visitor = _Visitor(tree := ast.parse(source))
    visitor.visit(tree)
    return {f"{rel}::{scope}::{rule}" for scope, rule in visitor.found}


def scan_tree(root: Path) -> set[str]:
    keys: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel == EXEMPT:
            continue
        keys |= scan_source(path.read_text(encoding="utf-8"), rel)
    return keys
