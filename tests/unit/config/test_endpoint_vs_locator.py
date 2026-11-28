"""AT-7: the S3 endpoint validator is never weaker than the locator recognizer.

The validator is a separate, stricter check by design (it also refuses percent-encoded marks).
This pins the relation: every http(s) row the recognizer says carries credentials is refused.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from decoy_engine.config import S3Source

CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "locator_credentials" / "cases.json").read_text(
        encoding="utf-8"
    )
)
HTTP_CARRIES = [
    r for r in CASES if r["carries"] and r["input"].lower().startswith(("http://", "https://"))
]


def test_the_selection_is_not_empty() -> None:
    assert len(HTTP_CARRIES) >= 8


@pytest.mark.parametrize("row", HTTP_CARRIES, ids=[r["id"] for r in HTTP_CARRIES])
def test_every_carrying_http_row_is_refused(row: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        S3Source.model_validate(
            {"type": "s3", "format": "csv", "bucket": "b", "key": "k", "endpoint_url": row["input"]}
        )
