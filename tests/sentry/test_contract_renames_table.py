"""The contract's public renames table keeps its shape and its symbols resolve (S7c).

Section 1 of `docs/compatibility-contract.md` owns the table. A `symbol` row names dotted import
paths: every new path must import, every old path must not.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "compatibility-contract.md"
COLUMNS = ["old", "new", "kind", "since", "note"]
KINDS = {"symbol", "wire key", "config key", "reason code", "CLI-visible label"}
BLOCK = re.compile(r"<!-- renames-table:start -->\n(.*?)<!-- renames-table:end -->", re.S)


def _rows() -> list[dict[str, str]]:
    block = BLOCK.search(CONTRACT.read_text(encoding="utf-8"))
    assert block, "renames table markers missing from the contract"
    lines = [ln for ln in block.group(1).splitlines() if ln.startswith("|")]
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    assert header == COLUMNS, header
    rows = [[c.strip() for c in ln.strip("|").split(" | ")] for ln in lines[2:]]
    assert all(len(r) == len(COLUMNS) for r in rows)
    return [dict(zip(COLUMNS, r, strict=True)) for r in rows]


def _names(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def _resolves(path: str) -> bool:
    parts = path.split(".")
    for i in range(len(parts), 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:i]))
        except ImportError:
            continue
        for attr in parts[i:]:
            if not hasattr(obj, attr):
                return False
            obj = getattr(obj, attr)
        return True
    return False


def test_table_shape() -> None:
    rows = _rows()
    assert len(rows) >= 12 and {"run_storm: true", "storm.scan"} <= {
        n for r in rows for n in _names(r["old"])
    }
    for r in rows:
        assert r["kind"] in KINDS, r
        assert re.fullmatch(r"\d+\.\d+\.\d+", r["since"]), r
        assert _names(r["old"]) and _names(r["new"]), r
        assert r["note"], r


def test_symbol_rows_resolve() -> None:
    symbols = [r for r in _rows() if r["kind"] == "symbol"]
    assert symbols
    for r in symbols:
        for new in _names(r["new"]):
            assert _resolves(new), f"new symbol does not import: {new}"
        for old in _names(r["old"]):
            assert not _resolves(old), f"retired symbol still imports: {old}"
