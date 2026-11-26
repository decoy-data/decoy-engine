"""AT-E1e: `config/_pre_scan.py` is the one place that adds `regex` to a detector set.

`canonical_detectors` puts `regex` first and keeps the canonical order. A second module that
builds `{*detectors, "regex"}` is a second copy of that rule (PRE-SCAN-RUN had one).

Covered shapes: a set, tuple or list literal that holds `"regex"` and one more element (a starred
element counts), `| {"regex"}` and `|= {"regex"}`, `+` or `+=` with a literal that holds
`"regex"`, and `.union(...)` with such a literal. Everything inside a subscript slice is skipped, so
`Literal["regex", "ner"]` does not match. A one-element default such as `("regex",)` does not
match. `.add("regex")` is not a shape: it records a flag source, not a detector set.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parents[3] / "src" / "decoy_engine"
OWNER = "config/_pre_scan.py"


def _is_regex(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value == "regex"


def _holds_regex(node: ast.expr) -> bool:
    return isinstance(node, ast.Set | ast.Tuple | ast.List) and any(_is_regex(e) for e in node.elts)


def regex_adders(source: str) -> list[int]:
    """Line numbers where a detector set is built by adding the literal `"regex"`."""
    tree = ast.parse(source)
    in_slice = {
        id(inner)
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        for inner in ast.walk(node.slice)
    }
    lines: list[int] = []
    for node in ast.walk(tree):
        if id(node) in in_slice:
            continue
        if isinstance(node, ast.Set | ast.Tuple | ast.List):
            if len(node.elts) >= 2 and any(_is_regex(e) for e in node.elts):
                lines.append(node.lineno)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr | ast.Add):
            if any(_holds_regex(side) for side in (node.left, node.right)):
                lines.append(node.lineno)
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.BitOr | ast.Add):
            if _holds_regex(node.value):
                lines.append(node.lineno)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "union"
        ):
            if any(_holds_regex(arg) for arg in node.args):
                lines.append(node.lineno)
    return lines


def test_only_the_config_model_adds_regex_to_a_detector_set() -> None:
    offenders = {}
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel == OWNER:
            continue
        lines = regex_adders(path.read_text(encoding="utf-8"))
        if lines:
            offenders[rel] = lines
    assert not offenders, f"regex added to a detector set outside {OWNER}: {offenders}"


def test_the_scanner_sees_each_shape_and_skips_the_look_alikes() -> None:
    seen = [
        'x = {*d, "regex"}',
        'x = ("regex", *d)',
        'x = ["ner", "regex"]',
        'x = {"regex", "ner"}',
        'x = d | {"regex"}',
        'x = {"regex"} | d',
        'x = tuple(sorted({*(p.get("detectors") or ()), "regex"}))',
        'd |= {"regex"}',
        'x = tuple(d) + ("regex",)',
        'x = ("regex",) + tuple(d)',
        'x = list(d) + ["regex"]',
        'x = set(d).union({"regex"})',
    ]
    for code in seen:
        assert regex_adders(code), code
    skipped = [
        'x: Literal["regex", "classifier", "ner"]',
        'x = get_args(Literal["regex", "ner"])',
        'x = ("regex",)',
        'found.add("regex")',
        'x = {"regex": 1}',
        'x = "regex" + suffix',
        'x = tuple(d) + ("ner",)',
        'x = set(d).union({"ner"})',
        'd |= {"ner"}',
    ]
    for code in skipped:
        assert not regex_adders(code), code
