"""Sentry: one capped env and one memory-cap setter, both in `_isolated_common.py`.

Seven copies of the capped child's env had drifted: #666 added the BLAS thread knobs to
`CAPPED_ENV` and the copies kept running without them. Two scripts also kept their own
`RLIMIT_DATA` setter. This guard parses (AST, not regex) every `*.py` under src, tests,
scripts, testflight and ci, and reports `path:line` for each of these outside
`src/decoy_engine/execution/_isolated_common.py`:

1. a string constant equal to the allocator-arena variable name (equality, so prose in a
   comment or docstring is not a finding). It covers a dict key, a subscript store,
   `setdefault`, `monkeypatch.setenv`, `os.putenv` and any other call that names the var;
2. a keyword argument of that name (`dict(NAME=...)`, `env.update(NAME=...)`);
3. a `setrlimit` call whose first argument is not a name or attribute ending in an RLIMIT
   other than `RLIMIT_DATA` and `RLIMIT_AS`, so computed first arguments are findings;
4. a recognized capped spawn whose `env=` is not built from `CAPPED_ENV`. A module is capped
   when it calls `apply_mem_cap` or `setrlimit`, passes `mem_cap_bytes` or `mem_cap_mb`,
   holds a string starting with `--mem-cap`, or references `CAPPED_ENV`. Spawns are
   `subprocess.Popen`, `run`, `call`, `check_call` and `check_output` under any module or
   direct-import alias, plus the fk-scale helper `run_worker`. Every reaching definition of
   the `env=` name must derive from `CAPPED_ENV`.

The one exemption: the constant of rule 1 as the first positional argument of `.get(...)` or
`getenv(...)`, which only read. Covered shapes are the ones above; other spellings (built
strings, `eval`, env files, spawns in modules with no rule-4 marker, an aliased
`CAPPED_ENV` import) are out of scope. There is no allowlist.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from decoy_engine.execution._isolated_common import CAPPED_ENV

ROOT = Path(__file__).resolve().parents[2]
CHOKE_POINT = ROOT / "src" / "decoy_engine" / "execution" / "_isolated_common.py"
SCANNED = ("src", "tests", "scripts", "testflight", "ci")

# Read from the constant itself so this file holds no copy of the name.
_VAR = next(k for k in CAPPED_ENV if k.startswith("MALLOC"))
_SPAWNS = frozenset({"Popen", "run", "call", "check_call", "check_output"})
_READ_CALLS = frozenset({"get", "getenv"})
_UNCAPPED_LIMITS = frozenset({"RLIMIT_DATA", "RLIMIT_AS"})
_UNKNOWN = frozenset({False})

State = dict[str, frozenset[bool]]


def _terminal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_capped_module(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if _terminal(node.func) in {"apply_mem_cap", "setrlimit"}:
                return True
            if any(k.arg in {"mem_cap_bytes", "mem_cap_mb"} for k in node.keywords):
                return True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("--mem-cap"):
                return True
        elif _terminal(node) == "CAPPED_ENV":
            return True
    return False


def _spawn_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Local names bound to the subprocess module, and to one of its spawn functions."""
    modules: set[str] = set()
    functions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.asname or a.name for a in node.names if a.name == "subprocess"}
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess" and node.level == 0:
            functions |= {a.asname or a.name for a in node.names if a.name in _SPAWNS}
    return modules, functions


