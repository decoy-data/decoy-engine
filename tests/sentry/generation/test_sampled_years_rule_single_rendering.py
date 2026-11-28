"""The sampled-years rule is rendered once, in `contracts/distribution_snapshot.py`.

Every refusal that names it formats `SAMPLED_YEARS_RULE`. A second literal of the sentence, a
bare `9998`, or an f-string that formats both `MIN_YEAR` and `MAX_SAMPLED_YEAR` elsewhere is a
second rendering that can drift from the limits. The guard scans `src/decoy_engine`; its own test
seeds each shape in an in-memory module so the scan is known to see it.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"
OWNER = "contracts/distribution_snapshot.py"
PHRASES = ("sampled years must lie", "a sampled year is outside")


def _is_name(node: ast.AST, name: str) -> bool:
    return (isinstance(node, ast.Name) and node.id == name) or (
        isinstance(node, ast.Attribute) and node.attr == name
    )


def renderings(source: str) -> list[str]:
    """The shapes of a second rendering found in one module's source."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str) and any(p in node.value for p in PHRASES):
                found.append("phrase")
            if node.value == 9998 or node.value == "9998":
                found.append("literal-9998")
        elif isinstance(node, ast.JoinedStr):
            parts = [v.value for v in node.values if isinstance(v, ast.FormattedValue)]
            names = {n for p in parts for n in (_all_names(p))}
            if {"MIN_YEAR", "MAX_SAMPLED_YEAR"} <= names:
                found.append("fstring")
    return found


def _all_names(node: ast.AST) -> set[str]:
    return {
        n.id if isinstance(n, ast.Name) else n.attr
        for n in ast.walk(node)
        if isinstance(n, ast.Name | ast.Attribute)
    }


def test_the_rule_is_rendered_only_by_the_snapshot_contract() -> None:
    offenders = {}
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel == OWNER:
            continue
        shapes = renderings(path.read_text(encoding="utf-8"))
        if shapes:
            offenders[rel] = shapes
    assert not offenders, f"a second rendering of the sampled-years rule: {offenders}"


def test_the_owner_holds_the_rule() -> None:
    assert renderings((SRC / OWNER).read_text(encoding="utf-8")), "the owner no longer renders it"


def test_the_scan_sees_each_shape() -> None:
    assert renderings('raise X("sampled years must lie in 1..9998")') == ["phrase", "literal-9998"]
    assert "phrase" in renderings('M = "a sampled year is outside the range"')
    assert renderings("LIMIT = 9998") == ["literal-9998"]
    assert renderings('LIMIT = "9998"') == ["literal-9998"]
    second = 'msg = f"a sampled year is outside {MIN_YEAR}..{MAX_SAMPLED_YEAR}"'
    assert set(renderings(second)) == {"phrase", "fstring"}
    assert renderings('msg = f"{MIN_YEAR} to {c.MAX_SAMPLED_YEAR}"') == ["fstring"]
    assert renderings("MIN_YEAR = 1") == []
