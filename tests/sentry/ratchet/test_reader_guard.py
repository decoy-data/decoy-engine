"""RG-E1 A1: the checker reads inputs only through the one reader in ``_integrity.py``.

An AST scan of the checker modules (``tests/sentry/_ratchet.py`` and the underscore modules in
``tests/sentry/ratchet``) bars the filesystem and Git spellings that bypass it: ``glob``,
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
# primitive -> the (module, function) pairs that may use it
HOMES: dict[str, frozenset[tuple[str, str]]] = {
    "scandir": frozenset({(INTEGRITY, "list_entries")}),
    "listdir": frozenset({(INTEGRITY, "list_entries")}),
    "iterdir": frozenset({(INTEGRITY, "list_entries")}),
    "open": frozenset({(INTEGRITY, "open_input")}),
    "fdopen": frozenset({(INTEGRITY, "open_input")}),
    "read": frozenset({(INTEGRITY, "open_input")}),
    "read_text": frozenset({(INTEGRITY, "open_input")}),
    "read_bytes": frozenset({(INTEGRITY, "open_input")}),
    "stat": frozenset({(INTEGRITY, "_probe")}),
    "lstat": frozenset({(INTEGRITY, "_probe")}),
    "fstat": frozenset({(INTEGRITY, "_probe")}),
    "_git": frozenset({(INTEGRITY, "__init__"), (INTEGRITY, "blob"), (INTEGRITY, "_renames")}),
    "run": frozenset({(INTEGRITY, "_git"), (INTEGRITY, "resolve_commit"), (CHECKER, "_git_show")}),
}


def checker_modules() -> list[str]:
    folder = ROOT / "tests/sentry/ratchet"
    names = sorted(
        p.name
        for p in folder.iterdir()
        if p.suffix == ".py" and p.name[0] in "_" and p.name != "__init__.py"
    )
    return [
        CHECKER,
        *(f"tests/sentry/ratchet/{n}" for n in names),
        "tests/sentry/ratchet/__init__.py",
    ]


def violations(sources: dict[str, str]) -> list[str]:
    """``module:function: name`` for every barred spelling and every primitive outside its home."""
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

    def walk(node: ast.AST, module: str, func: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = node.name
        name = spelled(node)
        if name in BARRED:
            out.append(f"{module}:{func}: {name}")
        elif name in HOMES and not isinstance(node, ast.Constant):
            if (module, func) not in HOMES[name]:
                out.append(f"{module}:{func}: {name}")
        for child in ast.iter_child_nodes(node):
            walk(child, module, func)

    for module, text in sorted(sources.items()):
        walk(ast.parse(text), module, "<module>")
    return sorted(set(out))


def live_sources() -> dict[str, str]:
    return {m: (ROOT / m).read_text(encoding="utf-8") for m in checker_modules()}


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
