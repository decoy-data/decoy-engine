"""G-ONE-PROBLEM-FORMATTER: the review functions format a `PipelineConfigError` in one place.

`config_problems_text` in `validation/starter_review.py` holds the cap and the value-free
"code at location" text. A second copy would drift on the cap or print more than a code and a
location, so no other source file may build that text.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
_FORMATTER = re.compile(r"\{p\.code\} at ")
_OWNER = SRC / "validation" / "starter_review.py"


def test_only_one_source_file_formats_a_config_problem() -> None:
    owners = sorted(p for p in SRC.rglob("*.py") if _FORMATTER.search(p.read_text("utf-8")))
    assert owners == [_OWNER]
    assert len(_FORMATTER.findall(_OWNER.read_text("utf-8"))) == 1


def test_the_post_scan_review_uses_the_shared_formatter() -> None:
    text = (SRC / "validation" / "finding_review.py").read_text("utf-8")
    assert "config_problems_text" in text
