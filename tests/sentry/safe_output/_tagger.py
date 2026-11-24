"""The one AST name tagger for the outbound-text sentries.

It answers one question about an expression: which names does it expose as text, such as a
raw exception, a data value, a user expression or child-process output? The log-interpolation
sentry uses it today, and the F31 safe-output sentries and the copy ratchet read the same
tagger, so a rule about what counts as risky is one edit here.

Bounded on purpose: names and plain formatting forms, a single scope, one pass over plain
assignments, no cross-function flow. A false positive costs one reasoned allowlist entry; a
value reached through a name this tagger does not tag is the residual risk.
"""

from __future__ import annotations

import ast

# Variable names that hold exceptions, data values or user expressions by convention.
RISKY_NAMES = frozenset(
    {
        "exc",
        "e",
        "err",
        "error",
        "ex",
        "value",
        "v",
        "val",
        "values",
        "cell",
        "row",
        "expression",
        "expr",
        "formula",
        "text",
        "data",
        "sample",
        "raw",
        "record",
        "item",
        "line",
        "content",
        # Geographic quasi-identifiers taken straight from rows (HIPAA Safe Harbor zip3/zip5).
        # Exact names, not a `zip*` wildcard, so unrelated identifiers stay clean.
        "z3",
        "z5",
        "zip3",
        "zip5",
        "zipcode",
        "prefix",
    }
)
# Names that hold child-process output. Only the error sinks treat them as risky, because
# `stderr`/`stdout` are routine, harmless names in code that does not build a user-facing error.
SINK_RISKY = RISKY_NAMES | {"stderr", "stdout"}

COUNT_METHODS = frozenset({"count", "nunique", "sum", "size", "__len__"})


def root_name(value: ast.expr) -> str | None:
    """The variable an expression reads through attributes and subscripts; None if a call
    sits on the path (`type(exc).__name__` reads the type, not the exception)."""
    while isinstance(value, (ast.Attribute, ast.Subscript)):
        if isinstance(value, ast.Attribute) and value.attr == "__class__":
            return None  # exc.__class__.__name__ is the type, like type(exc).__name__
        value = value.value
    return value.id if isinstance(value, ast.Name) else None


def risky_in(value: ast.expr, risky: frozenset[str]) -> list[str]:
    """Every risky name `value` exposes as text, directly or through formatting. All of them
    count, so adding a second risky value to an allowlisted message is still a new finding."""
    if isinstance(value, (ast.Name, ast.Attribute, ast.Subscript)):
        root = root_name(value)
        if root is not None:
            return [root] if root in risky else []
        base: ast.expr = value
        while isinstance(base, (ast.Attribute, ast.Subscript)):
            base = base.value
        # `str(exc)[:200]` still exposes the text; `type(exc).__name__` stays exempt because
        # `type` is not a formatting call.
        # A sliced f-string (`f"{exc}"[:500]`) exposes the same text as the f-string itself.
        return risky_in(base, risky) if not isinstance(base, ast.Name) else []
    children: list[ast.expr] = []
    if isinstance(value, ast.JoinedStr):
        children = [p.value for p in value.values if isinstance(p, ast.FormattedValue)]
    elif isinstance(value, ast.BinOp):
        children = [value.left, value.right]
    elif isinstance(value, ast.Starred):
        children = [value.value]
    elif isinstance(value, ast.BoolOp):
        children = list(value.values)
    elif isinstance(value, ast.IfExp):
        children = [value.body, value.orelse]
    elif isinstance(value, ast.Dict):
        # Logging renders a dict's keys as well as its values.
        children = [k for k in value.keys if k is not None] + list(value.values)
    elif isinstance(value, ast.DictComp):
        children = [value.key, value.value, *(g.iter for g in value.generators)]
    elif isinstance(value, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
        # The iterable counts too: conservative on purpose, since a false positive only costs
        # an allowlist entry while `", ".join(str(x) for x in row)` must not pass.
        children = [value.elt, *(g.iter for g in value.generators)]
    elif isinstance(value, (ast.Tuple, ast.List, ast.Set)):
        children = list(value.elts)
    elif isinstance(value, ast.Call):
        func = value.func
        if (isinstance(func, ast.Name) and func.id in {"str", "repr", "format"}) or (
            isinstance(func, ast.Attribute) and func.attr in {"format", "join"}
        ):
            children = [*value.args, *(k.value for k in value.keywords)]
        elif isinstance(func, ast.Name) and func.id == "scrub_error_text":
            # Returns the message with only the Arrow cell pattern removed: still the message.
            children = list(value.args)
        elif isinstance(func, ast.Attribute):
            if func.attr in COUNT_METHODS:
                return []  # `row.count()`, `values.nunique()` log a number, not the data
            # A method on a risky value (`row.items()`, `str(exc).strip()`) still exposes it.
            root = root_name(func.value)
            if root is not None:
                return [root] if root in risky else []
            return risky_in(func.value, risky)
    return [hit for child in children for hit in risky_in(child, risky)]


def own_nodes(scope: ast.AST) -> list[ast.AST]:
    """Nodes that belong to `scope` itself: nested defs and classes appear but are not entered."""
    own: list[ast.AST] = []
    pending = list(ast.iter_child_nodes(scope))
    while pending:
        node = pending.pop()
        own.append(node)
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            pending.extend(ast.iter_child_nodes(node))
    return own


def tainted_names(own: list[ast.AST], risky: frozenset[str]) -> frozenset[str]:
    """Names assigned from a risky expression, in source order, one pass.

    Bounded on purpose: a single scope, plain `name = expr` / `name += expr` assignments, no
    loops to a fixpoint, no cross-function flow. It is enough to follow
    `stderr_tail = stderr.strip()...` into the `error=` that uses `stderr_tail`, which an
    expression-only check cannot see because `stderr_tail` is not a risky name.
    """
    tainted: set[str] = set()
    assigns = sorted(
        (n for n in own if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign))),
        key=lambda n: (n.lineno, n.col_offset),
    )
    for node in assigns:
        if node.value is None:
            continue
        if risky_in(node.value, risky | tainted):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            tainted |= {t.id for t in targets if isinstance(t, ast.Name)}
    return frozenset(tainted)
