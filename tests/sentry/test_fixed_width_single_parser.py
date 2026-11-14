"""AT-17a: one module parses fixed-width records, so there is one record-width rule.

Only `profile/_fixed_width_reader.py` reads `.record_width` or `.exact_record_width` (in any
module) or calls `.readline(` in a module that references `FixedWidthLayout`. A second reader
would be a second copy of the overlong, short and cast rules, or a read that skips them. The
writer is the one named exception, for `.record_width` only (it sizes the line it emits).
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parents[2] / "src" / "decoy_engine"
READER = "profile/_fixed_width_reader.py"
WRITER = "profile/_fixed_width_writer.py"
_WIDTH_ATTRS = {"record_width", "exact_record_width"}


def mentions_layout(tree: ast.AST) -> bool:
    """Any reference to `FixedWidthLayout`: an import, a dotted-module attribute, or a name."""
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and any(a.name == "FixedWidthLayout" for a in n.names):
            return True
        if isinstance(n, ast.Import) and any(a.name.endswith("_fixed_width") for a in n.names):
            return True
        if isinstance(n, ast.Attribute) and n.attr == "FixedWidthLayout":
            return True
        if isinstance(n, ast.Name) and n.id == "FixedWidthLayout":
            return True
    return False


def parser_reads(source: str) -> dict[str, list[int]]:
    """Lines of width reads and `.readline(` calls, keyed by the spelling.

    The width names are unique to the layout, so they count in every module.
    `.readline(` is common, so it counts only in a module that references the layout.
    """
    tree = ast.parse(source)
    found: dict[str, list[int]] = {}
    layout_module = mentions_layout(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _WIDTH_ATTRS:
            found.setdefault(node.attr, []).append(node.lineno)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in _WIDTH_ATTRS
        ):
            found.setdefault(f"getattr:{node.args[1].value}", []).append(node.lineno)
        elif (
            layout_module
            and isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "readline"
        ):
            found.setdefault("readline", []).append(node.lineno)
    return found


def test_only_the_reader_parses_fixed_width() -> None:
    offenders: dict[str, dict[str, list[int]]] = {}
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel == READER:
            continue
        reads = parser_reads(path.read_text(encoding="utf-8"))
        if rel == WRITER:
            reads.pop("record_width", None)
        if reads:
            offenders[rel] = reads
    assert not offenders, f"fixed-width parsing outside {READER}: {offenders}"


def test_the_sentry_sees_the_reader_and_the_writer() -> None:
    assert {"record_width", "exact_record_width", "readline"} <= set(
        parser_reads((SRC / READER).read_text(encoding="utf-8"))
    )
    assert "record_width" in parser_reads((SRC / WRITER).read_text(encoding="utf-8"))


_IMPORT = "from decoy_engine.config import FixedWidthLayout\n"


def test_the_walk_sees_a_seeded_failing_case_per_spelling() -> None:
    assert parser_reads("w = spec.record_width\n") == {"record_width": [1]}
    assert parser_reads("w = layout.exact_record_width\n") == {"exact_record_width": [1]}
    assert parser_reads("w = getattr(spec, 'record_width')\n") == {"getattr:record_width": [1]}
    assert parser_reads(_IMPORT + "line = fh.readline()\n") == {"readline": [2]}
    aliased = (
        "import decoy_engine.config._fixed_width as fw\nL = fw.FixedWidthLayout\nfh.readline()\n"
    )
    assert parser_reads(aliased) == {"readline": [3]}
    dotted = "import decoy_engine\nL = decoy_engine.config.FixedWidthLayout\nfh.readline()\n"
    assert parser_reads(dotted) == {"readline": [3]}
    named = "def f(layout: FixedWidthLayout):\n    return fh.readline()\n"
    assert parser_reads(named) == {"readline": [2]}


def test_readline_alone_is_not_flagged_without_the_layout() -> None:
    assert parser_reads("line = fh.readline()\n") == {}
    assert parser_reads(_IMPORT + "x = spec.columns\n") == {}
