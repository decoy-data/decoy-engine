"""Sentry (class 5): the `pointer` file-access label appears only at its named sites.

The label selects the one publish that fsyncs the parent and reports a failure after the rename.
A pointer file is replaced through `HeldPointer.swap` alone, so the label may be named only in
`publication/_current.py`. Every `Constant("pointer")` in `src/` must sit at an exact allowlisted
site: path, enclosing definition or assignment, and AST role. No module is allowed whole.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
Site = tuple[str, str, str]  # (path under decoy_engine/, enclosing name, AST role)

ALLOWED: frozenset[Site] = frozenset(
    {
        ("publication/_current.py", "LocalPointerStore._publish", "keyword:label"),
        ("fileaccess/_types.py", "StageLabel", "subscript-element"),
        ("fileaccess/_output.py", "STAGE_PREFIX", "dict-key"),
        ("fileaccess/_output.py", "DURABLE_REPLACE_LABELS", "set-element"),
        ("fileaccess/_output.py", "PRIVATE_LABELS", "set-element"),
    }
)


def _role(node: ast.AST, parent: ast.AST) -> str:
    if isinstance(parent, ast.keyword):
        return f"keyword:{parent.arg}"
    if isinstance(parent, ast.Dict) and node in parent.keys:
        return "dict-key"
    if isinstance(parent, ast.Set):
        return "set-element"
    if isinstance(parent, (ast.Tuple, ast.List)):
        return "subscript-element"
    return type(parent).__name__


def _enclosing(chain: list[ast.AST]) -> str:
    names: list[str] = []
    for node in chain:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(node.name)
    if names:
        return ".".join(names)
    for node in chain:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            return node.target.id
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            return node.targets[0].id
    return "<module>"


def _walk(node: ast.AST, chain: list[ast.AST], root: Path, rel: str, out: list[Site]) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Constant) and child.value == "pointer":
            out.append((rel, _enclosing([*chain, node]), _role(child, node)))
        _walk(child, [*chain, node], root, rel, out)


def pointer_sites(root: Path) -> list[Site]:
    """Every `Constant("pointer")` under `root`, as (path, enclosing name, role)."""
    found: list[Site] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        _walk(tree, [], root, path.relative_to(root).as_posix(), found)
    return found


def violations(root: Path) -> list[Site]:
    return [site for site in pointer_sites(root) if site not in ALLOWED]


def test_real_tree_names_the_label_only_at_allowed_sites() -> None:
    sites = pointer_sites(SRC)
    assert not [s for s in sites if s not in ALLOWED]
    assert set(sites) == ALLOWED  # non-vacuity: every allowed site is real


def _scratch(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return tmp_path


SEEDS = {
    "second call": (
        {
            "publication/_publish.py": 'def f(out):\n    out.begin("file", "replace", label="pointer")\n'
        },
        ("publication/_publish.py", "f", "keyword:label"),
    ),
    "aliased constant": (
        {
            "publication/_publish.py": 'LABEL = "pointer"\n\ndef f(out):\n    out.begin(label=LABEL)\n'
        },
        ("publication/_publish.py", "LABEL", "Assign"),
    ),
    "other assignment in an allowed file": (
        {"fileaccess/_output.py": 'OTHER: frozenset[str] = frozenset({"pointer"})\n'},
        ("fileaccess/_output.py", "OTHER", "set-element"),
    ),
    "same function name, wrong role": (
        {
            "publication/_current.py": 'class LocalPointerStore:\n    def _publish(self):\n        return "pointer"\n'
        },
        ("publication/_current.py", "LocalPointerStore._publish", "Return"),
    ),
    "allowed module, other function": (
        {
            "publication/_current.py": (
                'def other(out):\n    out.begin("file", "replace", label="pointer")\n'
            )
        },
        ("publication/_current.py", "other", "keyword:label"),
    ),
}


@pytest.mark.parametrize("name", sorted(SEEDS))
def test_seed_is_flagged(tmp_path: Path, name: str) -> None:
    files, expected = SEEDS[name]
    assert violations(_scratch(tmp_path, files)) == [expected]


def test_allowed_sites_pass_in_a_scratch_copy(tmp_path: Path) -> None:
    root = _scratch(
        tmp_path,
        {
            "publication/_current.py": (
                "class LocalPointerStore:\n    def _publish(self, leaf):\n"
                '        leaf.begin("file", "replace", label="pointer")\n'
            ),
            "fileaccess/_output.py": 'STAGE_PREFIX = {"pointer": "p"}\n',
        },
    )
    assert violations(root) == []
