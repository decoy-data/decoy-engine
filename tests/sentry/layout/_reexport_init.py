"""The one physical-import scanner of the seam sentry.

`imports_physical` resolves relative imports to absolute names, so `from .physical import x` is
the same finding as the absolute form.
"""

from __future__ import annotations

import ast
from pathlib import Path

SEAM = "decoy_engine.execution.physical"


def _in_seam(name: str) -> bool:
    return name == SEAM or name.startswith(SEAM + ".")


def _str_arg(call: ast.Call, index: int, keyword: str) -> str | None:
    """The literal string passed positionally at `index` or as `keyword`; None if built up."""
    node = call.args[index] if len(call.args) > index else None
    for kw in call.keywords:
        if kw.arg == keyword:
            node = kw.value
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _dynamic_names(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Local names bound to the importlib module and to `import_module`, any alias."""
    modules, funcs = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "importlib":
                    modules.add(a.asname or "importlib")
                elif a.name.startswith("importlib.") and not a.asname:
                    modules.add("importlib")
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib" and not node.level:
            funcs |= {a.asname or a.name for a in node.names if a.name == "import_module"}
    return modules, funcs


def _dynamic_import_hits_seam(call: ast.Call, modules: set[str], funcs: set[str]) -> bool:
    fn = call.func
    if isinstance(fn, ast.Name) and fn.id == "__import__":
        name = _str_arg(call, 0, "name") or ""
        names = [name]
        fromlist = call.args[3] if len(call.args) > 3 else None
        for kw in call.keywords:
            if kw.arg == "fromlist":
                fromlist = kw.value
        if isinstance(fromlist, (ast.List, ast.Tuple)):
            names += [
                f"{name}.{e.value}"
                for e in fromlist.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
        return any(_in_seam(n) for n in names)
    is_import_module = (isinstance(fn, ast.Name) and fn.id in funcs) or (
        isinstance(fn, ast.Attribute)
        and fn.attr == "import_module"
        and isinstance(fn.value, ast.Name)
        and fn.value.id in modules
    )
    if not is_import_module:
        return False
    name = _str_arg(call, 0, "name")
    if name is None:
        return False
    if name.startswith("."):
        package = _str_arg(call, 1, "package")
        if package is None:
            return False
        level = len(name) - len(name.lstrip("."))
        pkg = package.split(".")
        name = ".".join([*pkg[: len(pkg) - (level - 1)], name[level:]]).rstrip(".")
    return _in_seam(name)


def imports_physical(path: Path, engine_root: Path) -> bool:
    """Whether the file imports `decoy_engine.execution.physical`, by any spelling.

    Absolute and relative `from` imports, `import x.y`, and `from pkg import physical` all count,
    at any indent, and so do `importlib.import_module(...)` (any alias of importlib or of
    import_module) and `__import__(...)` calls whose name is a string literal. A name built up at
    run time is not seen (hostile code is outside the V1 threat model; V2-LOG). `engine_root` is `src/decoy_engine`; it fixes the package a relative import
    starts from. A file that does not parse and mentions `physical` counts (fails closed)."""
    text = path.read_text(encoding="utf-8")
    if "physical" not in text:
        return False
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return True
    parts = ["decoy_engine", *path.relative_to(engine_root).parts[:-1]]
    modules, funcs = _dynamic_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if _dynamic_import_hits_seam(node, modules, funcs):
                return True
        elif isinstance(node, ast.Import):
            if any(_in_seam(a.name) for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = parts[: len(parts) - (node.level - 1)]
                module = ".".join([*base, *(node.module.split(".") if node.module else [])])
            else:
                module = node.module or ""
            if _in_seam(module) or any(_in_seam(f"{module}.{a.name}") for a in node.names):
                return True
    return False