class _Rule4:
    """Walks one module in control-flow order and checks each recognized spawn's env.

    `State` maps a name to the set of "derives from CAPPED_ENV" verdicts of every definition
    that can reach the current point. A name derives only when all of them do.
    """

    def __init__(self, tree: ast.Module, path: str) -> None:
        self.path = path
        self.modules, self.functions = _spawn_aliases(tree)
        self.found: list[str] = []
        self.deferred: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, State]] = []
        end = self.block(tree.body, {})
        while self.deferred:
            node, outer = self.deferred.pop(0)
            self.function(node, {**end, **outer})

    # -- derivation -------------------------------------------------------------------

    def derives(self, node: ast.expr | None, state: State) -> bool:
        if node is None:
            return False
        if _terminal(node) == "CAPPED_ENV":
            return True
        if isinstance(node, ast.Name):
            defs = state.get(node.id)
            return bool(defs) and all(defs)
        if isinstance(node, ast.Dict):
            return any(
                k is None and self.unpack_derives(v, state)
                for k, v in zip(node.keys, node.values, strict=True)
            )
        if isinstance(node, ast.IfExp):
            return self.derives(node.body, state) and self.derives(node.orelse, state)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return self.derives(node.left, state) or self.derives(node.right, state)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "copy":
                return self.derives(node.func.value, state)
            if _terminal(node.func) == "dict":
                args = [*node.args, *(k.value for k in node.keywords if k.arg is None)]
                return any(self.unpack_derives(a, state) for a in args)
        return False

    def unpack_derives(self, node: ast.expr, state: State) -> bool:
        """`**(CAPPED_ENV if capped else {})` counts: the unpack opts in on one branch."""
        if isinstance(node, ast.IfExp):
            return self.unpack_derives(node.body, state) or self.unpack_derives(node.orelse, state)
        return self.derives(node, state)

    # -- spawns -----------------------------------------------------------------------

    def is_spawn(self, call: ast.Call) -> bool:
        func = call.func
        if isinstance(func, ast.Attribute):
            return (
                isinstance(func.value, ast.Name)
                and func.value.id in self.modules
                and func.attr in _SPAWNS
            )
        return isinstance(func, ast.Name) and (func.id in self.functions or func.id == "run_worker")

    def check_calls(self, nodes: list[ast.AST], state: State) -> None:
        for root in nodes:
            for call in ast.walk(root):
                if not (isinstance(call, ast.Call) and self.is_spawn(call)):
                    continue
                env = next((k.value for k in call.keywords if k.arg == "env"), None)
                if not self.derives(env, state):
                    self.found.append(f"{self.path}:{call.lineno}")

    # -- control flow -----------------------------------------------------------------

    def function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, outer: State) -> None:
        state = dict(outer)
        a = node.args
        for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]:
            if arg is not None:
                state[arg.arg] = _UNKNOWN
        self.block(node.body, state)

    @staticmethod
    def merge(*states: State) -> State:
        merged: State = {}
        for state in states:
            for name, defs in state.items():
                merged[name] = merged.get(name, frozenset()) | defs
        return merged

    def block(self, body: list[ast.stmt], state: State) -> State:
        state = dict(state)
        for stmt in body:
            state = self.statement(stmt, state)
        return state

    def assign(self, state: State, target: ast.expr, defs: frozenset[bool]) -> None:
        if isinstance(target, ast.Name):
            state[target.id] = defs
        elif isinstance(target, ast.Tuple | ast.List):
            for elt in target.elts:
                self.assign(state, elt, _UNKNOWN)

    def statement(self, stmt: ast.stmt, state: State) -> State:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            self.deferred.append((stmt, dict(state)))
            return state
        if isinstance(stmt, ast.ClassDef):
            return self.merge(state, self.block(stmt.body, state))
        own = [
            c for c in ast.iter_child_nodes(stmt) if not isinstance(c, ast.stmt | ast.excepthandler)
        ]
        self.check_calls(own, state)
        state = dict(state)
        if isinstance(stmt, ast.Assign):
            defs = frozenset({self.derives(stmt.value, state)})
            for target in stmt.targets:
                self.assign(state, target, defs)
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            self.assign(state, stmt.target, frozenset({self.derives(stmt.value, state)}))
        elif isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name):
            if isinstance(stmt.op, ast.BitOr) and self.derives(stmt.value, state):
                state[stmt.target.id] = frozenset({True})
        elif isinstance(stmt, ast.If):
            return self.merge(self.block(stmt.body, state), self.block(stmt.orelse, state))
        elif isinstance(stmt, ast.For | ast.AsyncFor | ast.While):
            if isinstance(stmt, ast.For | ast.AsyncFor):
                self.assign(state, stmt.target, _UNKNOWN)
            looped = self.merge(state, self.block(stmt.body, state))
            return self.merge(looped, self.block(stmt.orelse, looped))
        elif isinstance(stmt, ast.With | ast.AsyncWith):
            return self.block(stmt.body, state)
        elif isinstance(stmt, ast.Try):
            after = self.merge(state, self.block(stmt.body, state))
            branches = [after, *(self.block(h.body, after) for h in stmt.handlers)]
            joined = self.merge(*branches, self.block(stmt.orelse, after))
            return self.block(stmt.finalbody, joined)
        return state


