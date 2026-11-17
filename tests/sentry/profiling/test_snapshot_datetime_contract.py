"""One decoder owns the stored datetime bucket format.

No reader in generation or in the two fidelity scorers may read `year_bins`, `start_year`,
`end_year` or a bucket's `year` key itself. They take the normalized buckets from the contract.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).parents[3] / "src" / "decoy_engine"
_READERS = [
    *sorted((_SRC / "generation").rglob("*.py")),
    _SRC / "quality" / "fidelity.py",
    _SRC / "quality" / "shape_fidelity.py",
]
_FORBIDDEN = {"year_bins", "start_year", "end_year", "year"}


def _key(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def bypasses(source: str) -> list[int]:
    """Line numbers that read a stored bucket key: `x["year"]`, `x.get("year_bins")` and the like.
    A bare string (a refusal's property name, prose) is not a read."""
    lines = []
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.Subscript):
            key = _key(n.slice)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.args:
            key = _key(n.args[0]) if n.func.attr in {"get", "pop", "setdefault"} else None
        else:
            continue
        if key in _FORBIDDEN:
            lines.append(n.lineno)
    return lines


def test_no_reader_parses_a_stored_bucket_outside_the_contract() -> None:
    found = {str(p.relative_to(_SRC)): bypasses(p.read_text()) for p in _READERS}
    assert {k: v for k, v in found.items() if v} == {}


def test_the_sentry_sees_a_seeded_direct_parse() -> None:
    assert bypasses('def f(stats):\n    return [b["year"] for b in stats["year_bins"]]\n')
    assert bypasses('def f(b):\n    return b.get("start_year")\n')
    assert not bypasses(
        'def f():\n    """year_bins in prose."""\n    return _refuse("year_bins")\n'
    )
