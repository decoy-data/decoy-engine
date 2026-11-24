"""F31 audit: what each raise site prints under the AE1 renderer.

Usage: python3 registry_share.py <engine src root> <copies.tsv> <out.tsv>

Each raise site with a message gets one outcome:

- coded: the raise passes `code=` or `reason=`, or a `reasons.` attribute or a name ending in
  `CODE` as an argument, or it calls a factory that takes a `code`/`reason` (or `ReasonCode`)
  parameter, or whose returned call passes `code=`/`reason=`.
  The renderer prints the registry summary plus refs.
- admitted: an uncoded project class (direct, or the class a factory returns) whose every raise
  has no EXC or VALUE tag (censuslib tagger) and sits in no function with an exception-text copy
  (copies.tsv). The renderer prints its message.
- label: anything else (stdlib and third-party classes, excluded project classes, factories that
  cannot be resolved). The renderer prints the type label.

A factory is a raise whose callee is a function, not a class: `raise violation(...)`,
`raise _refuse(...)`, `raise Error.from_exception_data(...)`. It is followed to the calls its
`return` statements make. Output columns: file, line, callee, resolved class, outcome, route.
"""

from __future__ import annotations

import ast
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from censuslib import classify_expr, message_args  # noqa: E402

CODE_KW = {"code", "reason"}


def callee(call: ast.Call) -> str:
    return ast.unparse(call.func).split(".")[-1]


def passes_code(call: ast.Call) -> bool:
    if any(k.arg in CODE_KW for k in call.keywords):
        return True
    for arg in call.args:
        text = ast.unparse(arg)
        if text.startswith("reasons.") or text.split(".")[-1].endswith("CODE"):
            return True
    return False


root = Path(sys.argv[1])
copy_lines: dict[str, set[int]] = defaultdict(set)
for line in Path(sys.argv[2]).read_text().splitlines()[1:]:
    rel, lineno, *_ = line.split("\t")
    copy_lines[rel].add(int(lineno))

project: set[str] = set()
factory_returns: dict[str, list[ast.Call]] = defaultdict(list)
factory_takes_code: set[str] = set()
sites = []
for path in sorted(root.rglob("*.py")):
    if "__pycache__" in path.parts:
        continue
    rel = str(path.relative_to(root))
    tree = ast.parse(path.read_text("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            project.add(node.name)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            if any(
                a.arg in CODE_KW
                or (a.annotation is not None and "ReasonCode" in ast.unparse(a.annotation))
                for a in params
            ):
                factory_takes_code.add(node.name)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Call):
                    factory_returns[node.name].append(sub.value)

    def visit(node, bound, span):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            span = (node.lineno, node.end_lineno)
        if isinstance(node, ast.ExceptHandler) and node.name:
            bound = bound | {node.name}
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            call = node.exc
            args = message_args(call) or call.args
            if args or call.keywords:
                tags = set()
                for arg in [*args, *(k.value for k in call.keywords)]:
                    tags |= classify_expr(arg, bound)
                lo, hi = span or (0, 10**9)
                near_copy = any(lo <= n <= hi for n in copy_lines.get(rel, ()))
                sites.append((rel, node.lineno, call, tags & {"EXC", "VALUE"}, near_copy))
        for child in ast.iter_child_nodes(node):
            visit(child, bound, span)

    visit(tree, set(), None)


def resolve(call: ast.Call) -> tuple[str, bool, str]:
    """(class name, coded, route) for a raise call; follows one factory level."""
    name = callee(call)
    if name in project or name[:1].isupper():
        return name, passes_code(call), "direct"
    returned = factory_returns.get(name, [])
    coded = (
        passes_code(call)
        or any(passes_code(r) for r in returned)
        or (name in factory_takes_code and bool(call.args or call.keywords))
    )
    classes = {callee(r) for r in returned if callee(r) in project}
    if coded:
        return (sorted(classes)[0] if classes else name), True, "factory"
    if len(classes) == 1:
        return classes.pop(), False, "factory"
    return name, False, "factory-unresolved"


resolved = [
    (rel, line, call, tainted, near, *resolve(call)) for rel, line, call, tainted, near in sites
]
bad = {
    cls
    for *_, tainted, near, cls, coded, route in [
        (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in resolved
    ]
    if tainted or near
}
rows = []
for rel, line, call, _tainted, _near, cls, coded, route in resolved:
    if coded:
        outcome = "coded"
    elif cls in project and cls not in bad:
        outcome = "admitted"
    else:
        outcome = "label"
    rows.append((rel, line, callee(call), cls, outcome, route))
with open(sys.argv[3], "w") as out:
    out.write("file\tline\tcallee\tclass\toutcome\troute\n")
    for row in rows:
        out.write("\t".join(map(str, row)) + "\n")
total = len(rows)
tally = Counter(r[4] for r in rows)
print("raise sites with a message", total)
for key in ("coded", "admitted", "label"):
    print(f"  {key}: {tally[key]} ({tally[key] / total:.1%})")
print("by route and outcome", dict(Counter((r[5], r[4]) for r in rows)))
label = [r for r in rows if r[4] == "label"]
print(
    "label: project classes",
    sum(r[3] in project for r in label),
    "other",
    sum(r[3] not in project for r in label),
)
print(
    "admitted classes",
    len({r[3] for r in rows if r[4] == "admitted"}),
    "of",
    len({r[3] for r in rows if r[3] in project}),
)
print("top label classes", Counter(r[3] for r in label).most_common(10))
