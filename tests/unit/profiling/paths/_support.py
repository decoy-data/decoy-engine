"""Fixtures for the path-observation tests: scan one JSON column built from cell texts."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from decoy_engine import reasons
from decoy_engine.profiling import ScanSet, scan_sources

COLUMN = "doc"


def write_cells(directory: Path, cells: Iterable[str], *, name: str = "t") -> dict[str, Any]:
    """A one-column CSV source whose cells are the given texts (an empty text is a null)."""
    path = directory / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([COLUMN])
        for cell in cells:
            writer.writerow([cell])
    return {"type": "file", "format": "csv", "path": str(path), "has_header": True}


def scan_cells(directory: Path, cells: Iterable[str], **kwargs: Any) -> ScanSet:
    return scan_sources({"t": write_cells(directory, cells)}, **kwargs)


def dumps(values: Iterable[Any]) -> list[str]:
    return [json.dumps(v) for v in values]


def observation(scan: ScanSet) -> Any:
    return scan.tables[0].nested.get(COLUMN)


def by_path(obs: Any) -> Mapping[str, Any]:
    return {p.path: p for p in obs.paths}


def warning_codes(scan: ScanSet) -> set[str]:
    return {w.code for w in scan.tables[0].warnings}


def ref(symbol: str) -> str:
    """The code string of a registered warning, by its registry symbol."""
    return getattr(reasons.warning, symbol).spec.ref.code
