"""Read the owning paths out of docs/frozen-surfaces.md.

The map is the one list of frozen engine surfaces. The compat pre-flight gate
(scripts/check_compat_preflight.py) and the map sentry
(tests/sentry/release/test_frozen_surface_map.py) both read it through here, so a surface
cannot be frozen in one place and free in the other.
"""

from __future__ import annotations

import re
from pathlib import Path

MAP_PATH = Path(__file__).resolve().parents[2] / "docs" / "frozen-surfaces.md"
_SPAN = re.compile(r"`([^`]+)`")
# Map columns: surface, completeness source, owning code, pinning test or snapshot.
_OWNING, _PINNING = 2, 3
_SNAPSHOT_DIR = "tests/snapshots/frozen_schemas/"


def rows(table: str) -> list[list[str]]:
    """Body rows of the first Markdown table in ``table`` as stripped cells."""
    body = [line for line in table.splitlines() if line.startswith("|")][2:]
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in body]


def _tables(markdown: str) -> list[str]:
    """Each run of consecutive `|` lines, as its own text."""
    blocks: list[list[str]] = [[]]
    for line in markdown.splitlines():
        if line.startswith("|"):
            blocks[-1].append(line)
        elif blocks[-1]:
            blocks.append([])
    return ["\n".join(block) for block in blocks if block]


def frozen_prefixes(markdown: str) -> tuple[str, ...]:
    """Repo-relative path prefixes a change to which touches a frozen surface.

    Every `src/` span in an owning-code cell, plus each committed schema snapshot a row
    names as its pin. A directory ends in `/`, so a prefix match cannot reach a sibling.
    """
    found: dict[str, None] = {}
    for row in (r for t in _tables(markdown) for r in rows(t) if len(r) == 4):
        for span in _SPAN.findall(row[_OWNING]):
            if span.startswith("src/"):
                found[span] = None
        for span in _SPAN.findall(row[_PINNING]):
            if span.startswith(_SNAPSHOT_DIR):
                found[span] = None
    return tuple(found)


def load_frozen_prefixes(path: Path = MAP_PATH) -> tuple[str, ...]:
    return frozen_prefixes(path.read_text(encoding="utf-8"))
