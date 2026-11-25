"""The scanner behind the config refusal text sentry (F31 AE5).

It reads Python source and reports where a refusal is built outside `config_refusal`. Rules:

- S1: every construction of a refusal class takes its message and `path` from builder output
  (a `Refusal` bound once, or a parameter annotated `Refusal`). In the zero set it also covers a
  builtin error's message.
- S2: every `config_refusal` call, wherever it is, passes only closed arguments.
- S3 (zero set): no raise inside an `except` body, no `raise ... from`, every refusal raise goes
  through `raise_bare`.
- S4 (zero set): a handler uses its exception only for type checks, the fileaccess
  classification calls and a short list of typed uses.
- S6 (zero set): a materializer call runs only inside the `read=` operation of `read_config`.
- R: a function outside `_error_base.py` that sets `__context__ = None` and re-raises.

The scan is bounded on purpose: one function scope at a time, plain assignments, no flow across
calls except the S6 helper rule. A finding names a rule, file, function and a digest of the
offending arguments, never their text.
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# The AE5 loader modules, plus the files split out of them (the corpus checks, the withheld-values
# refusal and the provenance record types).
ZERO_SET = frozenset(
    {
        "detection/name_hints/loader.py",
        "plan/_generation.py",
        "transforms/joint_mask.py",
        "transforms/_codeset_config_checks.py",
        "transforms/_codeset_checks.py",
        "transforms/_codeset_loader.py",
        "generation/statistical/_spec.py",
        "generation/statistical/_snapshot_io.py",
        "generation/statistical/_spec_refusals.py",
        "reference_tables/_loader.py",
        "profiling/model_pack/loader.py",
        "quality/dp_provenance.py",
        "quality/_dp_record.py",
    }
)
# The one function allowed to rebuild a refusal from the text it already held (a pickle round trip).
S1_EXEMPT = frozenset({("profiling/model_pack/loader.py", "_rebuild_load_error")})
CONFIG_TEXT_DIR = "_config_text/"
ERROR_BASE = "_error_base.py"
# The one engine-owned fixed text a zero-set builtin error may take besides a literal.
FIXED_TEXT_ATTR = "MEMORY_TEXT"
# Functions whose declared result is a `Refusal` built by `config_refusal`.
REFUSAL_FACTORIES = frozenset({"statistical_refusal"})


@dataclass(frozen=True)
class Sig:
    """Where a refusal class takes its message and path, and which `Refusal` field each uses."""

    message: tuple[int, str]
    message_field: str
    path: tuple[int, str] | None = None


_TEXT = Sig((0, "message"), "text")
SIGNATURES: dict[str, Sig] = {
    "PlanCompileError": Sig((2, "message"), "detail", (1, "path")),
    "PipelineValidationError": Sig((0, "message"), "text", (1, "path")),
    "ConfigRuleError": _TEXT,
    "ConfigError": _TEXT,
    "NameHintLoaderError": _TEXT,
    "ModelPackLoadError": _TEXT,
    "ProvenanceError": _TEXT,
    "StatisticalSpecError": _TEXT,
}
MATERIALIZERS_ATTR = frozenset({"as_py", "to_pylist", "to_pydict", "read_table"})
MATERIALIZERS_QUAL = frozenset(
    {
        ("json", "loads"),
        ("json", "load"),
        ("yaml", "safe_load"),
        ("toml_reader", "load"),
        ("tomllib", "load"),
        ("CodeSetProvenance", "from_parquet_metadata"),
        ("joblib", "load"),
    }
)
CLASSIFY_CALLS = frozenset(
    {
        "isinstance",
        "type",
        "safe_error_type",
        "keeps_class",
        "classified_failure",
        "is_memory_failure",
        "typed_memory_member",
    }
)
# (file, function, exception class, field, destination): the only typed uses of a caught error.
S4_ALLOWED = frozenset(
    {
        ("transforms/_codeset_loader.py", "verify_corpus", "PlanCompileError", "code", "problems"),
        (
            "transforms/_codeset_loader.py",
            "verify_corpus",
            "PlanCompileError",
            "message",
            "problems",
        ),
        ("plan/_generation.py", "read_and_pin_snapshots", "StatisticalSpecError", None, "failures"),
        ("plan/_generation.py", "check_fitted_references", "StatisticalSpecError", "code", "code"),
    }
)
_UPPER = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
BUILTIN_ERRORS = frozenset(
    n
    for n in dir(builtins)
    if isinstance(getattr(builtins, n), type) and issubclass(getattr(builtins, n), BaseException)
)


@dataclass(frozen=True)
class Finding:
    rule: str
    file: str
    qualname: str
    digest: str
    line: int = field(default=0, compare=False)

    @property
    def key(self) -> str:
        return f"{self.file}::{self.qualname}::{self.digest}"


def _digest(*nodes: ast.AST | None) -> str:
    text = "|".join(ast.unparse(n) for n in nodes if n is not None)
    return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()[:10]


def _name_of(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


# ---- scope model -----------------------------------------------------------------------------


@dataclass
class Scope:
    qualname: str
    parent: Scope | None
    assigns: dict[str, list[ast.expr]] = field(default_factory=dict)
    refusal_params: set[str] = field(default_factory=set)
    position_params: set[str] = field(default_factory=set)
    index_names: set[str] = field(default_factory=set)

    def chain(self) -> Iterable[Scope]:
        scope: Scope | None = self
        while scope is not None:
            yield scope
            scope = scope.parent

    def lookup(self, name: str) -> tuple[Scope, list[ast.expr]] | None:
        for scope in self.chain():
            if name in scope.assigns:
                return scope, scope.assigns[name]
        return None

    def is_refusal_param(self, name: str) -> bool:
        for scope in self.chain():
            if name in scope.refusal_params:
                return True
            if name in scope.assigns:
                return False
        return False

    def is_index(self, name: str) -> bool:
        return any(name in scope.index_names for scope in self.chain())


def _own_walk(scope_node: ast.AST) -> Iterable[ast.AST]:
    """Nodes of one scope: nested functions, lambdas and classes appear but are not entered."""
    pending = list(ast.iter_child_nodes(scope_node))
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            pending.extend(ast.iter_child_nodes(node))


def _build_scope(node: ast.AST, qualname: str, parent: Scope | None) -> Scope:
    scope = Scope(qualname, parent)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        args = node.args
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            scope.assigns.setdefault(arg.arg, [])
            if _name_of(arg.annotation) == "Refusal":
                scope.refusal_params.add(arg.arg)
            if _name_of(arg.annotation) == "ConfigPosition":
                scope.position_params.add(arg.arg)
    for sub in _own_walk(node):
        if isinstance(sub, ast.Assign):
            for target in sub.targets:
                if isinstance(target, ast.Name):
                    scope.assigns.setdefault(target.id, []).append(sub.value)
        elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
            if sub.value is not None:
                scope.assigns.setdefault(sub.target.id, []).append(sub.value)
        elif isinstance(sub, ast.AugAssign) and isinstance(sub.target, ast.Name):
            # An augmented assignment rebuilds the value: record it as formatted.
            scope.assigns.setdefault(sub.target.id, []).append(
                ast.BinOp(left=sub.target, op=ast.Mod(), right=sub.value)
            )
        elif isinstance(sub, ast.For):
            it = sub.iter
            target = sub.target
            if isinstance(it, ast.Call) and _name_of(it.func) in {"enumerate", "range"}:
                first = target.elts[0] if isinstance(target, ast.Tuple) else target
                if isinstance(first, ast.Name):
                    scope.index_names.add(first.id)
            for t in ast.walk(target):
                if isinstance(t, ast.Name):
                    scope.assigns.setdefault(t.id, []).append(ast.Constant(value=None))
    return scope


# ---- the expression predicates ---------------------------------------------------------------


def _is_call_to(node: ast.AST | None, name: str) -> bool:
    return isinstance(node, ast.Call) and _name_of(node.func) == name


def _is_formatting(node: ast.expr) -> bool:
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return True
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in {"str", "repr", "format", "ascii"}:
            return True
        if isinstance(func, ast.Attribute) and func.attr in {"format", "join"}:
            return True
    return False


def _is_builder(node: ast.expr, scope: Scope, seen: int = 0) -> bool:
    """True when `node` is `Refusal` builder output: a `config_refusal` call, a name bound once
    to one, or a parameter annotated `Refusal`."""
    if isinstance(node, ast.Call) and _name_of(node.func) in {"config_refusal", *REFUSAL_FACTORIES}:
        return True
    if isinstance(node, ast.Name) and seen < 4:
        if scope.is_refusal_param(node.id):
            return True
        found = scope.lookup(node.id)
        if found is not None:
            owner, values = found
            return len(values) == 1 and _is_builder(values[0], owner, seen + 1)
    return False


def _builder_field(node: ast.expr | None, scope: Scope, name: str) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == name and _is_builder(node.value, scope)


def _origin_formats(node: ast.expr, scope: Scope, depth: int = 0) -> bool:
    """True when `node`, or the value a plain name was last copied from, is built by formatting."""
    if _is_formatting(node):
        return True
    root = node
    while isinstance(root, (ast.Attribute, ast.Subscript)):
        root = root.value
    if isinstance(root, ast.Name) and depth < 4:
        found = scope.lookup(root.id)
        if found is not None:
            owner, values = found
            return any(_origin_formats(v, owner, depth + 1) for v in values)
    return False


def _plain_chain(node: ast.expr) -> bool:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        if isinstance(node, ast.Subscript) and any(
            isinstance(n, ast.Call) for n in ast.walk(node.slice)
        ):
            return False
        node = node.value
    return isinstance(node, ast.Name)


def _segment_ok(node: ast.expr, scope: Scope) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (str, int)) and not isinstance(node.value, bool)
    if isinstance(node, ast.Call) and _name_of(node.func) in {"Name", "Member"}:
        if len(node.args) != 1 or node.keywords:
            return False
        arg = node.args[0]
        if _is_str_const(arg):
            return True
        return _plain_chain(arg) and not _origin_formats(arg, scope)
    return isinstance(node, ast.Name) and scope.is_index(node.id)


def _is_position(node: ast.expr, scope: Scope, seen: int = 0) -> bool:
    if isinstance(node, ast.Call) and _name_of(node.func) == "config_position":
        return not node.keywords and all(_segment_ok(a, scope) for a in node.args)
    if isinstance(node, ast.Name) and seen < 4:
        for owner in scope.chain():
            if node.id in owner.position_params:
                return True
            if node.id in owner.assigns:
                values = owner.assigns[node.id]
                return len(values) == 1 and _is_position(values[0], owner, seen + 1)
    return False


def _enum_attr(node: ast.expr, enum: str) -> bool:
    if isinstance(node, ast.IfExp):
        return _enum_attr(node.body, enum) and _enum_attr(node.orelse, enum)
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == enum
    )


def _upper_name(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and bool(_UPPER.match(node.id))


def _names_ok(node: ast.expr, scope: Scope) -> bool:
    if isinstance(node, (ast.Tuple, ast.List)):
        return all(_segment_ok(e, scope) and isinstance(e, ast.Call) for e in node.elts)
    if isinstance(node, ast.Call) and _name_of(node.func) == "tuple" and len(node.args) == 1:
        gen = node.args[0]
        return isinstance(gen, ast.GeneratorExp) and _segment_ok(gen.elt, scope)
    return False


def s2_findings(call: ast.Call, scope: Scope) -> list[str]:
    """Problems with one `config_refusal` call's arguments, as short labels."""
    args = list(call.args)
    if any(isinstance(a, ast.Starred) for a in args) or any(k.arg is None for k in call.keywords):
        return ["unpacked arguments"]
    kw = {k.arg: k.value for k in call.keywords if k.arg}
    out: list[str] = []
    if not args or not _is_position(args[0], scope):
        out.append("position")
    problem = args[1] if len(args) > 1 else kw.get("problem")
    if problem is None or not _enum_attr(problem, "Problem"):
        out.append("problem")
    if len(args) > 2:
        out.append("positional")
    for name, value in kw.items():
        if name == "problem" or name == "got":
            continue
        if name == "expected":
            ok = _enum_attr(value, "Expected")
        elif name == "got_kind":
            ok = _enum_attr(value, "Kind") or _is_call_to(value, "_type_kind")
        elif name == "choices":
            ok = _upper_name(value)
        elif name == "names":
            ok = _names_ok(value, scope)
        elif name == "hint":
            ok = (isinstance(value, ast.Constant) and isinstance(value.value, str)) or _upper_name(
                value
            )
        elif name == "code":
            ok = True  # the builder reads only the registered summary of a code
        else:  # `line`, `column` and anything unknown belong to `read_config` alone
            ok = False
        if not ok:
            out.append(name)
    return out


