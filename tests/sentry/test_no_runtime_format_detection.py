"""Sentry: no strategy detects a date format from its cells at run time (COLUMN-SHAPE-RULE E2).

Detection belongs to `decoy scan` and the starter config, which write the format for the user to
confirm. `_detect_format` is gone. `transforms/date_shift.py` keeps `_COMMON_FORMATS` only for
`text_mask`, whose date spans in free text are not a column shape. Two rules:

1. No module names `_detect_format` at all, and none outside `date_shift.py` and `text_mask.py`
   names `_COMMON_FORMATS`: by import, attribute, name or string constant (`getattr`, `importlib`).
   The walk covers all of `src/decoy_engine/`, including `execution/native/` and
   `execution/out_of_core/`.
2. In the date strategy modules, every `to_datetime(` call that parses cells (`pd.to_datetime` or a
   bare imported name) passes `format=`, so a column is read with the declared format or not at
   all. A call that builds dates from year, month and day columns (a dict argument) parses
   nothing and is exempt.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
HOME = "transforms/date_shift.py"
# `_detect_format` has no user. `_COMMON_FORMATS` is for date spans found inside prose.
HELPER_USERS = {
    "_detect_format": frozenset[str](),
    "_COMMON_FORMATS": frozenset({HOME, "transforms/text_mask.py"}),
}
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
        if isinstance(node, ast.alias) and node.name in HELPER_USERS:
            found.append((node.name, getattr(node, "lineno", 0)))
        elif isinstance(node, ast.Attribute) and node.attr in HELPER_USERS:
            found.append((node.attr, node.lineno))
        elif isinstance(node, ast.Name) and node.id in HELPER_USERS:
            found.append((node.id, node.lineno))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in HELPER_USERS
        ):
            found.append((node.value, node.lineno))
    return found


def test_detection_helpers_are_reached_only_by_the_free_text_strategies() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        for name, line in _names(ast.parse(path.read_text(encoding="utf-8"))):
            if rel not in HELPER_USERS[name]:
                offenders.append(f"{rel}:{line}: uses {name}")
    assert not offenders, offenders


def _parses_cells(call: ast.Call) -> bool:
    func = call.func
    named = (isinstance(func, ast.Attribute) and func.attr == "to_datetime") or (
        isinstance(func, ast.Name) and func.id == "to_datetime"
    )
    return named and not (call.args and isinstance(call.args[0], ast.Dict))


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
    by_string = ast.parse("getattr(module, '_detect_format')\n")
    assert [n for n, _ in _names(by_string)] == ["_detect_format"]
    for source in (
        "pd.to_datetime(series, errors='coerce')",
        "to_datetime(series, errors='coerce')",
    ):
        bare = ast.parse(source).body[0]
        assert isinstance(bare, ast.Expr) and isinstance(bare.value, ast.Call)
        assert _parses_cells(bare.value)
    built = ast.parse("pd.to_datetime({'year': y, 'month': m, 'day': d})").body[0]
    assert isinstance(built, ast.Expr) and isinstance(built.value, ast.Call)
    assert not _parses_cells(built.value)
