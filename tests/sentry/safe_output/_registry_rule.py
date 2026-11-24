"""The rule that admits a project exception class to the value-free message registry.

A class is admitted when every raise of it, direct or through a factory function, passes no
exception or data-value name into its message and sits in no function that copies exception
text. The registry in `safe_output/_render.py` is seeded from this rule and the registry sentry
re-runs it on every test run, so a later raise that interpolates a value drops the class.

Same rule as the F31 audit's `registry_share.py`, on the shared tagger. It follows one factory
level (`raise _refuse(...)` counts as a raise of the class `_refuse` returns).
"""

from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tests.sentry.safe_output._exc_copies import copy_lines
from tests.sentry.safe_output._scopes import exposes, iter_scopes
from tests.sentry.safe_output._tagger import risky_in

CODE_KW = frozenset({"code", "reason"})
_SKIP_KW = frozenset({"exc_info", "stacklevel", "extra", "category"})


@dataclass(frozen=True)
class Admission:
    classes: Mapping[str, tuple[str, ...]]  # simple name -> dotted names defined in the sources
    bad: frozenset[str]  # a raise carries a value or sits beside an exception-text copy
    # Raised at least once without a reason code. Feeds the plan's share table only; admission
    # to the registry never reads it.
    uncoded: frozenset[str]

    @property
    def clean(self) -> frozenset[str]:
        return frozenset(self.classes) - self.bad


def read_sources(root: Path) -> dict[str, str]:
    """Dotted module name to source for every module under `root` (a package directory)."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = [root.name, *path.relative_to(root).with_suffix("").parts]
        if parts[-1] == "__init__":
            parts.pop()
        out[".".join(parts)] = path.read_text(encoding="utf-8")
    return out


def _callee(call: ast.Call) -> str:
    return ast.unparse(call.func).split(".")[-1]


def _passes_code(call: ast.Call) -> bool:
    if any(k.arg in CODE_KW for k in call.keywords):
        return True
    for arg in call.args:
        text = ast.unparse(arg)
        if text.startswith("reasons.") or text.split(".")[-1].endswith("CODE"):
            return True
    return False


def _message_exprs(call: ast.Call) -> list[ast.expr]:
    return [*call.args, *(k.value for k in call.keywords if k.arg not in _SKIP_KW)]


def analyze(sources: Mapping[str, str]) -> Admission:
    trees = {module: ast.parse(text) for module, text in sources.items()}
    classes: dict[str, list[str]] = defaultdict(list)
    returns: dict[str, list[ast.Call]] = defaultdict(list)
    takes_code: set[str] = set()
    for module, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes[node.name].append(f"{module}.{node.name}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                if any(
                    a.arg in CODE_KW
                    or (a.annotation is not None and "ReasonCode" in ast.unparse(a.annotation))
                    for a in params
                ):
                    takes_code.add(node.name)
                returns[node.name].extend(
                    sub.value
                    for sub in ast.walk(node)
                    if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Call)
                )

    def owners_of(name: str, seen: frozenset[str] = frozenset()) -> set[str]:
        """Every class a function can return, following factories that return factories."""
        found: set[str] = set()
        for r in returns.get(name, []):
            callee = _callee(r)
            if callee in classes:
                found.add(callee)
            elif callee not in seen and callee in returns:
                found |= owners_of(callee, seen | {name})
        return found

    def resolve(call: ast.Call) -> tuple[set[str], bool]:
        """(the classes the call can build, whether a reason code is passed)."""
        name = _callee(call)
        if name in classes:
            return {name}, _passes_code(call)
        coded = (
            _passes_code(call)
            or any(_passes_code(r) for r in returns.get(name, []))
            or (name in takes_code and bool(call.args or call.keywords))
        )
        return owners_of(name), coded

    bad: set[str] = set()
    uncoded: set[str] = set()
    for tree in trees.values():
        copies = copy_lines(tree)
        raised = {id(n.exc) for n in ast.walk(tree) if isinstance(n, ast.Raise) and n.exc}
        for scope, own, risky in iter_scopes(tree):
            lo = getattr(scope, "lineno", 0)
            hi = getattr(scope, "end_lineno", 10**9) or 10**9
            near_copy = any(lo <= n <= hi for n in copies)
            # Every call in the scope counts, not only `raise Call(...)`: a stored instance, a
            # factory body and a returned instance carry the same text to the same sinks.
            for node in own:
                if not isinstance(node, ast.Call):
                    continue
                exprs = _message_exprs(node)
                if not exprs:
                    continue
                owners, coded = resolve(node)
                if not owners:
                    continue
                if not coded and id(node) in raised:
                    uncoded |= owners
                if near_copy or any(risky_in(e, risky) or exposes(e, risky) for e in exprs):
                    # A call that can build several classes taints all of them: fail closed.
                    bad |= owners
    return Admission(
        classes={k: tuple(v) for k, v in classes.items()},
        bad=frozenset(bad),
        uncoded=frozenset(uncoded),
    )


def special_method_findings(sources: Mapping[str, str], module: str, class_name: str) -> list[str]:
    """`__str__`/`__repr__` returns of one class that expose a risky name (e.g. a raw value)."""
    text = sources.get(module)
    if text is None:
        return []
    tree = ast.parse(text)
    found: list[str] = []
    for node in tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        methods = {
            m.name: m
            for m in node.body
            if isinstance(m, ast.FunctionDef) and m.name in ("__str__", "__repr__")
        }
        for scope, own, risky in iter_scopes(tree):
            if not (isinstance(scope, ast.FunctionDef) and methods.get(scope.name) is scope):
                continue
            for ret in own:
                if isinstance(ret, ast.Return) and ret.value is not None:
                    hits = risky_in(ret.value, risky)
                    if hits or exposes(ret.value, risky):
                        found.append(f"{module}.{class_name}.{scope.name}: {sorted(set(hits))}")
    return found