# ---- class discovery ---------------------------------------------------------------------------


def refusal_classes(sources: Iterable[tuple[str, str]]) -> tuple[dict[str, Sig], list[Finding]]:
    """The refusal classes in `sources` (`(relative path, text)` pairs) with their signatures,
    and a finding for each subclass that has its own `__init__` and no row in `SIGNATURES`."""
    defs: dict[str, tuple[str, list[str], bool]] = {}
    for rel, text in sources:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = [b for b in (_name_of(x) for x in node.bases) if b]
                own_init = any(
                    isinstance(m, ast.FunctionDef) and m.name == "__init__" for m in node.body
                )
                defs.setdefault(node.name, (rel, bases, own_init))
    sigs = dict(SIGNATURES)
    changed = True
    while changed:
        changed = False
        for name, (_rel, bases, _own) in defs.items():
            if name not in sigs:
                parent = next((sigs[b] for b in bases if b in sigs), None)
                if parent is not None:
                    sigs[name] = parent
                    changed = True
    findings = [
        Finding("S1", rel, name, "own-init-no-row")
        for name, (rel, _bases, own) in sorted(defs.items())
        if name in sigs and name not in SIGNATURES and own
    ]
    return sigs, findings


# ---- the scan ----------------------------------------------------------------------------------


def _arg(call: ast.Call, where: tuple[int, str]) -> ast.expr | None:
    idx, name = where
    if len(call.args) > idx and not isinstance(call.args[idx], ast.Starred):
        return call.args[idx]
    return next((k.value for k in call.keywords if k.arg == name), None)


