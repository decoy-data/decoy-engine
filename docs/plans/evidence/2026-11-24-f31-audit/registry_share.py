"""F31 audit: the share of raise sites that keep their message under the value-free registry.

Usage: python3 registry_share.py <engine src root> <copies.tsv> <out.tsv>

A project class (defined under the src root) is admitted to the value-free message registry when
every raise of it (a) has no EXC or VALUE tag in its message arguments (censuslib tagger) and
(b) sits in a function with no exception-text copy (copies.tsv). Stdlib and third-party classes
are never admitted. Output: one row per raise site with class, admitted (y/n) and reason.
"""

from __future__ import annotations

import ast
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from censuslib import classify_expr, message_args

root = Path(sys.argv[1])
copy_lines: dict[str, set[int]] = defaultdict(set)
for line in Path(sys.argv[2]).read_text().splitlines()[1:]:
    rel, lineno, *_ = line.split("\t")
    copy_lines[rel].add(int(lineno))

project: set[str] = set()
sites = []
for path in sorted(root.rglob("*.py")):
    if "__pycache__" in path.parts:
        continue
    rel = str(path.relative_to(root))
    tree = ast.parse(path.read_text("utf-8"))
    project |= {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}

    def visit(node, bound, func_span):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_span = (node.lineno, node.end_lineno)
        if isinstance(node, ast.ExceptHandler) and node.name:
            bound = bound | {node.name}
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            args = message_args(node.exc)
            if args:
                tags = set()
                for arg in args:
                    tags |= classify_expr(arg, bound)
                lo, hi = func_span or (0, 10**9)
                copy_in_func = any(lo <= n <= hi for n in copy_lines.get(rel, ()))
                cls = ast.unparse(node.exc.func).split(".")[-1]
                sites.append((rel, node.lineno, cls, bool(tags & {"EXC", "VALUE"}), copy_in_func))
        for child in ast.iter_child_nodes(node):
            visit(child, bound, func_span)

    visit(tree, set(), None)

bad = {s[2] for s in sites if s[3] or s[4]}
rows = []
for rel, lineno, cls, tainted, copy in sites:
    if cls not in project:
        why, ok = "not a project class", False
    elif cls in bad:
        why, ok = "a raise of this class is tagged or near a copy", False
    else:
        why, ok = "admitted", True
    rows.append((rel, lineno, cls, "y" if ok else "n", why))
with open(sys.argv[3], "w") as out:
    out.write("file\tline\tclass\tadmitted\treason\n")
    for row in rows:
        out.write("\t".join(map(str, row)) + "\n")
total = len(rows)
kept = sum(r[3] == "y" for r in rows)
print("raise sites with a message", total)
print("keep message (admitted)", kept, f"{kept / total:.1%}")
print("by reason", dict(Counter(r[4] for r in rows)))
print(
    "project classes admitted",
    len({r[2] for r in rows if r[3] == "y"}),
    "of",
    len({r[2] for r in rows if r[2] in project}),
)
print(
    "top excluded project classes",
    Counter(r[2] for r in rows if r[4].startswith("a raise")).most_common(12),
)
