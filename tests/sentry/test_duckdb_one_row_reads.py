"""Sentry: a DuckDB one-row read goes through `decoy_engine._duckdb_read`, never `.fetchone()`.

`fetchone()` leaves the SELECT result unfinished and DuckDB 2.x then rejects the next
`conn.register()` on that connection (ResourceInUseException). That broke the post-scan gate
and was found again in two connectors, so the class is closed here. A module that mentions
DuckDB and calls `.fetchone(` fails unless the site is allowlisted below; an entry is only
for a read after which the connection is closed, and it names why.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"

# (path under src/decoy_engine, enclosing function) -> why a fetchone is safe there.
ALLOWED: dict[tuple[str, str], str] = {
    ("execution/native/_pool_quality.py", "measure_pool_quality"): (
        "the connection is closed in the finally right after the read; nothing registers on it"
    ),
}


def _scope_names(tree: ast.AST) -> dict[int, str]:
    names: dict[int, str] = {}

    def walk(node: ast.AST, scope: str) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            scope = node.name
        for child in ast.iter_child_nodes(node):
            names[id(child)] = scope
            walk(child, scope)

    walk(tree, "<module>")
    return names


def fetchone_sites(root: Path) -> list[tuple[str, str]]:
    sites = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "duckdb" not in text.lower():
            continue
        tree = ast.parse(text)
        scopes = _scope_names(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "fetchone"
            ):
                sites.append((path.relative_to(root).as_posix(), scopes.get(id(node), "<module>")))
    return sites


def test_no_unlisted_fetchone_in_duckdb_modules() -> None:
    unlisted = [s for s in fetchone_sites(SRC) if s not in ALLOWED]
    assert unlisted == [], "use decoy_engine._duckdb_read.fetch_row or fetch_scalar"


def test_every_allowlist_entry_has_a_reason_and_a_live_site() -> None:
    live = set(fetchone_sites(SRC))
    for key, reason in ALLOWED.items():
        assert reason.strip(), key
        assert key in live, f"stale allowlist entry {key}"


def test_the_scan_flags_a_seeded_violation(tmp_path: Path) -> None:
    (tmp_path / "seed.py").write_text(
        "import duckdb\n\ndef count(conn):\n    return conn.execute('SELECT 1').fetchone()[0]\n",
        encoding="utf-8",
    )
    (tmp_path / "other.py").write_text("def f(c):\n    return c.fetchone()\n", encoding="utf-8")
    assert fetchone_sites(tmp_path) == [("seed.py", "count")]


@pytest.mark.parametrize("name", ["fetch_row", "fetch_scalar"])
def test_choke_point_drains_the_result(name: str) -> None:
    from decoy_engine import _duckdb_read

    class Cursor:
        drained = False

        def fetchall(self) -> list[tuple[int]]:
            self.drained = True
            return [(7,)]

    cursor = Cursor()
    got = getattr(_duckdb_read, name)(cursor)
    assert cursor.drained
    assert got in (7, (7,))
