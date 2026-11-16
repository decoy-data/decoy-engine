"""Shared fixtures for the SCAN-ML M3a pre-scan model pass tests.

One table, `customers`, holds the columns the acceptance tests need: an `email` column the regex
detectors miss (one cell in five is a real address, the rest are written `user(at)host`) that the
bundled classifier still labels `email`; a free-text `notes` column that names a person in one cell
in four; a `names` column of bare person names (two tokens a cell, so not free text); and an id.
The cells come from the M4 generators so both phases test against the same corpus shape.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from tests.unit.detection_verification import _scanml_m4_support as m4

ROWS = m4.CELLS
DETECTOR_LOGGER = logging.getLogger("decoy_engine").getChild("detectors").name
ALL_DETECTORS = ("regex", "classifier", "ner")


def obfuscated_emails(n: int = ROWS) -> list[str]:
    """Every fifth cell is a real address, the rest are not: the regex finds no email column."""
    return [f"user{i}@example.com" if i % 5 == 0 else f"user{i}(at)example.com" for i in range(n)]


def customers(notes: list[str] | None = None, emails: list[str] | None = None) -> pd.DataFrame:
    notes = m4.notes_column(4) if notes is None else notes
    return pd.DataFrame(
        {
            "id": range(len(notes)),
            "email": obfuscated_emails(len(notes)) if emails is None else emails,
            "notes": notes,
            "names": m4.short_names(len(notes)),
        }
    )


def source(tmp_path: Path, name: str, frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    path = tmp_path / f"{name}.csv"
    frame.to_csv(path, index=False)
    return {name: {"type": "file", "format": "csv", "path": str(path), "has_header": True}}


def pre_scan(*sources: str) -> Any:
    from decoy_engine.config import PreScanConfig

    return PreScanConfig(detectors=("regex", *sources))


def hits(scan: Any, table: str, column: str) -> tuple[Any, ...]:
    found = next(t for t in scan.tables if t.name == table)
    return found.model_hits.get(column, ())