def _is_str_const(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


class _Scanner:
    def __init__(self, rel: str, tree: ast.Module, sigs: dict[str, Sig], zero: bool) -> None:
        self.rel = rel
        self.tree = tree
        self.sigs = sigs
        self.zero = zero
        self.findings: list[Finding] = []
        # unprotected materializer calls, keyed by the function that holds them
        self.helpers: dict[str, list[ast.Call]] = {}
        self.parents: dict[int, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                self.parents[id(child)] = parent

    def add(self, rule: str, scope: Scope, node: ast.AST, *digest_nodes: ast.AST | None) -> None:
        self.findings.append(
            Finding(
                rule,
                self.rel,
                scope.qualname,
                _digest(*digest_nodes) if digest_nodes else _digest(node),
                getattr(node, "lineno", 0),
            )
        )

    def run(self) -> list[Finding]:
        module = _build_scope(self.tree, "<module>", None)
        self._children(self.tree, module, False, False, set(), None)
        return self.findings

    # -- traversal ------------------------------------------------------------------------------

    def _children(
        self,
        node: ast.AST,
        scope: Scope,
        protected: bool,
        in_handler: bool,
        read_fns: set[str],
        handler: ast.ExceptHandler | None,
    ) -> None:
        for child in ast.iter_child_nodes(node):
            self._visit(child, scope, protected, in_handler, read_fns, handler)

    def _read_callables(self, scope_node: ast.AST) -> set[str]:
        """Names of local functions passed as `read=` (first argument) to `read_config`."""
        names: set[str] = set()
        for sub in _own_walk(scope_node):
            if isinstance(sub, ast.Call) and _name_of(sub.func) == "read_config":
                read = _arg(sub, (0, "read"))
                if isinstance(read, ast.Name):
                    names.add(read.id)
        return names

    def _qual(self, scope: Scope, name: str) -> str:
        return name if scope.qualname == "<module>" else f"{scope.qualname}.{name}"

    def _visit(
        self,
        node: ast.AST,
        scope: Scope,
        protected: bool,
        in_handler: bool,
        read_fns: set[str],
        handler: ast.ExceptHandler | None,
    ) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inner = _build_scope(node, self._qual(scope, node.name), scope)
            self._children(
                node,
                inner,
                protected or node.name in read_fns,
                False,
                self._read_callables(node),
                None,
            )
            return
        if isinstance(node, ast.ClassDef):
            inner = _build_scope(node, self._qual(scope, node.name), scope)
            self._children(node, inner, protected, False, set(), None)
            return
        if isinstance(node, ast.Lambda):
            inner = _build_scope(node, f"{scope.qualname}.<lambda>", scope)
            self._visit(node.body, inner, protected or self._is_read_arg(node), False, set(), None)
            return
        if isinstance(node, ast.ExceptHandler):
            self._children(node, scope, protected, True, read_fns, node)
            return
        if isinstance(node, ast.Raise):
            self._raise(node, scope, in_handler)
        elif isinstance(node, ast.Call):
            self._call(node, scope, protected)
        elif isinstance(node, ast.Name) and handler is not None and node.id == handler.name:
            self._s4(node, scope, handler)
        self._children(node, scope, protected, in_handler, read_fns, handler)

    def _is_read_arg(self, lam: ast.Lambda) -> bool:
        parent = self.parents.get(id(lam))
        if isinstance(parent, ast.keyword):
            call = self.parents.get(id(parent))
            return parent.arg == "read" and _is_call_to(call, "read_config")
        return (
            isinstance(parent, ast.Call)
            and _is_call_to(parent, "read_config")
            and bool(parent.args)
            and parent.args[0] is lam
        )

    # -- the rules ------------------------------------------------------------------------------

    def _raise(self, node: ast.Raise, scope: Scope, in_handler: bool) -> None:
        if not self.zero:
            return
        if node.cause is not None:
            self.add("S3", scope, node, node.cause)
        if (in_handler and node.exc is not None) or (
            isinstance(node.exc, ast.Call)
            and _name_of(node.exc.func) in self.sigs
            and (self.rel, scope.qualname.split(".")[-1]) not in S1_EXEMPT
        ):
            self.add("S3", scope, node, node.exc)

    def _call(self, call: ast.Call, scope: Scope, protected: bool) -> None:
        name = _name_of(call.func)
        if name == "config_refusal" and not self.rel.startswith(CONFIG_TEXT_DIR):
            for label in s2_findings(call, scope):
                self.add("S2", scope, call, call, ast.Constant(value=label))
        if name in self.sigs:
            if (self.rel, scope.qualname.split(".")[-1]) not in S1_EXEMPT:
                self._s1_class(call, scope, self.sigs[name or ""])
        elif self.zero and name in BUILTIN_ERRORS and isinstance(call.func, ast.Name):
            self._s1_builtin(call, scope)
        if self.zero:
            self._s6(call, scope, protected)

    def _s1_class(self, call: ast.Call, scope: Scope, sig: Sig) -> None:
        if any(isinstance(a, ast.Starred) for a in call.args) or any(
            k.arg is None for k in call.keywords
        ):
            self.add("S1", scope, call)
            return
        message = _arg(call, sig.message)
        bad = not (_is_str_const(message) or _builder_field(message, scope, sig.message_field))
        path = _arg(call, sig.path) if sig.path else None
        if sig.path is not None:
            bad = bad or not _builder_field(path, scope, "key")
        elif any(k.arg == "path" for k in call.keywords):
            bad = True
        if bad:
            self.add("S1", scope, call, message, path)

    def _s1_builtin(self, call: ast.Call, scope: Scope) -> None:
        if not call.args:
            return
        first = call.args[0]
        fixed = isinstance(first, ast.Attribute) and first.attr == FIXED_TEXT_ATTR
        if not (_is_str_const(first) or fixed or _builder_field(first, scope, "text")):
            self.add("S1", scope, call, first)

    def _s6(self, call: ast.Call, scope: Scope, protected: bool) -> None:
        func = call.func
        if not isinstance(func, ast.Attribute):
            return
        hit = func.attr in MATERIALIZERS_ATTR or (
            isinstance(func.value, ast.Name)
            and (
                (func.value.id, func.attr) in MATERIALIZERS_QUAL
                or (func.value.id == "serial" and func.attr.endswith("_load"))
            )
        )
        if hit and not protected:
            self.helpers.setdefault(scope.qualname.split(".")[-1], []).append(call)

    def _s4(self, name: ast.Name, scope: Scope, handler: ast.ExceptHandler) -> None:
        if not self.zero:
            return
        parent = self.parents.get(id(name))
        if isinstance(parent, ast.Call) and name in parent.args:
            if _name_of(parent.func) in CLASSIFY_CALLS:
                return
        exc_class = _name_of(handler.type)
        func_name = scope.qualname.split(".")[0]
        field_name = (
            parent.attr if isinstance(parent, ast.Attribute) and parent.value is name else None
        )
        for file, qual, cls, allowed_field, dest in S4_ALLOWED:
            if (file, qual, cls, allowed_field) == (self.rel, func_name, exc_class, field_name):
                if self._dest_ok(name, dest):
                    return
        self.add("S4", scope, name, handler.type, ast.Constant(value=field_name))

    def _dest_ok(self, name: ast.Name, dest: str) -> bool:
        node: ast.AST = name
        while id(node) in self.parents:
            node = self.parents[id(node)]
            if dest == "problems" and isinstance(node, ast.keyword) and node.arg == "problems":
                return True
            if dest == "failures" and isinstance(node, ast.Assign):
                return any(
                    isinstance(t, ast.Subscript) and _name_of(t.value) == "failures"
                    for t in node.targets
                )
            if dest == "code" and isinstance(node, (ast.Assign, ast.keyword)):
                return True
            if isinstance(node, (ast.FunctionDef, ast.Lambda)):
                return False
        return False

    # -- S6 helper clearing ------------------------------------------------------------------------

    def site_is_protected(self, node: ast.AST) -> bool:
        """True when `node` sits inside a function or lambda passed as `read=` to `read_config`."""
        cur: ast.AST | None = self.parents.get(id(node))
        while cur is not None:
            if isinstance(cur, ast.Lambda) and self._is_read_arg(cur):
                return True
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)) and self._passed_read(cur):
                return True
            cur = self.parents.get(id(cur))
        return False

    def _passed_read(self, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        for sub in ast.walk(self.tree):
            if isinstance(sub, ast.Call) and _name_of(sub.func) == "read_config":
                read = _arg(sub, (0, "read"))
                if isinstance(read, ast.Name) and read.id == fn.name:
                    return True
        return False


def _copies_of_raise_bare(rel: str, tree: ast.Module) -> list[Finding]:
    """A function outside `_error_base.py` that sets `__context__ = None` and re-raises."""
    if rel.endswith(ERROR_BASE):
        return []
    out: list[Finding] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        clears = any(
            isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Attribute) and t.attr == "__context__" for t in n.targets)
            and isinstance(n.value, ast.Constant)
            and n.value.value is None
            for n in ast.walk(fn)
        )
        reraises = any(isinstance(n, ast.Raise) and n.exc is None for n in ast.walk(fn))
        if clears and reraises:
            out.append(Finding("R", rel, fn.name, _digest(fn), fn.lineno))
    return out


