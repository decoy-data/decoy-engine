"""RG-E1 A1: the checker reads inputs only through the one reader in ``_integrity.py``.

An AST scan of the checker modules (``tests/sentry/_ratchet.py`` and every non-test module in
``tests/sentry/ratchet``, whatever its name) bars the filesystem and Git spellings that bypass it: ``glob``,
``rglob``, ``isfile``, ``exists`` and their pathlib forms anywhere, and each raw primitive outside
the one function that owns it. Aliases, bound references, unbound method forms and ``getattr``
strings are all seen, because the scan looks at every attribute and name, not only at calls.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CHECKER = "tests/sentry/_ratchet.py"
INTEGRITY = "tests/sentry/ratchet/_integrity.py"

BARRED = frozenset(
    {"glob", "rglob", "iglob", "isfile", "isdir", "exists", "lexists", "is_file", "is_dir"}
)
# primitive -> the (module, owner) pairs that may use it. An owner is a qualified name
# (``Class.method`` or ``function``); a nested function is its own owner, so a helper defined
# inside an owner does not inherit the right to use the primitive.
HOMES: dict[str, frozenset[tuple[str, str]]] = {
    "scandir": frozenset({(INTEGRITY, "list_entries")}),
    "listdir": frozenset({(INTEGRITY, "list_entries")}),
    "iterdir": frozenset({(INTEGRITY, "list_entries")}),
    "children": frozenset({(INTEGRITY, "list_entries")}),
    "open": frozenset({(INTEGRITY, "open_input")}),
    "fdopen": frozenset({(INTEGRITY, "open_input")}),
    "read": frozenset({(INTEGRITY, "open_input")}),
    "read_text": frozenset({(INTEGRITY, "open_input")}),
    "read_bytes": frozenset({(INTEGRITY, "open_input")}),
    "blob": frozenset({(INTEGRITY, "open_input"), (INTEGRITY, "BaseTree.blob")}),
    "stat": frozenset({(INTEGRITY, "_probe")}),
    "lstat": frozenset({(INTEGRITY, "_probe")}),
    "fstat": frozenset({(INTEGRITY, "_probe")}),
    "_git": frozenset(
        {(INTEGRITY, "BaseTree.__init__"), (INTEGRITY, "BaseTree.blob"), (INTEGRITY, "_renames")}
    ),
    "run": frozenset({(INTEGRITY, "_git"), (INTEGRITY, "resolve_commit"), (CHECKER, "_git_show")}),
}


def checker_modules(root: Path = ROOT) -> list[str]:
    """The checker and every non-test module beside it, with or without a leading underscore."""
    folder = root / "tests/sentry/ratchet"
    names = sorted(
        p.name
        for p in folder.glob("*.py")
        if not p.name.startswith("test_") and p.name != "conftest.py"
    )
    return [CHECKER, *(f"tests/sentry/ratchet/{n}" for n in names)]


def _allowed(owners: frozenset[tuple[str, str]], module: str, owner: str) -> bool:
    return any(module == m and owner == o for m, o in owners)


def violations(sources: dict[str, str]) -> list[str]:
    """``module:owner: name`` for every barred spelling and every primitive outside its home."""
    out: list[str] = []

    def spelled(node: ast.AST) -> str | None:
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.alias):
            return node.name.rsplit(".", 1)[-1]
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value  # getattr(os.path, "isfile")
        return None

    def walk(node: ast.AST, module: str, owner: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            owner = node.name if owner == "<module>" else f"{owner}.{node.name}"
        name = spelled(node)
        if name in BARRED:
            out.append(f"{module}:{owner}: {name}")
        elif name in HOMES and not isinstance(node, ast.Constant):
            if not _allowed(HOMES[name], module, owner):
                out.append(f"{module}:{owner}: {name}")
        for child in ast.iter_child_nodes(node):
            walk(child, module, owner)

    for module, text in sorted(sources.items()):
        walk(ast.parse(text), module, "<module>")
    return sorted(set(out))


def live_sources(root: Path = ROOT) -> dict[str, str]:
    return {m: (root / m).read_text(encoding="utf-8") for m in checker_modules(root)}


def test_the_checker_reads_only_through_the_one_reader() -> None:
    assert violations(live_sources()) == []


def test_the_checker_imports_no_test_module() -> None:
    for module, text in live_sources().items():
        for node in ast.walk(ast.parse(text)):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not [n for n in names if n.rsplit(".", 1)[-1].startswith("test_")], module


SPELLINGS = (
    'Path(x).glob("*.json")',
    'p.rglob("*")',
    "os.path.isfile(x)",
    "os.path.exists(x)",
    "x.is_file()",
    "x.exists()",
    "x.is_dir()",
    "f = os.path.isfile",
    "g = Path.exists",
    'getattr(os.path, "isfile")',
    "os.scandir(x)",
    "os.listdir(x)",
    "x.iterdir()",
    "open(x)",
    "x.read_text()",
    "x.read_bytes()",
    "os.open(x, 0)",
    "os.lstat(x)",
    "x.stat()",
    "_git(a, b)",
    "subprocess.run(c)",
    "tree.blob(p)",
    "tree.children(d)",
)


@pytest.mark.parametrize("spelling", SPELLINGS)
def test_a_seeded_spelling_is_caught_in_a_sibling_function(spelling: str) -> None:
    seeded = {INTEGRITY: f"def other(x):\n    {spelling}\n"}
    assert violations(seeded) != []


@pytest.mark.parametrize("spelling", SPELLINGS)
def test_a_seeded_spelling_is_caught_in_a_second_module(spelling: str) -> None:
    seeded = {"tests/sentry/ratchet/_extra.py": f"def list_entries(x):\n    {spelling}\n"}
    assert violations(seeded) != []


def test_an_import_alias_of_a_barred_name_is_caught() -> None:
    seeded = {INTEGRITY: "from os.path import isfile as present\n"}
    assert violations(seeded) != []


@pytest.mark.parametrize(
    "func, call",
    [
        ("list_entries", "os.scandir(x)"),
        ("open_input", "open(x)"),
        ("_probe", "os.lstat(x)"),
    ],
)
def test_the_owning_function_may_use_its_primitive(func: str, call: str) -> None:
    seeded = {INTEGRITY: f"def {func}(x):\n    {call}\n"}
    assert violations(seeded) == []


def test_a_sibling_class_method_named_like_the_home_is_caught() -> None:
    seeded = {
        INTEGRITY: "class Other:\n    def open_input(self, p):\n        return p.read_bytes()\n"
    }
    assert violations(seeded) == [f"{INTEGRITY}:Other.open_input: read_bytes"]


def test_a_plain_helper_calling_the_git_blob_reader_is_caught() -> None:
    seeded = {INTEGRITY: "def helper(tree, path):\n    return tree.blob(path)\n"}
    assert violations(seeded) == [f"{INTEGRITY}:helper: blob"]


def test_the_git_reader_method_itself_may_run_git() -> None:
    seeded = {INTEGRITY: "class BaseTree:\n    def blob(self, p):\n        return _git(p)\n"}
    assert violations(seeded) == []


def test_a_module_without_a_leading_underscore_is_scanned(tmp_path: Path) -> None:
    folder = tmp_path / "tests/sentry/ratchet"
    folder.mkdir(parents=True)
    (tmp_path / "tests/sentry/_ratchet.py").write_text("X = 1\n", encoding="utf-8")
    (folder / "reader.py").write_text("def f(p):\n    return p.glob('*')\n", encoding="utf-8")
    (folder / "test_x.py").write_text("def test_a(p):\n    p.glob('*')\n", encoding="utf-8")
    (folder / "conftest.py").write_text("Y = 1\n", encoding="utf-8")
    sources = live_sources(tmp_path)
    assert sorted(sources) == [CHECKER, "tests/sentry/ratchet/reader.py"]
    assert violations(sources) == ["tests/sentry/ratchet/reader.py:f: glob"]


def test_a_nested_helper_inside_the_owner_does_not_inherit_its_right() -> None:
    seeded = {
        INTEGRITY: "def open_input(side, p):\n"
        "    def later():\n"
        "        return p.read_bytes()\n"
        "    return later\n"
    }
    assert violations(seeded) == [f"{INTEGRITY}:open_input.later: read_bytes"]
