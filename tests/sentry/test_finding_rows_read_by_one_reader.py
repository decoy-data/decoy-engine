"""G-ONE-FINDING-READER: a persisted finding row is read in `postmask/finding_reader.py` only.

The strict reader (`read_residual_finding`) and the verdict's tolerant projection
(`project_for_verdict`) share one version rule and one field table. A second parser of the same
row would let a v2 row mean one thing to the run gate and another to the review, so the verdict
module and the review may not index or `.get` a finding's own fields.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
FINDING_KEYS = frozenset(
    {"source", "severity", "model", "band", "table", "column", "detector_id", "match_rate"}
)
GUARDED = (SRC / "verification" / "postmask" / "_blocked.py",)
READ_ONLY_VIA_READER = (SRC / "validation" / "finding_review.py",)


def _direct_reads(path: Path, *, subscripts: bool) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in FINDING_KEYS
        ):
            hits.append(f"{path.name}:{node.lineno} .get({node.args[0].value!r})")
        if (
            subscripts
            and isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value in FINDING_KEYS
        ):
            hits.append(f"{path.name}:{node.lineno} [{node.slice.value!r}]")
    return hits


def test_the_verdict_reads_finding_fields_only_through_the_projection() -> None:
    hits = [h for p in GUARDED for h in _direct_reads(p, subscripts=True)]
    assert not hits, f"parse finding rows in finding_reader.py instead: {hits}"


def test_the_review_does_not_get_finding_fields_off_a_raw_row() -> None:
    hits = [h for p in READ_ONLY_VIA_READER for h in _direct_reads(p, subscripts=False)]
    assert not hits, f"parse finding rows in finding_reader.py instead: {hits}"


def test_the_guard_sees_a_seeded_direct_read(tmp_path: Path) -> None:
    seeded = tmp_path / "seed.py"
    seeded.write_text('def f(row):\n    return row.get("severity"), row["source"]\n')
    assert len(_direct_reads(seeded, subscripts=True)) == 2