def helper_findings(texts: dict[str, str], sigs: dict[str, Sig]) -> list[Finding]:
    """S6: an unprotected materializer call is allowed only when every call site of its function,
    in the zero set, is itself inside a protected operation or inside another cleared helper."""
    scanners: dict[str, _Scanner] = {}
    for rel, text in texts.items():
        if rel in ZERO_SET:
            scanner = _Scanner(rel, ast.parse(text), sigs, True)
            scanner.run()
            scanners[rel] = scanner
    held: dict[str, list[tuple[str, ast.Call]]] = {}
    for rel, scanner in scanners.items():
        for fn, calls in scanner.helpers.items():
            held.setdefault(fn, []).extend((rel, c) for c in calls)
    sites: dict[str, list[bool]] = {}
    for scanner in scanners.values():
        for node in ast.walk(scanner.tree):
            if isinstance(node, ast.Call) and _name_of(node.func) in held:
                sites.setdefault(_name_of(node.func) or "", []).append(
                    scanner.site_is_protected(node)
                )
    cleared = {fn for fn in held if sites.get(fn) and all(sites[fn])}
    return [
        Finding("S6", rel, fn, _digest(call), call.lineno)
        for fn, calls in held.items()
        if fn not in cleared
        for rel, call in calls
    ]


def scan_source(rel: str, text: str, *, zero: bool | None = None) -> list[Finding]:
    """Findings in one source text (a snippet or a module). The refusal classes the text defines
    join the table; `zero` defaults to membership of `ZERO_SET`."""
    tree = ast.parse(text)
    sigs, own = refusal_classes([(rel, text)])
    is_zero = rel in ZERO_SET if zero is None else zero
    found = _Scanner(rel, tree, sigs, is_zero).run() + own + _copies_of_raise_bare(rel, tree)
    if is_zero:
        found += _snippet_s6(rel, text, sigs)
    return found


