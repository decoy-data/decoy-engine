"""Sentry: no strategy detects a date format from its cells at run time (COLUMN-SHAPE-RULE E2).

Detection belongs to `decoy scan` and the starter config, which write the format for the user to
confirm. `transforms/date_shift.py` keeps `_detect_format` and `_COMMON_FORMATS` only for the free
text strategies (`text_mask`, whose date spans are not a column shape). Two rules:

1. No module outside that allowlist names either helper, by import or by attribute. The walk
   covers all of `src/decoy_engine/`, including `execution/native/` and `execution/out_of_core/`.
2. In the date strategy modules, every `pd.to_datetime(` call that parses cells passes `format=`,
   so a column is read with the declared format or not at all. A call that builds dates from
   year, month and day columns (a dict argument) parses nothing and is exempt.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
HOME = "transforms/date_shift.py"
HELPERS = frozenset({"_detect_format", "_COMMON_FORMATS"})
# Free text date spans are found inside prose, not read from a column.
ALLOWED = frozenset({HOME, "transforms/text_mask.py"})
DATE_STRATEGY_MODULES = (
    "transforms/bucket_perturb.py",
    "transforms/date_shift.py",
    "execution/_strategies/_bucket_perturb.py",
    "execution/_strategies/_date_shift.py",
    "execution/native/_bucket_perturb_ext.py",
    "execution/native/_date_shift_ext.py",
    "execution/out_of_core/_bucket_native.py",
)


def _names(tree: ast.AST) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.alias) and node.name in HELPERS:
            found.append((node.name, getattr(node, "lineno", 0)))
        elif isinstance(node, ast.Attribute) and node.attr in HELPERS:
            found.append((node.attr, node.lineno))
        elif isinstance(node, ast.Name) and node.id in HELPERS:
            found.append((node.id, node.lineno))
    return found


def test_detection_helpers_are_reached_only_by_the_free_text_strategies() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in ALLOWED:
            continue
        for name, line in _names(ast.parse(path.read_text(encoding="utf-8"))):
            offenders.append(f"{rel}:{line}: uses {name}")
    assert not offenders, offenders


def _parses_cells(call: ast.Call) -> bool:
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr == "to_datetime"):
        return False
    return not (call.args and isinstance(call.args[0], ast.Dict))


def test_every_date_parse_in_a_date_strategy_passes_a_format() -> None:
    offenders: list[str] = []
    for rel in DATE_STRATEGY_MODULES:
        tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _parses_cells(node):
                fmt = {k.arg: k.value for k in node.keywords}.get("format")
                if fmt is None or (isinstance(fmt, ast.Constant) and fmt.value is None):
                    offenders.append(f"{rel}:{node.lineno}: to_datetime without a format")
    assert not offenders, offenders


def test_the_sentry_sees_the_bypasses_it_guards_against() -> None:
    """Each seeded spelling is caught, so a green walk means something."""
    imported = ast.parse("from decoy_engine.transforms.date_shift import _detect_format\n")
    assert [n for n, _ in _names(imported)] == ["_detect_format"]
    attribute = ast.parse("import x\nx.date_shift._COMMON_FORMATS\n")
    assert [n for n, _ in _names(attribute)] == ["_COMMON_FORMATS"]
    bare = ast.parse("pd.to_datetime(series, errors='coerce')").body[0]
    assert isinstance(bare, ast.Expr) and isinstance(bare.value, ast.Call)
    assert _parses_cells(bare.value)
    built = ast.parse("pd.to_datetime({'year': y, 'month': m, 'day': d})").body[0]
    assert isinstance(built, ast.Expr) and isinstance(built.value, ast.Call)
    assert not _parses_cells(built.value)
