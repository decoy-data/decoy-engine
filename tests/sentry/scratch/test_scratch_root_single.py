"""Sentry S-G6a (F25 G6-1): one function selects the engine's temp root.

Only `fileaccess._protected_dir.scratch_root` reads `tempfile.gettempdir`, the stdlib cache
`tempfile.tempdir` or the TMPDIR, TEMP and TMP variables. Nothing under `src/` spells `/tmp`.
Two places deriving one root is how the disk cap and the arena came to agree by luck.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.sentry.fa import sinks
from tests.sentry.fa.resolve import ProjectIndex, Scope, resolve
from tests.sentry.fa.rules import indexed_modules, scoped_nodes
from tests.sentry.fa.scan import scan_tree

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
CHOKE = ("decoy_engine/fileaccess/_protected_dir.py", "scratch_root")
TEMP_VARS = frozenset({"TMPDIR", "TEMP", "TMP"})
CACHE = "tempfile.tempdir"
ENV_CALLS = frozenset(
    {"os.getenv", "os.putenv", "os.environ.get", "os.environ.setdefault", "os.environ.pop"}
)


def _is_temp_var(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value in TEMP_VARS


def _docstrings(tree: ast.Module) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def _what(node: ast.AST, scope: Scope, index: ProjectIndex, docs: set[int]) -> str | None:
    """Which banned form `node` is, or None."""
    if isinstance(node, (ast.Name, ast.Attribute)):
        name = resolve(node, scope, index)
        if name in sinks.TEMP_ROOT_READS or name == CACHE:
            return name
    elif isinstance(node, ast.Call):
        # `getattr(tempfile, "gettempdir")` resolves to the attribute it fetches.
        got = resolve(node, scope, index)
        if got in sinks.TEMP_ROOT_READS or got == CACHE:
            return got
        if resolve(node.func, scope, index) in ENV_CALLS and node.args:
            return "a temp variable read" if _is_temp_var(node.args[0]) else None
    elif isinstance(node, ast.Subscript):
        if resolve(node.value, scope, index) == "os.environ" and _is_temp_var(node.slice):
            return "a temp variable read"
    elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        names = {e.value for e in node.elts if isinstance(e, ast.Constant)}
        if len(names & TEMP_VARS) >= 2:
            return "a loop over the temp variables"
    elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
        if node.value == "/tmp" or node.value.startswith("/tmp/"):
            return "a /tmp path"
    return None


def root_findings(src: Path) -> list[str]:
    _, index = scan_tree(src)
    out: list[str] = []
    for rel, name, tree, pkg in indexed_modules(index):
        docs = _docstrings(tree)
        for qual, node, scope in scoped_nodes(tree, name, pkg):
            what = _what(node, scope, index, docs)
            allowed = (rel, qual) == CHOKE and what != "a /tmp path"
            if what is not None and not allowed:
                out.append(f"{rel}:{getattr(node, 'lineno', 0)} {qual}: {what}")
    return sorted(set(out))


def test_only_scratch_root_selects_the_temp_root() -> None:
    assert root_findings(SRC) == []


_CHOKE = '''"""The allocator."""
import os
import tempfile


def scratch_root():
    for name in ("TMPDIR", "TEMP", "TMP"):
        if os.environ.get(name):
            return os.environ[name]
    return tempfile.gettempdir()
'''
_SEEDS = {
    "gettempdir": "import tempfile\n\n\ndef root():\n    return tempfile.gettempdir()\n",
    "gettempdirb": "import tempfile\n\n\ndef root():\n    return tempfile.gettempdirb()\n",
    "alias": "from tempfile import gettempdir as g\n\n\ndef root():\n    return g()\n",
    "as_value": "import tempfile\n\nREAD = tempfile.gettempdir\n",
    "cache_read": "import tempfile\n\n\ndef root():\n    return tempfile.tempdir\n",
    "cache_write": "import tempfile\n\n\ndef reset():\n    tempfile.tempdir = None\n",
    "env_subscript": "import os\n\n\ndef root():\n    return os.environ['TMPDIR']\n",
    "env_getenv": "import os\n\n\ndef root():\n    return os.getenv('TEMP')\n",
    "env_get": "import os\n\n\ndef root():\n    return os.environ.get('TMP')\n",
    "getattr_gettempdir": "import tempfile\n\n\ndef root():\n    return getattr(tempfile, 'gettempdir')()\n",
    "getattr_cache": "import tempfile\n\n\ndef root():\n    return getattr(tempfile, 'tempdir')\n",
    "env_loop": (
        "import os\n\n\ndef root():\n"
        "    for name in ('TMPDIR', 'TEMP', 'TMP'):\n        os.environ.get(name)\n"
    ),
    "slash_tmp": "def root():\n    return '/tmp'\n",
    "slash_tmp_child": "def root():\n    return '/tmp/decoy'\n",
}


def _seed(root: Path, files: dict[str, str]) -> Path:
    pkg = root / "decoy_engine" / "fileaccess"
    pkg.mkdir(parents=True)
    (pkg.parent / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    for rel, body in files.items():
        (pkg.parent / rel).write_text(body)
    return root


def test_the_choke_point_alone_is_clean(tmp_path: Path) -> None:
    clean = _seed(tmp_path, {"fileaccess/_protected_dir.py": _CHOKE})
    assert root_findings(clean) == []  # non-vacuity: the seeds below start from this


@pytest.mark.parametrize("cell", sorted(_SEEDS))
def test_a_seeded_second_selector_is_seen(tmp_path: Path, cell: str) -> None:
    files = {"fileaccess/_protected_dir.py": _CHOKE, "execution.py": _SEEDS[cell]}
    assert root_findings(_seed(tmp_path, files)), f"{cell} went unseen"


def test_a_second_function_in_the_choke_module_is_seen(tmp_path: Path) -> None:
    files = {
        "fileaccess/_protected_dir.py": _CHOKE + "\n\n" + _SEEDS["gettempdir"].split("\n\n\n")[1]
    }
    assert root_findings(_seed(tmp_path, files))


def test_the_old_spill_estimate_call_is_seen(tmp_path: Path) -> None:
    old = "import tempfile\nfrom pathlib import Path\n\n\ndef default_ooc_temp_root():\n    return Path(tempfile.gettempdir())\n"
    files = {"fileaccess/_protected_dir.py": _CHOKE, "spill_estimate.py": old}
    assert root_findings(_seed(tmp_path, files))