def _snippet_s6(rel: str, text: str, sigs: dict[str, Sig]) -> list[Finding]:
    scanner = _Scanner(rel, ast.parse(text), sigs, True)
    scanner.run()
    sites: dict[str, list[bool]] = {}
    for node in ast.walk(scanner.tree):
        if isinstance(node, ast.Call) and _name_of(node.func) in scanner.helpers:
            sites.setdefault(_name_of(node.func) or "", []).append(scanner.site_is_protected(node))
    cleared = {fn for fn in scanner.helpers if sites.get(fn) and all(sites[fn])}
    return [
        Finding("S6", rel, fn, _digest(call), call.lineno)
        for fn, calls in scanner.helpers.items()
        if fn not in cleared
        for call in calls
    ]


def scan_tree(src: Path) -> list[Finding]:
    """Every finding in `src` (the `decoy_engine` package directory)."""
    texts = {
        p.relative_to(src).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(src.rglob("*.py"))
    }
    return scan_texts(texts)


def scan_texts(texts: dict[str, str]) -> list[Finding]:
    """`scan_tree` over `{relative path: text}`, so the merge base can be scanned from git."""
    sigs, out = refusal_classes(texts.items())
    out = list(out)
    for rel, text in texts.items():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        out += _Scanner(rel, tree, sigs, rel in ZERO_SET).run()
        out += _copies_of_raise_bare(rel, tree)
    out += helper_findings(texts, sigs)
    return out


def baselined_counts(findings: Iterable[Finding]) -> dict[str, int]:
    """Site key to count for the findings that may sit in the baseline: S1 outside the zero set."""
    counts: dict[str, int] = {}
    for f in findings:
        if f.rule == "S1" and f.file not in ZERO_SET:
            counts[f.key] = counts.get(f.key, 0) + 1
    return counts