def scan_source(source: str, path: str = "mod.py") -> list[str]:
    """Findings for one module's source, as `path:line` strings."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    exempt = {
        id(call.args[0])
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and call.args and _terminal(call.func) in _READ_CALLS
    }
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == _VAR and id(node) not in exempt:
            found.append(f"{path}:{node.lineno}")
        elif isinstance(node, ast.keyword) and node.arg == _VAR:
            found.append(f"{path}:{node.value.lineno}")
        elif isinstance(node, ast.Call) and _terminal(node.func) == "setrlimit":
            first = node.args[0] if node.args else None
            name = _terminal(first) if first is not None else None
            safe = (
                isinstance(first, ast.Name | ast.Attribute)
                and name is not None
                and name.startswith("RLIMIT_")
                and name not in _UNCAPPED_LIMITS
            )
            if not safe:
                found.append(f"{path}:{node.lineno}")
    if _is_capped_module(tree):
        found += _Rule4(tree, path).found
    return sorted(set(found))


def scan_tree(root: Path) -> list[str]:
    findings: list[str] = []
    for top in SCANNED:
        for path in sorted((root / top).rglob("*.py")):
            if path == CHOKE_POINT or ".venv" in path.parts:
                continue
            rel = path.relative_to(root).as_posix()
            findings += scan_source(path.read_text(encoding="utf-8"), rel)
    return findings


def test_no_capped_env_copy_outside_isolated_common() -> None:
    assert scan_tree(ROOT) == []


_MARK = 'FLAG = "--mem-cap-mb"\n'
_SP = "import subprocess as sp\n"
_FROM = "from subprocess import Popen\n"
_FROM_AS = "from subprocess import run as r\n"
_IMPORT = "from decoy_engine.execution._isolated_common import CAPPED_ENV\n"
_PLAIN = "{**os.environ}"
_CAPPED = "{**os.environ, **CAPPED_ENV}"

FOUND = {
    "dict key": f'env = {{"{_VAR}": "2"}}\n',
    "dict() keyword": f'env = dict({_VAR}="2")\n',
    "subscript store": f'env["{_VAR}"] = "2"\n',
    "setdefault": f'env.setdefault("{_VAR}", "2")\n',
    "update keyword": f'env.update({_VAR}="2")\n',
    "monkeypatch": f'monkeypatch.setenv("{_VAR}", "2")\n',
    "putenv": f'os.putenv("{_VAR}", "2")\n',
    "setrlimit data": "resource.setrlimit(resource.RLIMIT_DATA, (1, 1))\n",
    "setrlimit from-import": "from resource import setrlimit\nsetrlimit(RLIMIT_AS, (1, 1))\n",
    "setrlimit computed": "resource.setrlimit(_RLIMITS[kind], (1, 1))\n",
    "module alias, plain env": _MARK + _SP + f"sp.Popen(cmd, env={_PLAIN})\n",
    "direct import, plain env": _MARK + _FROM + f"Popen(cmd, env={_PLAIN})\n",
    "direct alias, plain env": _MARK + _FROM_AS + f"r(cmd, env={_PLAIN})\n",
    "no env": _MARK + "import subprocess\nsubprocess.run(cmd)\n",
    "direct plain env": _MARK + f"import subprocess\nsubprocess.run(cmd, env={_PLAIN})\n",
    "local plain env": (
        _MARK + "import subprocess\nenv = dict(os.environ)\nsubprocess.run(cmd, env=env)\n"
    ),
    "run_worker plain env": _MARK + f"plain = {_PLAIN}\nrun_worker(cmd, env=plain)\n",
    "branch replaces capped": (
        _IMPORT
        + "import subprocess\n"
        + f"env = {_PLAIN}\n"
        + f"if flag:\n    env = {_CAPPED}\n"
        + "subprocess.run(cmd, env=env)\n"
    ),
    "capped then replaced": (
        _IMPORT
        + "import subprocess\n"
        + "def go(flag):\n"
        + f"    env = {_CAPPED}\n"
        + f"    if flag:\n        env = {_PLAIN}\n"
        + "    subprocess.run(cmd, env=env)\n"
    ),
    "env is a parameter": (
        _MARK + "import subprocess\ndef go(env):\n    subprocess.run(cmd, env=env)\n"
    ),
}

NOT_FOUND = {
    "environ.get": f'os.environ.get("{_VAR}")\n',
    "getenv": f'os.getenv("{_VAR}")\n',
    "prose in docstring": f'"""Pins {_VAR} for the child."""\n',
    "setrlimit core": "resource.setrlimit(resource.RLIMIT_CORE, (0, 0))\n",
    "setrlimit in a string": 'CHILD = "resource.setrlimit(resource.RLIMIT_DATA, (1, 1))"\n',
    "module alias, capped env": _MARK + _IMPORT + _SP + f"sp.Popen(cmd, env={_CAPPED})\n",
    "direct import, capped env": _MARK + _IMPORT + _FROM + f"Popen(cmd, env={_CAPPED})\n",
    "direct alias, capped env": _MARK + _IMPORT + _FROM_AS + f"r(cmd, env={_CAPPED})\n",
    "direct capped env": (
        _MARK + _IMPORT + f"import subprocess\nsubprocess.run(cmd, env={_CAPPED})\n"
    ),
    "local capped env": (
        _IMPORT + f"import subprocess\nenv = {_CAPPED}\nsubprocess.run(cmd, env=env)\n"
    ),
    "conditional unpack": (
        _IMPORT
        + "import subprocess\n"
        + "subprocess.run(cmd, env={**os.environ, **(CAPPED_ENV if capped else {})})\n"
    ),
    "both branches capped": (
        _IMPORT
        + "import subprocess\n"
        + "if flag:\n    env = {**os.environ, **CAPPED_ENV, 'A': '1'}\n"
        + f"else:\n    env = {_CAPPED}\n"
        + "subprocess.run(cmd, env=env)\n"
    ),
    "unmarked module": "import subprocess\nsubprocess.run(cmd)\n",
}


@pytest.mark.parametrize("source", FOUND.values(), ids=FOUND.keys())
def test_the_scan_finds_the_shape(source: str) -> None:
    assert scan_source(source) != []


@pytest.mark.parametrize("source", NOT_FOUND.values(), ids=NOT_FOUND.keys())
def test_the_scan_leaves_the_shape_alone(source: str) -> None:
    assert scan_source(source) == []
