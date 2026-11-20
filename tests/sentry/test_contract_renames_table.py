"""The contract's public renames table keeps its shape and its symbols resolve (S7c).

Section 1 of `docs/compatibility-contract.md` owns the table. A `symbol` row names dotted import
paths: every new path must import, every old path must not.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from tests.sentry.test_no_residual_removed_surface import RETIRED_NAME

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "compatibility-contract.md"
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
    assert len(rows) >= 12 and {f"run_{RETIRED_NAME}: true", f"{RETIRED_NAME}.scan"} <= {
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


def _section(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
    assert m, f"CHANGELOG has no section for {version}"
    return re.sub(r"[\s`'\"]", "", m.group(1))


# Released CHANGELOG sections are pinned, so two renames stay recorded under the wrong release
# (the tags show where they first shipped): the profiler taxonomy split is written up under 0.11.0
# and shipped in 0.16.0; the custom provider variable is written up under 0.25.0 and shipped in
# 0.24.0. Keyed by the row's first old name to (release from the tags, section holding the entry);
# the row's `since` must equal the pinned release, so these rows cannot drift to the CHANGELOG one.
RECORDED_UNDER = {
    f"decoy_engine.{RETIRED_NAME}": ("0.16.0", "0.11.0"),
    f"decoy_engine.run_{RETIRED_NAME}": ("0.16.0", "0.11.0"),
    f"decoy_engine.{RETIRED_NAME.title()}Profile": ("0.16.0", "0.11.0"),
    f"decoy_engine.run_{RETIRED_NAME}_post_mask": ("0.16.0", "0.11.0"),
    f"decoy_engine.{RETIRED_NAME.title()}PostMaskReport": ("0.16.0", "0.11.0"),
    "CUSTOM_PROVIDERS_DIR": ("0.24.0", "0.25.0"),
}


def test_since_matches_the_changelog_section() -> None:
    # A row that points at the wrong release fails: the section for `since` (or, for a known
    # misplaced entry, its pinned release and section) must name the old or the new name. A
    # reason code may appear without its namespace.
    for r in _rows():
        recorded = r["since"]
        pinned = RECORDED_UNDER.get(_names(r["old"])[0])
        if pinned is not None:
            assert r["since"] == pinned[0], f"{r['old']} first shipped in {pinned[0]}"
            recorded = pinned[1]
        section = _section(recorded)
        names = _names(r["old"]) + _names(r["new"])
        if r["kind"] == "reason code":
            names += [n.rsplit("/", 1)[-1] for n in names]
        if r["kind"] == "symbol":
            names += [n.rsplit(".", 1)[-1] for n in names]
        assert any(re.sub(r"[\s`'\"]", "", n) in section for n in names), (
            f"CHANGELOG {recorded} names neither side of: {r['old']}"
        )
